import 'package:flutter/material.dart';
import 'package:hb_shared/hb_shared.dart';
import 'package:provider/provider.dart';

import '../services/printer.dart';
import '../state/merchant_state.dart';

/// Choosing the kitchen ticket printer.
///
/// Pairing is left to Android's own Bluetooth settings - a thermal printer wants
/// a PIN the first time, and sending somebody to the screen that already handles
/// that well beats reimplementing it badly. This screen only picks which of the
/// already-paired devices is the one that prints tickets.
class PrinterScreen extends StatefulWidget {
  const PrinterScreen({super.key});

  @override
  State<PrinterScreen> createState() => _PrinterScreenState();
}

class _PrinterScreenState extends State<PrinterScreen> {
  List<PairedPrinter> _devices = const [];
  String? _error;
  bool _loading = true;
  bool _printing = false;

  @override
  void initState() {
    super.initState();
    _find();
  }

  Future<void> _find() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final devices = await context.read<PrinterService>().paired();
      if (!mounted) return;
      setState(() {
        _devices = devices;
        _loading = false;
      });
    } on PrinterException catch (e) {
      if (!mounted) return;
      setState(() {
        _error = e.message;
        _loading = false;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _error = "Couldn't look for printers. Check Bluetooth is on.";
        _loading = false;
      });
    }
  }

  void _say(String message) {
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(message)));
  }

  Future<void> _choose(PairedPrinter printer) async {
    await context.read<PrinterService>().remember(printer);
    if (!mounted) return;
    _say('${printer.name} will print your tickets.');
  }

  Future<void> _forget() async {
    await context.read<PrinterService>().forget();
  }

  Future<void> _setColumns(int columns) async {
    await context.read<PrinterService>().setColumns(columns);
  }

  Future<void> _test() async {
    final service = context.read<PrinterService>();
    final stallName = context.read<MerchantState>().vendor?.stallName ?? 'Hungry Birds';

    setState(() => _printing = true);
    try {
      await service.printTest(stallName: stallName);
      if (mounted) _say('Sent. Check the paper.');
    } on PrinterException catch (e) {
      if (mounted) _say(e.message);
    } catch (_) {
      if (mounted) _say("Couldn't print the test page.");
    } finally {
      if (mounted) setState(() => _printing = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final service = context.watch<PrinterService>();

    return Scaffold(
      appBar: AppBar(
        title: const Text('Ticket printer'),
        actions: [
          IconButton(
            onPressed: _loading ? null : _find,
            icon: const Icon(Icons.refresh),
            tooltip: 'Look again',
          ),
        ],
      ),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          const Card(
            child: Padding(
              padding: EdgeInsets.all(16),
              child: Row(
                children: [
                  Icon(Icons.bluetooth, color: AppTheme.textSecondary),
                  SizedBox(width: 12),
                  Expanded(
                    child: Text(
                      'Pair the printer in your phone’s Bluetooth settings first, '
                      'then pick it here.',
                      style: TextStyle(fontSize: 13, color: AppTheme.textSecondary),
                    ),
                  ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 16),

          if (service.hasPrinter)
            Card(
              child: Column(
                children: [
                  ListTile(
                    leading: const Icon(Icons.print, color: AppTheme.success),
                    title: Text(
                      service.savedName ?? 'Printer',
                      style: const TextStyle(fontWeight: FontWeight.w700),
                    ),
                    subtitle: Text(
                      '${service.savedMac}\n${service.columns} columns',
                      style: const TextStyle(fontSize: 12),
                    ),
                    isThreeLine: true,
                    trailing: IconButton(
                      onPressed: _forget,
                      icon: const Icon(Icons.link_off),
                      tooltip: 'Forget',
                    ),
                  ),
                  const Divider(height: 1),
                  Padding(
                    padding: const EdgeInsets.all(12),
                    child: SizedBox(
                      width: double.infinity,
                      child: OutlinedButton.icon(
                        onPressed: _printing ? null : _test,
                        icon: const Icon(Icons.receipt_long_outlined, size: 18),
                        label: Text(_printing ? 'Printing…' : 'Print a test page'),
                      ),
                    ),
                  ),
                ],
              ),
            ),

          const SizedBox(height: 16),
          const Text('Paper width', style: TextStyle(fontWeight: FontWeight.w800)),
          const SizedBox(height: 4),
          const Text(
            // The test page prints a numbered ruler for exactly this: if it
            // wraps onto a second line, the setting is too wide for the paper.
            'Most phone printers take 58mm rolls. If the test page wraps, you are '
            'on the wrong setting.',
            style: TextStyle(fontSize: 13, color: AppTheme.textSecondary),
          ),
          const SizedBox(height: 8),
          SegmentedButton<int>(
            segments: const [
              ButtonSegment(value: 32, label: Text('58mm')),
              ButtonSegment(value: 48, label: Text('80mm')),
            ],
            selected: {service.columns},
            onSelectionChanged: (selection) => _setColumns(selection.first),
          ),

          const SizedBox(height: 24),
          const Text('Paired devices', style: TextStyle(fontWeight: FontWeight.w800)),
          const SizedBox(height: 8),

          if (_loading)
            const Padding(
              padding: EdgeInsets.symmetric(vertical: 24),
              child: Center(child: CircularProgressIndicator()),
            )
          else if (_error != null)
            Card(
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(_error!, style: const TextStyle(fontSize: 14)),
                    const SizedBox(height: 10),
                    OutlinedButton(onPressed: _find, child: const Text('Try again')),
                  ],
                ),
              ),
            )
          else if (_devices.isEmpty)
            const Card(
              child: Padding(
                padding: EdgeInsets.all(16),
                child: Text(
                  'No paired devices. Pair your printer in Bluetooth settings, then '
                  'tap refresh.',
                  style: TextStyle(fontSize: 14),
                ),
              ),
            )
          else
            Card(
              child: Column(
                children: [
                  for (final device in _devices)
                    ListTile(
                      leading: const Icon(Icons.print_outlined),
                      title: Text(device.name),
                      subtitle: Text(device.mac, style: const TextStyle(fontSize: 12)),
                      trailing: device.mac == service.savedMac
                          ? const Icon(Icons.check_circle, color: AppTheme.success)
                          : null,
                      onTap: () => _choose(device),
                    ),
                ],
              ),
            ),
        ],
      ),
    );
  }
}
