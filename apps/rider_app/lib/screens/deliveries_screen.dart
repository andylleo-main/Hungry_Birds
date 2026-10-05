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

  /// Takes the cash, after asking once.
  ///
  /// Confirmed because it is the rider asserting money changed hands and there
  /// is no way to take it back from the app - a stray tap while the phone is in
  /// a pocket would mark an order paid that nobody paid for.
  Future<void> _collectCash(Order order) async {
    final sure = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text('Collected \u20b9${order.totalAmount.toStringAsFixed(0)}?'),
        content: const Text(
          'Only tap yes once the customer has handed you the cash. '
          'This marks the order paid.',
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Not yet')),
          TextButton(onPressed: () => Navigator.pop(context, true), child: const Text('Got it')),
        ],
      ),
    );
    if (sure != true || !mounted) return;

    setState(() => _busy = true);
    try {
      await context.read<RiderState>().collectCash(order);
    } on ApiException catch (e) {
      _say(e.message);
    } catch (_) {
      _say("Couldn't reach the server. Try again.");
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  /// Shows a QR for exactly this order's total.
  ///
  /// Nothing is marked paid here, and the sheet says so: Razorpay tells the
  /// server when the money lands, and the order updates itself on the next poll.
  /// A rider who taps "Delivered" too early is refused by the server, which is
  /// the point.
  Future<void> _showUpiQr(Order order) async {
    setState(() => _busy = true);
    UpiQr qr;
    try {
      qr = await context.read<RiderState>().upiQr(order);
    } on ApiException catch (e) {
      // Including Razorpay not having QR codes switched on for this account,
      // which the server phrases as "please collect cash".
      _say(e.message);
      return;
    } catch (_) {
      _say("Couldn't make a QR. Collect cash instead.");
      return;
    } finally {
      if (mounted) setState(() => _busy = false);
    }

    if (!mounted) return;
    await showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      builder: (context) => SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(20),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(
                '\u20b9${qr.amount.toStringAsFixed(0)}',
                style: const TextStyle(fontSize: 30, fontWeight: FontWeight.w900),
              ),
              const SizedBox(height: 4),
              const Text(
                'Ask the customer to scan with any UPI app',
                style: TextStyle(color: AppTheme.textSecondary, fontSize: 13),
              ),
              const SizedBox(height: 16),
              // Razorpay renders and hosts the image, so there is no QR package
              // in this app and nothing here has to encode a payment string.
              ConstrainedBox(
                constraints: const BoxConstraints(maxHeight: 280),
                child: Image.network(
                  qr.imageUrl,
                  fit: BoxFit.contain,
                  errorBuilder: (_, __, ___) => const Padding(
                    padding: EdgeInsets.all(24),
                    child: Text("Couldn't load the QR. Collect cash instead."),
                  ),
                  loadingBuilder: (_, child, progress) => progress == null
                      ? child
                      : const Padding(
                          padding: EdgeInsets.all(40),
                          child: CircularProgressIndicator(),
                        ),
                ),
              ),
              const SizedBox(height: 16),
              const Text(
                'It marks itself paid once the money arrives. '
                'You do not need to confirm anything.',
                textAlign: TextAlign.center,
                style: TextStyle(color: AppTheme.textSecondary, fontSize: 12),
              ),
              const SizedBox(height: 12),
              SizedBox(
                width: double.infinity,
                child: OutlinedButton(
                  onPressed: () => Navigator.pop(context),
                  child: const Text('Close'),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  void _say(String message) {
    if (!mounted) return;
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(content: Text(message)));
  }

  /// The amount still owed, and the two ways to take it.
  Widget _collect(Order order) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: AppTheme.warning.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(10),
        border: const Border(left: BorderSide(color: AppTheme.warning, width: 4)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Icon(Icons.payments_outlined, size: 18),
              const SizedBox(width: 8),
              Text(
                'COLLECT \u20b9${order.totalAmount.toStringAsFixed(0)}',
                style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w900),
              ),
            ],
          ),
          const SizedBox(height: 10),
          Row(
            children: [
              Expanded(
                child: OutlinedButton.icon(
                  onPressed: _busy ? null : () => _collectCash(order),
                  icon: const Icon(Icons.currency_rupee, size: 16),
                  label: const Text('Cash'),
                ),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: ElevatedButton.icon(
                  onPressed: _busy ? null : () => _showUpiQr(order),
                  icon: const Icon(Icons.qr_code_2, size: 18),
                  label: const Text('UPI QR'),
                ),
              ),
            ],
          ),
        ],
      ),
    );
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
              const SizedBox(height: 10),
              // Same treatment as the merchant card, and for the same reason: a
              // rider reads this card while walking, and "leave it at the gate,
              // don't call" has to survive being glanced at.
              Container(
                width: double.infinity,
                decoration: BoxDecoration(
                  color: AppTheme.warning.withValues(alpha: 0.12),
                  borderRadius: BorderRadius.circular(8),
                  border: const Border(
                    left: BorderSide(color: AppTheme.warning, width: 4),
                  ),
                ),
                padding: const EdgeInsets.fromLTRB(12, 10, 12, 10),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        const Icon(Icons.sticky_note_2, size: 16, color: AppTheme.warning),
                        const SizedBox(width: 6),
                        Text(
                          'NOTE FROM THE CUSTOMER',
                          style: TextStyle(
                            fontSize: 11,
                            fontWeight: FontWeight.w800,
                            letterSpacing: 0.6,
                            color: AppTheme.warning.withValues(alpha: 0.95),
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 4),
                    Text(
                      order.note!,
                      style: const TextStyle(
                        fontSize: 15,
                        fontWeight: FontWeight.w600,
                        height: 1.3,
                        color: AppTheme.textPrimary,
                      ),
                    ),
                  ],
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
            if (order.isAwaitingCollection) ...[
              const SizedBox(height: 10),
              _collect(order),
            ],
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
