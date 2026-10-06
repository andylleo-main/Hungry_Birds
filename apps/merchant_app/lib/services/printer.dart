
import 'package:flutter/foundation.dart';
import 'package:hb_shared/hb_shared.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'printer_transport.dart';
import 'receipt.dart';

/// A paired printer, as the settings screen lists it.
class PairedPrinter {
  const PairedPrinter({required this.name, required this.mac});

  final String name;
  final String mac;
}

/// What went wrong, in words a stall owner can act on.
class PrinterException implements Exception {
  const PrinterException(this.message);
  final String message;

  @override
  String toString() => message;
}

/// Talks to the kitchen ticket printer over Bluetooth.
///
/// Remembers one printer, because a stall has one. The MAC and the paper width
/// live in SharedPreferences rather than on the server: which printer sits on
/// which counter is a property of the phone, not of the account, and a merchant
/// signing in on a borrowed handset should not inherit somebody else's hardware.
///
/// **Not verified against a real printer.** There is no Android SDK in the
/// environment this was written in and dl.google.com is blocked there, so none
/// of this has run. The ESC/POS in receipt.dart is unit-tested and the flow
/// below is ordinary plugin calls, but first contact with the hardware is the
/// real test - start with the test page in the Stall tab, which prints a column
/// ruler for exactly that reason.
class PrinterService extends ChangeNotifier {
  PrinterService({PrinterTransport? transport})
      : _bt = transport ?? const BluetoothPrinterTransport();

  final PrinterTransport _bt;

  static const _macKey = 'hb_printer_mac';
  static const _nameKey = 'hb_printer_name';
  static const _columnsKey = 'hb_printer_columns';

  /// How long a connection is trusted before being rebuilt.
  ///
  /// These printers power their radio down after a few minutes idle, and the
  /// socket goes stale without either end saying so - writes vanish into a
  /// buffer and are reported as successful. Four minutes is under the usual
  /// sleep timeout, so a ticket during service reuses a live connection while
  /// the first one after a quiet spell rebuilds it.
  ///
  /// It is a heuristic because the plugin gives us nothing better: its
  /// connectionStatus lies (see PrinterTransport). The cost of being wrong in
  /// the cautious direction is a second of reconnecting; wrong the other way is
  /// a ticket that never prints and never complains.
  static const _trustConnectionFor = Duration(minutes: 4);

  /// Reconnecting every single job would be simpler, and is wrong: the plugin's
  /// disconnect closes the OutputStream but never the BluetoothSocket, so each
  /// connect leaks one. Bounding reconnects to idle periods and failures keeps
  /// that to a handful a day instead of one per ticket.
  String? _connectedTo;
  DateTime? _lastAccepted;

  String? _mac;
  String? _name;
  int _columns = 32;

  String? get savedName => _name;
  String? get savedMac => _mac;
  int get columns => _columns;
  bool get hasPrinter => _mac != null;

  Future<void> load() async {
    final prefs = await SharedPreferences.getInstance();
    _mac = prefs.getString(_macKey);
    _name = prefs.getString(_nameKey);
    _columns = prefs.getInt(_columnsKey) ?? 32;
    notifyListeners();
  }

