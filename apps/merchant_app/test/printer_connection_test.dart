import 'package:flutter_test/flutter_test.dart';
import 'package:merchant_app/services/printer.dart';
import 'package:merchant_app/services/printer_transport.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// When the printer connection is rebuilt, and what happens when a write fails.
///
/// This exists because the transport cannot be tried against a printer from
/// where it is written, and the previous version was wrong in the one way that
/// produces no symptom: it asked the plugin whether it was connected, and a
/// buffered write to a sleeping printer answers yes. A ticket went into a dead
/// socket, the plugin reported success, and the stall was told nothing while no
/// paper moved.
class FakeTransport implements PrinterTransport {
  FakeTransport({this.acceptWrites = true, this.connectSucceeds = true});

  /// What write() answers. A printer that has slept answers true here while
  /// printing nothing, which is exactly why a true is not treated as lasting
  /// evidence of a healthy connection.
  bool acceptWrites;
  bool connectSucceeds;

  /// How many connects it takes before one succeeds. 0 is the normal case.
  int failConnectsBeforeSuccess = 0;

  /// From which write onwards to accept, regardless of [acceptWrites]. Models a
  /// printer that refuses while asleep and takes the job once woken.
  int? acceptFromWriteNumber;

  final List<String> log = [];
  int connects = 0;
  int writes = 0;

  @override
  Future<bool> permissionGranted() async => true;

  @override
  Future<bool> bluetoothOn() async => true;

  @override
  Future<List<({String name, String mac})>> paired() async =>
      [(name: 'Counter printer', mac: 'AA:BB')];

  @override
  Future<void> disconnect() async => log.add('disconnect');

  @override
  Future<bool> connect(String mac) async {
    connects++;
    log.add('connect');
    if (!connectSucceeds) return false;
    return connects > failConnectsBeforeSuccess;
  }

  @override
  Future<bool> write(List<int> bytes) async {
    writes++;
    log.add('write');
    final from = acceptFromWriteNumber;
    if (from != null && writes >= from) return true;
    return acceptWrites;
  }
}

void main() {
  setUp(() {
    TestWidgetsFlutterBinding.ensureInitialized();
    SharedPreferences.setMockInitialValues({});
  });

  Future<PrinterService> ready(FakeTransport bt) async {
    final service = PrinterService(transport: bt);
    await service.remember(const PairedPrinter(name: 'Counter printer', mac: 'AA:BB'));
    return service;
  }

  test('the first job connects before writing', () async {
    final bt = FakeTransport();
    final service = await ready(bt);

    await service.printTest();

    expect(bt.log, ['disconnect', 'connect', 'write']);
  });

  test('a second job straight after reuses the connection', () async {
    // Reconnecting per job would be simpler and leaks a BluetoothSocket each
    // time, because the plugin's disconnect closes only the stream.
    final bt = FakeTransport();
    final service = await ready(bt);

    await service.printTest();
    await service.printTest();

    expect(bt.connects, 1, reason: 'should not rebuild a fresh connection');
    expect(bt.writes, 2);
  });

  test('a refused write is retried on a rebuilt connection, not the dead one',
      () async {
    final bt = FakeTransport(acceptWrites: false);
    final service = await ready(bt);

    await expectLater(service.printTest(), throwsA(isA<PrinterException>()));

    // connect, write (refused), disconnect, connect, write (refused), throw.
    expect(bt.log, ['disconnect', 'connect', 'write', 'disconnect', 'connect', 'write']);
  });

  test('a write that succeeds on the rebuilt connection is not an error', () async {
    // The case the retry exists for: the printer had slept, the first write is
    // refused, and it takes the job once the socket is rebuilt. The stall
    // should see a printed ticket, not an error.
    final bt = FakeTransport(acceptWrites: false);
    final service = await ready(bt);
    bt.acceptFromWriteNumber = 2;

    await service.printTest();

    expect(bt.writes, 2);
    expect(bt.connects, 2, reason: 'the second write must be on a new connection');
  });

  test('a failed connect is retried once before giving up', () async {
    // The first connect after the printer sleeps routinely fails while its
    // radio wakes. Giving up there has a stall concluding it is broken.
    final bt = FakeTransport()..failConnectsBeforeSuccess = 1;
    final service = await ready(bt);

    await service.printTest();

    expect(bt.connects, 2);
    expect(bt.writes, 1);
  });

  test('a printer that never answers reports it rather than hanging', () async {
    final bt = FakeTransport(connectSucceeds: false);
    final service = await ready(bt);

    await expectLater(
      service.printTest(),
      throwsA(
        isA<PrinterException>().having(
          (e) => e.message,
          'message',
          contains('Could not reach'),
        ),
      ),
    );
  });

  test('reconnect: true rebuilds even when the connection looks fine', () async {
    // What the "nothing came out" button does. The connection looks healthy
    // precisely in the case that needs rebuilding.
    final bt = FakeTransport();
    final service = await ready(bt);

    await service.printTest();
    expect(bt.connects, 1);

    await service.printTest(reconnect: true);
    expect(bt.connects, 2);
  });

  test('choosing a different printer does not inherit the old connection',
      () async {
    final bt = FakeTransport();
    final service = await ready(bt);
    await service.printTest();

    await service.remember(const PairedPrinter(name: 'Other', mac: 'CC:DD'));
    await service.printTest();

    expect(bt.connects, 2, reason: 'the second printer needs its own connection');
  });

  test('no printer chosen says where to choose one', () async {
    final service = PrinterService(transport: FakeTransport());

    await expectLater(
      service.printTest(),
      throwsA(
        isA<PrinterException>().having(
          (e) => e.message,
          'message',
          contains('Stall settings'),
        ),
      ),
    );
  });
}
