import 'package:flutter/material.dart';
import 'package:hb_shared/hb_shared.dart';
import 'package:provider/provider.dart';
import 'package:url_launcher/url_launcher.dart';

import '../state/rider_state.dart';

/// The rider's working screen: what to carry, where, and who to ring.
class DeliveriesScreen extends StatelessWidget {
  const DeliveriesScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final state = context.watch<RiderState>();
    final active = state.active;

    return Scaffold(
      appBar: AppBar(
        title: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text('Your deliveries'),
            if (state.stallName.isNotEmpty)
              Text(
                state.stallName,
                style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w400),
              ),
          ],
        ),
        actions: [
          IconButton(
            onPressed: () => _confirmLogout(context),
            icon: const Icon(Icons.logout),
            tooltip: 'Sign out',
          ),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: () => context.read<RiderState>().refresh(),
        child: switch ((state.error, active.isEmpty)) {
          (final String error, _) => ListView(
              padding: const EdgeInsets.all(24),
              children: [
                const SizedBox(height: 60),
                Text(error, textAlign: TextAlign.center),
                const SizedBox(height: 16),
                Center(
                  child: OutlinedButton(
                    onPressed: () => context.read<RiderState>().refresh(),
                    child: const Text('Try again'),
                  ),
                ),
              ],
            ),
          (null, true) => ListView(
              padding: const EdgeInsets.all(24),
              children: const [
                SizedBox(height: 60),
                EmptyState(
                  icon: Icons.inbox_outlined,
                  title: 'Nothing to carry',
                  message:
                      'When your stall gives you a delivery it shows up here. '
                      'Pull down to check again.',
                ),
              ],
            ),
          (null, false) => ListView.separated(
              padding: const EdgeInsets.all(16),
              itemCount: active.length,
              separatorBuilder: (_, __) => const SizedBox(height: 12),
              itemBuilder: (context, i) => _DeliveryCard(order: active[i]),
            ),
        },
      ),
    );
  }

  Future<void> _confirmLogout(BuildContext context) async {
    final go = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Sign out?'),
        content: const Text(
          "You'll need your login id and password again to come back.",
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Cancel')),
          TextButton(onPressed: () => Navigator.pop(context, true), child: const Text('Sign out')),
        ],
      ),
    );
    if (go == true && context.mounted) await context.read<RiderState>().logout();
  }
}

class _DeliveryCard extends StatefulWidget {
  const _DeliveryCard({required this.order});

  final Order order;

  @override
  State<_DeliveryCard> createState() => _DeliveryCardState();
}

class _DeliveryCardState extends State<_DeliveryCard> {
  bool _busy = false;

  /// Asks for the customer's code, then completes the delivery.
  ///
  /// Separate from [_move] because this is the one action with something to
  /// collect first, and because a wrong code has to leave the sheet open with
  /// the message - sending the rider back to the list to try again would be
  /// miserable at somebody's door.
  Future<void> _complete() async {
    final controller = TextEditingController();
    String? error;
    var busy = false;

    try {
      final code = await showModalBottomSheet<String>(
        context: context,
        isScrollControlled: true,
        builder: (sheetContext) => Padding(
          padding: EdgeInsets.only(
            left: 20,
            right: 20,
            top: 20,
            bottom: MediaQuery.of(sheetContext).viewInsets.bottom + 20,
          ),
          child: StatefulBuilder(
            builder: (sheetContext, setSheetState) => Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                const Text(
                  'Ask for their code',
                  style: TextStyle(fontSize: 18, fontWeight: FontWeight.w800),
                ),
                const SizedBox(height: 6),
                const Text(
                  'The customer has a 4-digit code on their order. Enter it to '
                  'confirm you handed the food over.',
                  style: TextStyle(fontSize: 13, color: AppTheme.textSecondary),
                ),
                const SizedBox(height: 16),
                TextField(
                  controller: controller,
                  autofocus: true,
                  keyboardType: TextInputType.number,
                  textAlign: TextAlign.center,
                  maxLength: 4,
                  style: const TextStyle(
                    fontSize: 28,
                    fontWeight: FontWeight.w800,
                    letterSpacing: 10,
                  ),
                  decoration: InputDecoration(
                    counterText: '',
                    hintText: '0000',
                    errorText: error,
                  ),
                  onChanged: (_) {
                    if (error != null) setSheetState(() => error = null);
                  },
                ),
                const SizedBox(height: 12),
                ElevatedButton(
                  onPressed: busy
                      ? null
                      : () {
                          final entered = controller.text.trim();
                          if (entered.length != 4) {
                            setSheetState(() => error = 'Enter the 4 digits');
                            return;
                          }
                          setSheetState(() => busy = true);
                          Navigator.pop(sheetContext, entered);
                        },
                  child: const Text('Confirm delivery'),
                ),
              ],
            ),
          ),
        ),
      );