  Future<void> remember(PairedPrinter printer, {int? columns}) async {
    if (printer.mac != _mac) _forgetConnection();
    _mac = printer.mac;
    _name = printer.name;
    if (columns != null) _columns = columns;
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_macKey, printer.mac);
    await prefs.setString(_nameKey, printer.name);
    await prefs.setInt(_columnsKey, _columns);
    notifyListeners();
  }

  Future<void> setColumns(int columns) async {
    _columns = columns;
    final prefs = await SharedPreferences.getInstance();
    await prefs.setInt(_columnsKey, columns);
    notifyListeners();
  }

  Future<void> forget() async {
    _forgetConnection();
    _mac = null;
    _name = null;
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_macKey);
    await prefs.remove(_nameKey);
    notifyListeners();
  }

  /// Printers already paired in Android's Bluetooth settings.
  ///
  /// Pairing itself is deliberately left to Android. A thermal printer needs a
  /// PIN the first time, and reimplementing that flow badly is worse than
  /// sending somebody to the screen that already does it well.
  Future<List<PairedPrinter>> paired() async {
    if (!await _bt.permissionGranted()) {
      throw const PrinterException(
        'Android needs permission to use Bluetooth. Allow it when asked, or turn '
        'it on for Hungry Birds Partner in Settings.',
      );
    }
    if (!await _bt.bluetoothOn()) {
      throw const PrinterException('Bluetooth is off. Turn it on and try again.');
    }
    final devices = await _bt.paired();
    return [
      for (final d in devices) PairedPrinter(name: d.name, mac: d.mac),
    ];
  }

  void _forgetConnection() {
    _connectedTo = null;
    _lastAccepted = null;
  }

  /// Whether the connection we think we have is worth using.
  bool get _connectionIsTrustworthy {
    if (_connectedTo == null || _connectedTo != _mac) return false;
    final last = _lastAccepted;
    if (last == null) return false;
    return DateTime.now().difference(last) <= _trustConnectionFor;
  }

  Future<void> _connect(String mac) async {
    // Close first, always. Connecting over a half-open socket is how the
    // plugin ends up holding a stream that accepts bytes and delivers none.
    await _bt.disconnect();
    _forgetConnection();

    var connected = await _bt.connect(mac);
    if (!connected) {
      // One retry, because the first connect after the printer has slept
      // routinely fails while its radio wakes. Failing on that would have a
      // stall concluding the printer is broken when a second tap works.
      await Future<void>.delayed(const Duration(milliseconds: 700));
      connected = await _bt.connect(mac);
    }
    if (!connected) {
      throw PrinterException(
        'Could not reach ${_name ?? 'the printer'}. Check it is switched on and '
        'in range.',
      );
    }
    _connectedTo = mac;
  }

  /// Sends bytes, rebuilding the connection when it cannot be trusted.
  ///
  /// The shape worth keeping: a write that returns false is retried **on a
  /// fresh connection**, not on the one that just failed. The previous version
  /// asked the plugin whether it was connected and believed the answer - and
  /// that answer is a buffered write to a sleeping printer, which succeeds. So
  /// a ticket went into a dead socket, the plugin reported success, and the
  /// stall was told nothing while no paper moved. That is the bug this is for.
  Future<void> _send(Uint8List bytes, {bool reconnect = false}) async {
    final mac = _mac;
    if (mac == null) {
      throw const PrinterException('No printer chosen yet. Pick one in Stall settings.');
    }

    if (reconnect || !_connectionIsTrustworthy) {
      await _connect(mac);
    }

    if (await _bt.write(bytes)) {
      _lastAccepted = DateTime.now();
      return;
    }

    // Refused. The socket is gone whatever it claimed, so rebuild and try the
    // job once more rather than reporting a failure the stall cannot act on.
    await _connect(mac);
    if (await _bt.write(bytes)) {
      _lastAccepted = DateTime.now();
      return;
    }

    throw const PrinterException(
      'The printer would not take the job. Check the paper, then try again.',
    );
  }

  Future<void> printOrder(Order order, {String stallName = 'Hungry Birds'}) async {
    try {
      await _send(Receipt(columns: _columns).build(order, stallName: stallName));
    } on PrinterException {
      rethrow;
    } catch (e) {
      debugPrint('printer: $e');
      throw const PrinterException('Could not print that. Try again.');
    }
  }

  /// [reconnect] rebuilds the connection before printing. The test page is
  /// where somebody goes when nothing came out, so it is the one place that
  /// needs to be able to say "ignore whatever you think you have".
  Future<void> printTest({String stallName = 'Hungry Birds', bool reconnect = false}) async {
    try {
      await _send(
        Receipt(columns: _columns).testPage(stallName: stallName),
        reconnect: reconnect,
      );
    } on PrinterException {
      rethrow;
    } catch (e) {
      debugPrint('printer: $e');
      throw const PrinterException('Could not print the test page. Try again.');
    }
  }
}
