import 'package:flutter/material.dart';
import 'package:hb_shared/hb_shared.dart';
import 'package:provider/provider.dart';

/// Where a stall says how it hands food over, and which buildings it carries to.
///
/// Every switch saves immediately and optimistically, the same way the stall's
/// open/closed switch does: a merchant flipping a location off is usually doing
/// it because a rider just left, and a screen that needed a separate Save tap
/// would get half-used. A failed save puts the switch back and says why, because
/// the dangerous outcome is a switch that looks off while orders keep arriving.
class FulfilmentScreen extends StatefulWidget {
  const FulfilmentScreen({super.key});

  @override
  State<FulfilmentScreen> createState() => _FulfilmentScreenState();
}

class _FulfilmentScreenState extends State<FulfilmentScreen> {
  FulfilmentSettings? _settings;
  String? _loadError;
  bool _saving = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() => _loadError = null);
    try {
      final settings = await context.read<ApiClient>().myFulfilment();
      if (mounted) setState(() => _settings = settings);
    } on ApiException catch (e) {
      if (mounted) setState(() => _loadError = e.message);
    } catch (_) {
      if (mounted) {
        setState(() => _loadError = "Couldn't reach the server. Check your connection.");
      }
    }
  }

  void _say(String message) {
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(content: Text(message)));
  }

  /// Applies a change locally, saves it, and rolls back if the server refuses.
  Future<void> _save(FulfilmentSettings next) async {
    final previous = _settings;
    setState(() {
      _settings = next;
      _saving = true;
    });
    try {
      final saved = await context.read<ApiClient>().updateFulfilment(
            dineInEnabled: next.dineInEnabled,
            deliveryEnabled: next.deliveryEnabled,
            enabledLocations: next.enabledCodes,
            // Always sent, so this screen is the whole truth. The server treats
            // an omitted figure as "leave it alone", which exists for merchant
            // builds that predate the field - not for this one.
            minDeliveryOrder: next.minDeliveryOrder,
          );
      if (mounted) setState(() => _settings = saved);
    } on ApiException catch (e) {
      if (mounted) {
        setState(() => _settings = previous);
        _say(e.message);
      }
    } catch (_) {
      if (mounted) {
        setState(() => _settings = previous);
        _say("Couldn't save that. Check your connection and try again.");
      }
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  /// Ask for a new minimum, then save it through the same path as the switches.
  Future<void> _editMinimum(FulfilmentSettings s) async {
    final chosen = await showDialog<double>(
      context: context,
      builder: (_) => _MinimumDialog(current: s.minDeliveryOrder),
    );
    if (chosen == null || !mounted) return;
    if (chosen == s.minDeliveryOrder) return;
    await _save(s.copyWith(minDeliveryOrder: chosen));
  }

  @override
  Widget build(BuildContext context) {
    final settings = _settings;

    return Scaffold(
      appBar: AppBar(title: const Text('How you serve')),
      body: switch ((settings, _loadError)) {
        (_, final String error) => Center(
            child: Padding(
              padding: const EdgeInsets.all(24),
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  Text(error, textAlign: TextAlign.center),
                  const SizedBox(height: 16),
                  OutlinedButton(onPressed: _load, child: const Text('Try again')),
                ],
              ),
            ),
          ),
        (null, _) => const Center(child: CircularProgressIndicator()),
        (final FulfilmentSettings s, _) => _buildBody(s),
      },
    );
  }

  Widget _buildBody(FulfilmentSettings s) {
    final locations = s.locations;

    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Card(
          child: Column(
            children: [
              SwitchListTile(
                value: s.dineInEnabled,
                activeThumbColor: AppTheme.success,
                secondary: const Icon(Icons.restaurant_outlined),
                title: const Text('Dine in', style: TextStyle(fontWeight: FontWeight.w700)),
                subtitle: const Text(
                  'Students eat at, or collect from, your counter',
                  style: TextStyle(fontSize: 13),
                ),
                onChanged: _saving ? null : (v) => _save(s.copyWith(dineInEnabled: v)),
              ),
              const Divider(height: 1),
              SwitchListTile(
                value: s.deliveryEnabled,
                activeThumbColor: AppTheme.success,
                secondary: const Icon(Icons.delivery_dining_outlined),
                title: const Text('Delivery', style: TextStyle(fontWeight: FontWeight.w700)),
                subtitle: Text(
                  s.deliveryEnabled
                      ? '${s.enabledCodes.length} of ${locations.length} places switched on'
                      : 'You are not delivering right now',
                  style: const TextStyle(fontSize: 13),
                ),
                onChanged: _saving ? null : (v) => _save(s.copyWith(deliveryEnabled: v)),
              ),
              const Divider(height: 1),
              // In this card rather than its own, because it is a property of
              // delivery: a stall reading "Delivery: on" needs the floor that
              // comes with it in the same glance.
              ListTile(
                enabled: !_saving && s.deliveryEnabled,
                leading: const Icon(Icons.currency_rupee),
                title: const Text(
                  'Smallest delivery order',
                  style: TextStyle(fontWeight: FontWeight.w700),
                ),
                subtitle: Text(
                  s.hasMinimum
                      ? 'Students need ₹${s.minDeliveryOrder.toStringAsFixed(0)} in the cart to have it delivered'
                      : 'No minimum - you will take a delivery of any size',
                  style: const TextStyle(fontSize: 13),
                ),
                trailing: Text(
                  s.hasMinimum ? '₹${s.minDeliveryOrder.toStringAsFixed(0)}' : 'None',
                  style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 16),
                ),
                onTap: (_saving || !s.deliveryEnabled) ? null : () => _editMinimum(s),
              ),
            ],
          ),
        ),
        const SizedBox(height: 8),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 8),
          child: Text(
            s.deliveryEnabled
                ? 'Switch off anywhere you cannot reach today. Students only see the places you keep on.'
                : 'Switch delivery on to choose where you carry orders.',
            style: const TextStyle(color: AppTheme.textSecondary, fontSize: 13),
          ),
        ),
        Card(
          child: Column(
            children: [
              for (var i = 0; i < locations.length; i++) ...[
                if (i > 0) const Divider(height: 1),
                SwitchListTile(
                  value: locations[i].enabled,
                  activeThumbColor: AppTheme.success,
                  dense: true,
                  title: Text(locations[i].label),
                  // Greyed out rather than hidden when delivery is off, so the
                  // choices a stall has made are still visible - switching
                  // delivery back on should not look like it lost them.
                  onChanged: (_saving || !s.deliveryEnabled)
                      ? null
                      : (v) => _save(s.copyWith(
                            locations: [
                              for (final l in locations)
                                l.code == locations[i].code ? l.copyWith(enabled: v) : l,
                            ],
                          )),
                ),
              ],
            ],
          ),
        ),
        const SizedBox(height: 24),
      ],
    );
  }
}

