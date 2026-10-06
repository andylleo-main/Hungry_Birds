import 'package:flutter/material.dart';
import 'package:hb_shared/hb_shared.dart';
import 'package:provider/provider.dart';

import '../app_config.dart';
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
  List<PrinterCheck>? _checks;
  bool _checking = false;

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

  Future<void> _test({bool reconnect = false}) async {
    final service = context.read<PrinterService>();
    final stallName = context.read<MerchantState>().vendor?.stallName ?? 'Hungry Birds';

    setState(() => _printing = true);
    try {
      await service.printTest(stallName: stallName, reconnect: reconnect);
      if (mounted) _say('Sent. Check the paper.');
    } on PrinterException catch (e) {
      if (mounted) _say(e.message);
    } catch (_) {
      if (mounted) _say("Couldn't print the test page.");
    } finally {
      if (mounted) setState(() => _printing = false);
    }
  }

  Future<void> _plain() async {
    final service = context.read<PrinterService>();
    setState(() => _printing = true);
    try {
      await service.printPlainTest();
      if (mounted) _say('Sent plain text. Check the paper.');
    } on PrinterException catch (e) {
      if (mounted) _say(e.message);
    } catch (_) {
      if (mounted) _say("Couldn't send the plain test.");
    } finally {
      if (mounted) setState(() => _printing = false);
    }
  }

  Future<void> _diagnose() async {
    final service = context.read<PrinterService>();
    setState(() {
      _checking = true;
      _checks = null;
    });
    // diagnose() never throws, so there is deliberately nothing to catch here.
    final checks = await service.diagnose();
    if (!mounted) return;
    setState(() {
      _checks = checks;
      _checking = false;
    });
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
                    child: Column(
                      children: [
                        SizedBox(
                          width: double.infinity,
                          child: OutlinedButton.icon(
                            onPressed: _printing ? null : () => _test(),
                            icon: const Icon(Icons.receipt_long_outlined, size: 18),
                            label: Text(_printing ? 'Printing…' : 'Print a test page'),
                          ),
                        ),
                        const SizedBox(height: 8),
                        // The honest answer to "it says it printed and nothing
                        // came out". The connection can be dead while looking
                        // alive - a write to a sleeping printer is buffered and
                        // reported as sent - and this is the way to rule that
                        // out without power-cycling anything.
                        SizedBox(
                          width: double.infinity,
                          child: TextButton.icon(
                            onPressed: _printing ? null : () => _test(reconnect: true),
                            icon: const Icon(Icons.bluetooth_searching, size: 18),
                            label: const Text('Nothing came out? Reconnect and retry'),
                          ),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            ),

          const SizedBox(height: 16),
          Card(
            child: Padding(
              padding: const EdgeInsets.all(14),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text(
                    'Not printing?',
                    style: TextStyle(fontWeight: FontWeight.w800),
                  ),
                  const SizedBox(height: 2),
                  const Text(
                    // Said plainly because it is true, and because a stall owner
                    // reading a list of ticks is doing the work a developer
                    // cannot do from somewhere else.
                    'This walks the whole path and shows exactly where it stops. '
                    'Every step fails the same way from the outside, so this is '
                    'the only way to tell them apart.',
                    style: TextStyle(fontSize: 12, color: AppTheme.textSecondary),
                  ),
                  const SizedBox(height: 6),
                  // The build, right where somebody is about to report what
                  // this screen told them. Testing a fix against the previous
                  // APK and reporting it as still broken has happened, and this
                  // is the line that makes that impossible to do by accident.
                  Text(
                    'App ${AppConfig.version}',
                    style: const TextStyle(
                      fontSize: 11,
                      color: AppTheme.textSecondary,
                      fontFeatures: [FontFeature.tabularFigures()],
                    ),
                  ),
                  const SizedBox(height: 10),
                  SizedBox(
                    width: double.infinity,
                    child: OutlinedButton.icon(
                      onPressed: _checking ? null : _diagnose,
                      icon: const Icon(Icons.troubleshoot, size: 18),
                      label: Text(_checking ? 'Checking…' : 'Run the check'),
                    ),
                  ),
                  if (_checks != null) ...[
                    const SizedBox(height: 12),
                    for (final check in _checks!) _CheckRow(check: check),
                  ],
                  const SizedBox(height: 10),
                  const Divider(height: 1),
                  const SizedBox(height: 10),
                  const Text(
                    'Plain text, with no formatting commands at all. If this '
                    'prints but the test page does not, the connection is fine '
                    'and the formatting is the problem — tell me that.',
                    style: TextStyle(fontSize: 12, color: AppTheme.textSecondary),
                  ),
                  const SizedBox(height: 8),
                  SizedBox(
                    width: double.infinity,
                    child: OutlinedButton.icon(
                      onPressed: _printing ? null : _plain,
                      icon: const Icon(Icons.text_fields, size: 18),
                      label: const Text('Print plain text'),
                    ),
                  ),
                ],
              ),
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


/// One line of the self-check: what was tried, and what happened.
class _CheckRow extends StatelessWidget {
  const _CheckRow({required this.check});

  final PrinterCheck check;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(
            check.ok ? Icons.check_circle : Icons.cancel,
            size: 16,
            color: check.ok ? AppTheme.success : AppTheme.primaryRed,
          ),
          const SizedBox(width: 8),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  check.step,
                  style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w700),
                ),
                if (check.detail != null)
                  Text(
                    check.detail!,
                    style: const TextStyle(fontSize: 12, color: AppTheme.textSecondary),
                  ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
