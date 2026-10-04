
import 'package:flutter/foundation.dart';
import 'package:hb_shared/hb_shared.dart';
import 'package:print_bluetooth_thermal/print_bluetooth_thermal.dart';
import 'package:shared_preferences/shared_preferences.dart';

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
  static const _macKey = 'hb_printer_mac';
  static const _nameKey = 'hb_printer_name';
  static const _columnsKey = 'hb_printer_columns';

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
    if (!await PrintBluetoothThermal.isPermissionBluetoothGranted) {
      throw const PrinterException(
        'Android needs permission to use Bluetooth. Allow it when asked, or turn '
        'it on for Hungry Birds Partner in Settings.',
      );
    }
    if (!await PrintBluetoothThermal.bluetoothEnabled) {
      throw const PrinterException('Bluetooth is off. Turn it on and try again.');
    }
    final devices = await PrintBluetoothThermal.pairedBluetooths;
    return [
      for (final d in devices) PairedPrinter(name: d.name, mac: d.macAdress),
    ];
  }

  /// Sends bytes, connecting first if nothing is connected.
  ///
  /// Reconnects rather than assuming: the printer sleeps, the phone wanders out
  /// of range and back, and a connection that was good when the stall opened is
  /// not evidence of anything by the lunch rush.
  Future<void> _send(Uint8List bytes) async {
    final mac = _mac;
    if (mac == null) {
      throw const PrinterException('No printer chosen yet. Pick one in Stall settings.');
    }

    if (!await PrintBluetoothThermal.connectionStatus) {
      final connected = await PrintBluetoothThermal.connect(macPrinterAddress: mac);
      if (!connected) {
        throw PrinterException(
          'Could not reach ${_name ?? 'the printer'}. Check it is switched on and '
          'in range.',
        );
      }
    }

    final ok = await PrintBluetoothThermal.writeBytes(bytes);
    if (!ok) {
      throw const PrinterException(
        'The printer took the job but did not confirm it. Check the paper.',
      );
    }
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

  Future<void> printTest({String stallName = 'Hungry Birds'}) async {
    try {
      await _send(Receipt(columns: _columns).testPage(stallName: stallName));
    } on PrinterException {
      rethrow;
    } catch (e) {
      debugPrint('printer: $e');
      throw const PrinterException('Could not print the test page. Try again.');
    }
  }
}
