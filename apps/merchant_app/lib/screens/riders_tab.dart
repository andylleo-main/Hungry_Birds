import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:hb_shared/hb_shared.dart';
import 'package:provider/provider.dart';
import 'package:url_launcher/url_launcher.dart';

/// The stall's own riders: who they are, and how they sign in.
///
/// A rider's password exists in exactly one response - the one that creates or
/// regenerates it - so this screen has to make that moment count. The dialog
/// says so plainly and offers a copy button, and Regenerate is one tap away for
/// when nobody wrote it down.
class RidersTab extends StatefulWidget {
  const RidersTab({super.key});

  @override
  State<RidersTab> createState() => _RidersTabState();
}

class _RidersTabState extends State<RidersTab> {
  List<Rider>? _riders;
  String? _error;
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() => _error = null);
    try {
      final riders = await context.read<ApiClient>().myRiders();
      if (mounted) setState(() => _riders = riders);
    } on ApiException catch (e) {
      if (mounted) setState(() => _error = e.message);
    } catch (_) {
      if (mounted) {
        setState(() => _error = "Couldn't reach the server. Check your connection.");
      }
    }
  }

  void _say(String message) {
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(content: Text(message)));
  }

  Future<void> _addRider() async {
    final nameController = TextEditingController();
    final phoneController = TextEditingController();
    final loginController = TextEditingController();

    try {
      final go = await showDialog<bool>(
        context: context,
        builder: (context) => AlertDialog(
          title: const Text('Add a rider'),
          content: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                TextField(
                  controller: nameController,
                  autofocus: true,
                  textCapitalization: TextCapitalization.words,
                  decoration: const InputDecoration(labelText: 'Name'),
                ),
                const SizedBox(height: 12),
                TextField(
                  controller: phoneController,
                  keyboardType: TextInputType.phone,
                  decoration: const InputDecoration(
                    labelText: 'Phone number',
                    helperText: 'Customers call this to reach the rider',
                  ),
                ),
                const SizedBox(height: 12),
                TextField(
                  controller: loginController,
                  autocorrect: false,
                  decoration: const InputDecoration(
                    labelText: 'Login id (optional)',
                    helperText: "Leave blank and we'll make one up",
                  ),
                ),
              ],
            ),
          ),
          actions: [
            TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Cancel')),
            TextButton(onPressed: () => Navigator.pop(context, true), child: const Text('Add')),
          ],
        ),
      );
      if (go != true || !mounted) return;

      final name = nameController.text.trim();
      if (name.isEmpty) {
        _say('Give the rider a name.');
        return;
      }

      setState(() => _busy = true);
      final created = await context.read<ApiClient>().createRider(
            displayName: name,
            phone: phoneController.text.trim(),
            loginId: loginController.text.trim(),
          );
      if (!mounted) return;
      await _showCredentials(created, isNew: true);
      await _load();
    } on ApiException catch (e) {
      if (mounted) _say(e.message);
    } catch (_) {
      if (mounted) _say("Couldn't add that rider. Check your connection.");
    } finally {
      // Disposed on every path, including cancel and error.
      nameController.dispose();
      phoneController.dispose();
      loginController.dispose();
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _regenerate(Rider rider) async {
    final go = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text('New password for ${rider.displayName}?'),
        content: const Text(
          'Their current password stops working straight away, and they will be '
          'signed out of the rider app until you give them the new one.',
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Cancel')),
          TextButton(onPressed: () => Navigator.pop(context, true), child: const Text('Regenerate')),
        ],
      ),
    );
    if (go != true || !mounted) return;

    setState(() => _busy = true);
    try {
      final fresh = await context.read<ApiClient>().regenerateRiderPassword(rider.id);
      if (!mounted) return;
      await _showCredentials(fresh, isNew: false);
    } on ApiException catch (e) {
      if (mounted) _say(e.message);
    } catch (_) {
      if (mounted) _say("Couldn't reach the server. Try again.");
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _setActive(Rider rider, bool active) async {
    setState(() => _busy = true);
    try {
      await context.read<ApiClient>().updateRider(rider.id, isActive: active);
      await _load();
      if (mounted) {
        _say(active
            ? '${rider.displayName} can take deliveries again.'
            : '${rider.displayName} is switched off and signed out.');
      }
    } on ApiException catch (e) {
      if (mounted) _say(e.message);
    } catch (_) {
      if (mounted) _say("Couldn't reach the server. Try again.");
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  /// The one and only sighting of a rider's password.
  Future<void> _showCredentials(RiderCredentials rider, {required bool isNew}) async {
    final block = 'Login id: ${rider.loginId}\nPassword: ${rider.password}';
    await showDialog<void>(
      context: context,
      barrierDismissible: false,
      builder: (context) => AlertDialog(
        title: Text(isNew ? '${rider.displayName} is ready' : 'New password'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text(
              'Give these to the rider for the Hungry Birds Rider app. '
              "This is the only time the password is shown - if it gets lost, "
              'come back here and regenerate it.',
              style: TextStyle(fontSize: 13, color: AppTheme.textSecondary),
            ),
            const SizedBox(height: 14),
            Container(
              width: double.infinity,
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: AppTheme.primaryRed.withValues(alpha: 0.07),
                borderRadius: BorderRadius.circular(8),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  _CredLine(label: 'Login id', value: rider.loginId),
                  const SizedBox(height: 8),
                  _CredLine(label: 'Password', value: rider.password),
                ],
              ),
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () async {
              await Clipboard.setData(ClipboardData(text: block));
              if (context.mounted) Navigator.pop(context);
            },
            child: const Text('Copy'),
          ),
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text("I've written it down"),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final riders = _riders;

    return Scaffold(
      appBar: AppBar(
        title: const Text('Riders'),
        actions: [
          IconButton(
            onPressed: _busy ? null : _addRider,
            icon: const Icon(Icons.person_add_alt),
            tooltip: 'Add a rider',
          ),
        ],
      ),
      body: switch ((riders, _error)) {
        (_, final String error) => _Retry(message: error, onRetry: _load),
        (null, _) => const Center(child: CircularProgressIndicator()),
        (final List<Rider> list, _) when list.isEmpty => const EmptyState(
            icon: Icons.pedal_bike_outlined,
            title: 'No riders yet',
            message:
                'Add the people who carry your deliveries. Each one gets a login '
                'for the Hungry Birds Rider app.',
          ),
        (final List<Rider> list, _) => RefreshIndicator(
            onRefresh: _load,
            child: ListView.separated(
              padding: const EdgeInsets.all(16),
              itemCount: list.length,
              separatorBuilder: (_, __) => const SizedBox(height: 10),
              itemBuilder: (context, i) => _RiderCard(
                rider: list[i],
                busy: _busy,
                onRegenerate: () => _regenerate(list[i]),
                onSetActive: (v) => _setActive(list[i], v),
              ),
            ),
          ),
      },
    );
  }
}

class _CredLine extends StatelessWidget {
  const _CredLine({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) => Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 72,
            child: Text(
              label,
              style: const TextStyle(fontSize: 12, color: AppTheme.textSecondary),
            ),
          ),
          Expanded(
            child: SelectableText(
              value,
              style: const TextStyle(
                fontSize: 16,
                fontWeight: FontWeight.w800,
                fontFamily: 'monospace',
              ),
            ),
          ),
        ],
      );
}

class _RiderCard extends StatelessWidget {
  const _RiderCard({
    required this.rider,
    required this.busy,
    required this.onRegenerate,
    required this.onSetActive,
  });

  final Rider rider;
  final bool busy;
  final VoidCallback onRegenerate;
  final ValueChanged<bool> onSetActive;

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(16, 12, 8, 8),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        rider.displayName,
                        style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w800),
                      ),
                      const SizedBox(height: 2),
                      Text(
                        '${rider.loginId} · ${rider.phone}',
                        style: const TextStyle(fontSize: 13, color: AppTheme.textSecondary),
                      ),
                    ],
                  ),
                ),
                if (!rider.isActive)
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                    decoration: BoxDecoration(
                      color: AppTheme.textSecondary.withValues(alpha: 0.12),
                      borderRadius: BorderRadius.circular(6),
                    ),
                    child: const Text(
                      'Switched off',
                      style: TextStyle(
                        fontSize: 12,
                        fontWeight: FontWeight.w700,
                        color: AppTheme.textSecondary,
                      ),
                    ),
                  ),
              ],
            ),
            const SizedBox(height: 6),
            Row(
              children: [
                TextButton.icon(
                  onPressed: busy ? null : onRegenerate,
                  icon: const Icon(Icons.key_outlined, size: 18),
                  label: const Text('New password'),
                ),
                IconButton(
                  onPressed: busy ? null : () => launchUrl(Uri.parse('tel:${rider.phone}')),
                  icon: const Icon(Icons.call_outlined, size: 20),
                  tooltip: 'Call ${rider.displayName}',
                ),
                const Spacer(),
                Switch(
                  value: rider.isActive,
                  activeThumbColor: AppTheme.success,
                  onChanged: busy ? null : onSetActive,
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _Retry extends StatelessWidget {
  const _Retry({required this.message, required this.onRetry});

  final String message;
  final Future<void> Function() onRetry;

  @override
  Widget build(BuildContext context) => Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Text(message, textAlign: TextAlign.center),
              const SizedBox(height: 16),
              OutlinedButton(onPressed: onRetry, child: const Text('Try again')),
            ],
          ),
        ),
      );
}
