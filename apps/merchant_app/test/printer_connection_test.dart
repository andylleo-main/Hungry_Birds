import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:merchant_app/services/printer.dart';
import 'package:merchant_app/services/receipt.dart';
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

  /// What the permission and pairing gates answer, so the self-check can be
  /// driven to stop at each one in turn.
  bool permitted = true;
  bool bluetooth = true;
  List<String> pairedMacs = const ['AA:BB'];

  /// How many connects it takes before one succeeds. 0 is the normal case.
  int failConnectsBeforeSuccess = 0;

  /// From which write onwards to accept, regardless of [acceptWrites]. Models a
  /// printer that refuses while asleep and takes the job once woken.
  int? acceptFromWriteNumber;

  final List<String> log = [];
  int connects = 0;
  int writes = 0;

  @override
  Future<bool> permissionGranted() async => permitted;

  @override
  Future<bool> bluetoothOn() async => bluetooth;

  @override
  Future<List<({String name, String mac})>> paired() async =>
      [for (final mac in pairedMacs) (name: 'Counter printer', mac: mac)];

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

  _diagnostics();
  _byteEncoding();

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

/// The self-check, and the plain-text control print.
///
/// Both exist because three attempts were made at "it says it printed and
/// nothing came out" without ever knowing which step failed. These pin that the
/// check reports the failing step rather than stopping at the first thing it
/// tried, and that the plain print really is free of escape sequences - a
/// control that quietly contained a formatting command would prove nothing.
void _diagnostics() {
  setUp(() {
    TestWidgetsFlutterBinding.ensureInitialized();
    SharedPreferences.setMockInitialValues({});
  });

  Future<PrinterService> ready(PrinterTransport bt) async {
    final service = PrinterService(transport: bt);
    await service.remember(const PairedPrinter(name: 'Counter printer', mac: 'AA:BB'));
    return service;
  }

  test('a clean run reports every step as passing', () async {
    final service = await ready(FakeTransport());

    final checks = await service.diagnose();

    expect(checks.map((c) => c.ok), everyElement(isTrue));
    expect(checks.map((c) => c.step), contains('Connects'));
    expect(checks.map((c) => c.step), contains('Accepts a line of text'));
  });

  test('no permission stops at the first gate and says so', () async {
    final bt = FakeTransport()..permitted = false;
    final service = await ready(bt);

    final checks = await service.diagnose();

    expect(checks.first.step, 'Bluetooth permission');
    expect(checks.first.ok, isFalse);
    // And it does not pretend to have tried the rest.
    expect(bt.connects, 0);
    expect(checks.last.ok, isFalse);
  });

  test('a printer that is no longer paired is named as the problem', () async {
    // The case that looks identical to everything else from the outside: the
    // MAC is remembered, Android has forgotten the device.
    final bt = FakeTransport()..pairedMacs = const [];
    final service = await ready(bt);

    final checks = await service.diagnose();
    final failed = checks.firstWhere((c) => !c.ok);

    expect(failed.step, 'Still paired with the phone');
    expect(failed.detail, contains('AA:BB'));
    expect(bt.connects, 0, reason: 'no point dialling a device that is not there');
  });

  test('a connect failure is reported as the connect step, not as a write one',
      () async {
    final bt = FakeTransport(connectSucceeds: false);
    final service = await ready(bt);

    final checks = await service.diagnose();
    final failed = checks.firstWhere((c) => !c.ok);

    expect(failed.step, 'Connects');
    expect(bt.writes, 0);
  });

  test('a refused write is reported, and paper is not claimed', () async {
    final bt = FakeTransport(acceptWrites: false);
    final service = await ready(bt);

    final checks = await service.diagnose();

    expect(checks.firstWhere((c) => c.step == 'Connects').ok, isTrue);
    expect(checks.firstWhere((c) => c.step == 'Accepts a line of text').ok, isFalse);
    expect(checks.firstWhere((c) => c.step == 'Paper came out').ok, isFalse);
  });

  test('the check never throws, whatever the transport does', () async {
    final service = await ready(ThrowingTransport());

    final checks = await service.diagnose();

    expect(checks, isNotEmpty);
    expect(checks.any((c) => !c.ok), isTrue);
  });

  test('the plain test contains no escape sequences at all', () async {
    // The whole value of the control is that it is free of them. ESC is 0x1B
    // and GS is 0x1D; if either appears, this proves nothing about whether a
    // formatting command is what the printer chokes on.
    final bytes = const Receipt().plainTest();

    expect(bytes, isNot(contains(0x1B)));
    expect(bytes, isNot(contains(0x1D)));
    // Printable ASCII and line feeds only.
    for (final b in bytes) {
      expect(b == 0x0A || (b >= 0x20 && b <= 0x7E), isTrue,
          reason: 'byte 0x${b.toRadixString(16)} is neither text nor a newline');
    }
    // And it has to end with enough blank lines to clear the tear bar.
    expect(bytes.sublist(bytes.length - 5), everyElement(0x0A));
  });

  test('the plain test always rebuilds the connection first', () async {
    // Somebody reaching for it has already had a print silently fail, so the
    // connection it would reuse is the suspect.
    final bt = FakeTransport();
    final service = await ready(bt);

    await service.printTest();
    expect(bt.connects, 1);

    await service.printPlainTest();
    expect(bt.connects, 2);
  });
}

