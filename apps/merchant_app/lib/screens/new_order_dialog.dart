import 'package:flutter/material.dart';
import 'package:hb_shared/hb_shared.dart';
import 'package:provider/provider.dart';

import '../state/orders_state.dart';

/// The full-screen interruption when an order lands.
///
/// Full-screen, and loud to look at, because the alarm respects the phone's
/// silent setting - so on a muted phone this is the *only* signal there is. A
/// toast or a banner would be missable across a counter during service, which is
/// the one moment this exists for.
///
/// Raised through a navigator key rather than a BuildContext, because the thing
/// that knows an order arrived is a ChangeNotifier listening to a socket and it
/// holds no context of its own.
class NewOrderDialog extends StatelessWidget {
  const NewOrderDialog({super.key, required this.order});

  final Order order;

  /// Shows the dialog, and stops the chime whichever way it is dismissed.
  ///
  /// Barrier dismissal is off on purpose: a stray tap while wiping a counter
  /// should not silently clear an order nobody has read.
  static Future<void> show(BuildContext context, Order order) {
    return showDialog<void>(
      context: context,
      barrierDismissible: false,
      builder: (_) => NewOrderDialog(order: order),
    );
  }

  @override
  Widget build(BuildContext context) {
    final items = order.items;

    return Dialog.fullscreen(
      backgroundColor: AppTheme.primaryRed,
      child: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(20),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const SizedBox(height: 12),
              const Icon(Icons.notifications_active, size: 44, color: Colors.white),
              const SizedBox(height: 10),
              const Text(
                'NEW ORDER',
                textAlign: TextAlign.center,
                style: TextStyle(
                  color: Colors.white,
                  fontSize: 30,
                  fontWeight: FontWeight.w900,
                  letterSpacing: 2,
                ),
              ),
              if (order.tokenNumber != null)
                Text(
                  'Token #${order.tokenNumber}',
                  textAlign: TextAlign.center,
                  style: const TextStyle(
                    color: Colors.white,
                    fontSize: 20,
                    fontWeight: FontWeight.w700,
                  ),
                ),
              const SizedBox(height: 18),

              Expanded(
                child: Container(
                  width: double.infinity,
                  padding: const EdgeInsets.all(16),
                  decoration: BoxDecoration(
                    color: Colors.white,
                    borderRadius: BorderRadius.circular(12),
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        order.isDelivery
                            ? 'Delivery · ${order.deliveryLocationLabel ?? "on campus"}'
                            : 'Dine in',
                        style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 15),
                      ),
                      const Divider(height: 18),
                      Expanded(
                        child: ListView(
                          children: [
                            for (final item in items)
                              Padding(
                                padding: const EdgeInsets.only(bottom: 6),
                                child: Row(
                                  crossAxisAlignment: CrossAxisAlignment.start,
                                  children: [
                                    Text(
                                      '${item.quantity}× ',
                                      style: const TextStyle(
                                        fontWeight: FontWeight.w800,
                                        fontSize: 16,
                                      ),
                                    ),
                                    Expanded(
                                      child: Text(
                                        item.variantName == null
                                            ? item.nameSnapshot
                                            : '${item.nameSnapshot} · ${item.variantName}',
                                        style: const TextStyle(fontSize: 16),
                                      ),
                                    ),
                                  ],
                                ),
                              ),
                            if (order.note != null && order.note!.isNotEmpty) ...[
                              const SizedBox(height: 10),
                              Container(
                                width: double.infinity,
                                padding: const EdgeInsets.all(10),
                                decoration: BoxDecoration(
                                  color: AppTheme.warning.withValues(alpha: 0.15),
                                  borderRadius: BorderRadius.circular(8),
                                  border: const Border(
                                    left: BorderSide(color: AppTheme.warning, width: 4),
                                  ),
                                ),
                                child: Text(
                                  order.note!,
                                  style: const TextStyle(
                                    fontSize: 15,
                                    fontWeight: FontWeight.w600,
                                  ),
                                ),
                              ),
                            ],
                          ],
                        ),
                      ),
                      const Divider(height: 18),
                      Text(
                        '₹${order.totalAmount.toStringAsFixed(0)}',
                        style: const TextStyle(fontSize: 22, fontWeight: FontWeight.w900),
                      ),
                    ],
                  ),
                ),
              ),

              const SizedBox(height: 16),
              // Only dismisses. Accepting and rejecting stay on the order card,
              // where the merchant can see the whole queue - deciding from a
              // dialog that covers everything else is how the wrong order gets
              // accepted during a rush.
              SizedBox(
                height: 54,
                child: ElevatedButton(
                  onPressed: () {
                    context.read<OrdersState>().acknowledge(order);
                    Navigator.of(context).pop();
                  },
                  style: ElevatedButton.styleFrom(
                    backgroundColor: Colors.white,
                    foregroundColor: AppTheme.primaryRed,
                  ),
                  child: const Text(
                    'Got it',
                    style: TextStyle(fontSize: 17, fontWeight: FontWeight.w800),
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