/// Asks for a stall's smallest delivery order.
///
/// Its own widget rather than an inline AlertDialog because it has to hold a
/// controller and an error message, and the screen behind it is already holding
/// the optimistic save. Returns the chosen figure, or null if dismissed.
class _MinimumDialog extends StatefulWidget {
  final double current;

  const _MinimumDialog({required this.current});

  @override
  State<_MinimumDialog> createState() => _MinimumDialogState();
}

class _MinimumDialogState extends State<_MinimumDialog> {
  late final TextEditingController _controller;
  String? _error;

  @override
  void initState() {
    super.initState();
    _controller = TextEditingController(text: widget.current.toStringAsFixed(0));
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  void _submit() {
    final text = _controller.text.trim();
    final parsed = double.tryParse(text);
    // The same bounds the server enforces, checked here too so the merchant is
    // told what is wrong without a round trip. The server stays the authority.
    if (parsed == null) {
      setState(() => _error = 'Enter an amount in rupees');
      return;
    }
    if (parsed < 0) {
      setState(() => _error = 'It cannot be less than zero');
      return;
    }
    if (parsed > 10000) {
      setState(() => _error = 'That is too high. Close delivery instead.');
      return;
    }
    Navigator.pop(context, parsed);
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Smallest delivery order'),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            'Students will not be able to order a delivery below this. '
            'Set 0 to take deliveries of any size.',
            style: TextStyle(fontSize: 13),
          ),
          const SizedBox(height: 14),
          TextField(
            controller: _controller,
            autofocus: true,
            keyboardType: const TextInputType.numberWithOptions(decimal: true),
            decoration: InputDecoration(
              labelText: 'Amount',
              prefixText: '₹ ',
              errorText: _error,
            ),
            onSubmitted: (_) => _submit(),
          ),
          const SizedBox(height: 8),
          const Text(
            'Dine-in is never affected - there is nobody to send.',
            style: TextStyle(color: AppTheme.textSecondary, fontSize: 12),
          ),
        ],
      ),
      actions: [
        TextButton(onPressed: () => Navigator.pop(context), child: const Text('Cancel')),
        TextButton(onPressed: _submit, child: const Text('Save')),
      ],
    );
  }
}
