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