/// A transport where everything blows up, for the never-throws guarantee.
class ThrowingTransport implements PrinterTransport {
  @override
  Future<bool> permissionGranted() async => throw StateError('no platform here');

  @override
  Future<bool> bluetoothOn() async => throw StateError('no platform here');

  @override
  Future<List<({String name, String mac})>> paired() async =>
      throw StateError('no platform here');

  @override
  Future<void> disconnect() async => throw StateError('no platform here');

  @override
  Future<bool> connect(String mac) async => throw StateError('no platform here');

  @override
  Future<bool> write(List<int> bytes) async => throw StateError('no platform here');
}

/// The byte encoding that stopped anything ever printing.
///
/// Receipt hands back a Uint8List, which is the natural type for a byte buffer
/// and is a perfectly good `List<int>` as far as Dart is concerned. Flutter's
/// StandardMessageCodec disagrees: a Uint8List has its own wire type and lands
/// on Android as a ByteArray, where the plugin's cast to `List<Int>` returns
/// null and the method answers false without touching the socket.
///
/// So every write returned false from the first build. The connection was
/// always fine - which is exactly why three rounds were spent on permissions, a
/// stale socket and the ESC/POS commands.
void _byteEncoding() {
  test('a Uint8List is converted to an ordinary list', () {
    final typed = Uint8List.fromList([0x1B, 0x40, 0x48, 0x69, 0x0A]);

    final sent = asPlatformList(typed);

    expect(sent, isNot(isA<Uint8List>()),
        reason: 'a Uint8List crosses the channel as a ByteArray and is refused');
    expect(sent, [0x1B, 0x40, 0x48, 0x69, 0x0A]);
  });

  test('an ordinary list survives unchanged', () {
    final plain = <int>[1, 2, 3];

    final sent = asPlatformList(plain);

    expect(sent, isNot(isA<Uint8List>()));
    expect(sent, [1, 2, 3]);
  });

  test('every payload the receipt builds converts cleanly', () {
    // All three are Uint8List at source, so all three would have been refused.
    for (final payload in [
      const Receipt().plainTest(),
      const Receipt().testPage(),
    ]) {
      final sent = asPlatformList(payload);
      expect(sent, isNot(isA<Uint8List>()));
      expect(sent, payload.toList());
      expect(sent, isNotEmpty);
    }
  });

  test('values stay within a byte, so nothing is mangled in transit', () {
    // The codec writes each element as a number. Anything outside 0..255 would
    // mean the receipt built something that is not a byte in the first place.
    for (final b in asPlatformList(const Receipt().testPage())) {
      expect(b, inInclusiveRange(0, 255));
    }
  });
}