      if (code == null || !mounted) return;
      await _move(OrderStatus.completed, deliveryCode: code);
    } finally {
      controller.dispose();
    }
  }

  Future<void> _move(OrderStatus status, {String? deliveryCode}) async {
    setState(() => _busy = true);
    try {
      await context
          .read<RiderState>()
          .setStatus(widget.order, status, deliveryCode: deliveryCode);
    } on ApiException catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context)
          ..hideCurrentSnackBar()
          ..showSnackBar(SnackBar(content: Text(e.message)));
      }
    } catch (_) {
      if (mounted) {
        ScaffoldMessenger.of(context)
          ..hideCurrentSnackBar()
          ..showSnackBar(
            const SnackBar(content: Text("Couldn't reach the server. Try again.")),
          );
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final order = widget.order;

    return Card(
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // Destination first and largest. It is the one thing a rider reads
            // while walking.
            Row(
              children: [
                const Icon(Icons.place, size: 20, color: AppTheme.primaryRed),
                const SizedBox(width: 6),
                Expanded(
                  child: Text(
                    order.deliveryLocationLabel ?? 'On campus',
                    style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w800),
                  ),
                ),
                Text(
                  '₹${order.totalAmount.toStringAsFixed(0)}',
                  style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w800),
                ),
              ],
            ),
            const SizedBox(height: 10),
            for (final item in order.items)
              Padding(
                padding: const EdgeInsets.only(bottom: 3),
                child: Row(
                  children: [
                    Text(
                      '${item.quantity}x ',
                      style: const TextStyle(fontWeight: FontWeight.w800),
                    ),
                    Expanded(child: Text(item.nameSnapshot)),
                  ],
                ),
              ),
            if (order.note != null && order.note!.isNotEmpty) ...[
              const SizedBox(height: 8),
              Container(
                width: double.infinity,
                padding: const EdgeInsets.all(10),
                decoration: BoxDecoration(
                  color: AppTheme.warning.withValues(alpha: 0.1),
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Text(
                  'Note: ${order.note}',
                  style: const TextStyle(fontSize: 13),
                ),
              ),
            ],
            const Padding(
              padding: EdgeInsets.symmetric(vertical: 10),
              child: Divider(height: 1),
            ),
            if (order.customerPhone != null)
              Row(
                children: [
                  const Icon(Icons.person_outline, size: 18, color: AppTheme.textSecondary),
                  const SizedBox(width: 6),
                  Expanded(
                    child: Text(
                      order.customerName ?? 'Customer',
                      style: const TextStyle(fontWeight: FontWeight.w700),
                    ),
                  ),
                  // The reason assignment exchanges numbers at all.
                  OutlinedButton.icon(
                    onPressed: () => launchUrl(Uri.parse('tel:${order.customerPhone}')),
                    icon: const Icon(Icons.call, size: 18),
                    label: const Text('Call'),
                  ),
                ],
              ),
            const SizedBox(height: 10),
            _action(order),
          ],
        ),
      ),
    );
  }

  Widget _action(Order order) {
    if (_busy) {
      return const Center(
        child: Padding(
          padding: EdgeInsets.all(6),
          child: SizedBox(
            height: 20,
            width: 20,
            child: CircularProgressIndicator(color: AppTheme.primaryRed, strokeWidth: 2.5),
          ),
        ),
      );
    }

    // Only two buttons exist here, because only two statuses are a rider's to
    // set. Everything before "ready" is the stall still cooking, and saying so
    // is better than a disabled button that looks like a bug.
    return switch (order.status) {
      OrderStatus.ready => SizedBox(
          width: double.infinity,
          child: ElevatedButton.icon(
            onPressed: () => _move(OrderStatus.outForDelivery),
            icon: const Icon(Icons.directions_bike, size: 18),
            label: const Text('Picked it up'),
          ),
        ),
      OrderStatus.outForDelivery => SizedBox(
          width: double.infinity,
          child: ElevatedButton.icon(
            onPressed: _complete,
            icon: const Icon(Icons.check, size: 18),
            label: const Text('Delivered'),
          ),
        ),
      _ => Container(
          width: double.infinity,
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
          decoration: BoxDecoration(
            color: AppTheme.textSecondary.withValues(alpha: 0.07),
            borderRadius: BorderRadius.circular(8),
          ),
          child: Row(
            children: [
              const Icon(Icons.soup_kitchen_outlined, size: 16, color: AppTheme.textSecondary),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  'Still being made - ${order.status.label.toLowerCase()}',
                  style: const TextStyle(fontSize: 13, color: AppTheme.textSecondary),
                ),
              ),
            ],
          ),
        ),
    };
  }
}
