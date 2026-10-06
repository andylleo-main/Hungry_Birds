import 'package:flutter/foundation.dart';
import 'package:print_bluetooth_thermal/print_bluetooth_thermal.dart';

/// The three things we need a Bluetooth printer to do.
///
/// A seam over the plugin, for one reason: none of this can be run against a
/// printer from where it is written, and the connection logic in PrinterService
/// has now been wrong twice. Behind an interface it is at least testable, which
/// is the difference between "believed correct" and "pinned".
///
/// Deliberately *not* exposing the plugin's `connectionStatus`. It probes by
/// writing a space to the socket, which means every check prints a stray
/// character, and a buffered write to a printer that has slept does not throw -
/// so it answers "connected" for a socket that is going nowhere. Trusting it is
/// how a ticket disappears with no error at all. PrinterService decides when a
/// connection is stale instead, from time and from failures.
abstract class PrinterTransport {
  Future<bool> permissionGranted();
  Future<bool> bluetoothOn();
  Future<List<({String name, String mac})>> paired();

  /// Drop whatever connection exists. Must tolerate there being none.
  Future<void> disconnect();

  Future<bool> connect(String mac);

  /// True if the printer took the bytes. A false is trustworthy; a true is not
  /// proof the paper moved, which is why PrinterService never treats one as
  /// evidence that the connection is healthy beyond a short window.
  Future<bool> write(List<int> bytes);
}

/// The real one.
class BluetoothPrinterTransport implements PrinterTransport {
  const BluetoothPrinterTransport();

  @override
  Future<bool> permissionGranted() =>
      PrintBluetoothThermal.isPermissionBluetoothGranted;

  @override
  Future<bool> bluetoothOn() => PrintBluetoothThermal.bluetoothEnabled;

  @override
  Future<List<({String name, String mac})>> paired() async {
    final devices = await PrintBluetoothThermal.pairedBluetooths;
    return [for (final d in devices) (name: d.name, mac: d.macAdress)];
  }

  @override
  Future<void> disconnect() => PrintBluetoothThermal.disconnect;

  @override
  Future<bool> connect(String mac) =>
      PrintBluetoothThermal.connect(macPrinterAddress: mac);

  @override
  Future<bool> write(List<int> bytes) =>
      PrintBluetoothThermal.writeBytes(asPlatformList(bytes));
}

/// Bytes in a shape the platform channel will carry as a list of numbers.
///
/// **This is the bug that stopped anything ever printing**, and it is worth
/// spelling out because nothing about it is visible from Dart.
///
/// `writeBytes` takes a `List<int>`, and a `Uint8List` *is* a `List<int>`, so
/// handing it one compiles and reads correctly. But Flutter's
/// StandardMessageCodec does not treat the two alike: a `Uint8List` has its own
/// wire type and arrives on the Android side as a `ByteArray`, while an ordinary
/// `List<int>` arrives as a `List`. The plugin does:
///
/// ```kotlin
/// val lista = call.arguments as? List<Int>
/// if (lista == null || stream == null) { result.success(false); return }
/// ```
///
/// so a `ByteArray` fails that cast, and the method answers `false` without
/// touching the socket. Every write returned false, from the first build - which
/// is why the connection was fine, the diagnostics got as far as "Connects", and
/// no paper ever moved. Three earlier theories (permissions, a stale socket, the
/// ESC/POS commands) were all wrong because the bytes never left the phone.
///
/// Receipt returns a `Uint8List`, which is the natural thing for a byte buffer
/// to be, so the conversion lives here rather than there: this is the one place
/// that knows a platform channel is involved, and doing it unconditionally means
/// no future caller can reintroduce it by passing a typed list.
@visibleForTesting
List<int> asPlatformList(List<int> bytes) => List<int>.from(bytes);

