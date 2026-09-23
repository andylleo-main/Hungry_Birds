import 'package:flutter/material.dart';
import 'package:hb_shared/hb_shared.dart';
import 'package:provider/provider.dart';

import '../../state/auth_state.dart';
import '../../state/cart_state.dart';
import '../../widgets/contact_details_sheet.dart';
import '../orders/order_tracking_screen.dart';

class CartScreen extends StatefulWidget {
  const CartScreen({super.key});

  @override
  State<CartScreen> createState() => _CartScreenState();
}

class _CartScreenState extends State<CartScreen> {
  final _noteController = TextEditingController();
  bool _placing = false;

  @override
  void dispose() {
    _noteController.dispose();
    super.dispose();
  }

  Future<void> _placeOrder() async {
    final cart = context.read<CartState>();
    final vendor = cart.vendor;
    if (vendor == null || cart.isEmpty) return;

    // The backend rejects an order from a customer with no phone, so ask for
    // one here rather than letting the order fail with an error message.
    if (!(context.read<AuthState>().currentUser?.hasPhone ?? false)) {
      final saved = await showContactDetailsSheet(
        context,
        title: 'How should the stall reach you?',
        subtitle: 'They call this number when your order is ready for pickup.',
      );
      if (!saved || !mounted) return;
    }

    setState(() => _placing = true);
    try {
      final note = _noteController.text.trim();
      final order = await context.read<ApiClient>().placeOrder(
            vendorId: vendor.id,
            items: cart.toOrderItems(),
            note: note.isEmpty ? null : note,
          );
      cart.clear();
      if (!mounted) return;
      Navigator.of(context).pushReplacement(
        MaterialPageRoute(
          builder: (_) => OrderTrackingScreen(orderId: order.id, vendorName: vendor.stallName),
        ),
      );
    } on ApiException catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.message)));
    } catch (_) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text("Couldn't place the order. Check your connection.")),
      );
    } finally {
      if (mounted) setState(() => _placing = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final cart = context.watch<CartState>();
    final vendor = cart.vendor;

    return Scaffold(
      appBar: AppBar(title: const Text('Your cart')),
      body: cart.isEmpty || vendor == null
          ? const EmptyState(
              icon: Icons.shopping_bag_outlined,
              title: 'Your cart is empty',
              message: 'Add items from a campus stall to get started.',
            )
          : ListView(
              padding: const EdgeInsets.fromLTRB(16, 8, 16, 24),
              children: [
                Text(
                  vendor.stallName,
                  style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w800),
                ),
                const SizedBox(height: 12),
                Card(
                  child: Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 4),
                    child: Column(
                      children: [
                        for (final item in vendor.allItems)
                          if (cart.quantityOf(item.id) > 0)
                            _CartLine(item: item, quantity: cart.quantityOf(item.id)),
                      ],
                    ),
                  ),
                ),
                const SizedBox(height: 16),
                TextField(
                  controller: _noteController,
                  maxLines: 2,
                  decoration: const InputDecoration(
                    labelText: 'Note for the stall (optional)',
                    hintText: 'e.g. less spicy, no onion',
                  ),
                ),
                const SizedBox(height: 16),
                Card(
                  child: Padding(
                    padding: const EdgeInsets.all(14),
                    child: Column(
                      children: [
                        Row(
                          mainAxisAlignment: MainAxisAlignment.spaceBetween,
                          children: [
                            const Text('Item total'),
                            Text('₹${cart.total.toStringAsFixed(0)}'),
                          ],
                        ),
                        const Padding(
                          padding: EdgeInsets.symmetric(vertical: 10),
                          child: Divider(height: 1),
                        ),
                        Row(
                          mainAxisAlignment: MainAxisAlignment.spaceBetween,
                          children: [
                            const Text(
                              'To pay (cash)',
                              style: TextStyle(fontWeight: FontWeight.w800, fontSize: 16),
                            ),
                            Text(
                              '₹${cart.total.toStringAsFixed(0)}',
                              style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 16),
                            ),
                          ],
                        ),
                      ],
                    ),
                  ),
                ),
                const SizedBox(height: 12),
                const Row(
                  children: [
                    Icon(Icons.payments_outlined, size: 18, color: AppTheme.textSecondary),
                    SizedBox(width: 8),
                    Expanded(
                      child: Text(
                        'Cash on delivery only. Pay the stall when you collect your order.',
                        style: TextStyle(color: AppTheme.textSecondary, fontSize: 13),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 20),
                ElevatedButton(
                  onPressed: _placing ? null : _placeOrder,
                  child: _placing
                      ? const SizedBox(
                          height: 20,
                          width: 20,
                          child: CircularProgressIndicator(color: Colors.white, strokeWidth: 2.5),
                        )
                      : Text('Place order · ₹${cart.total.toStringAsFixed(0)}'),
                ),
              ],
            ),
    );
  }
}

class _CartLine extends StatelessWidget {
  final MenuItem item;
  final int quantity;

  const _CartLine({required this.item, required this.quantity});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 10),
      child: Row(
        children: [
          Expanded(
            child: Text(item.name, style: const TextStyle(fontWeight: FontWeight.w600)),
          ),
          _QuantityStepper(item: item, quantity: quantity),
          SizedBox(
            width: 62,
            child: Text(
              '₹${(item.price * quantity).toStringAsFixed(0)}',
              textAlign: TextAlign.right,
              style: const TextStyle(fontWeight: FontWeight.w700),
            ),
          ),
        ],
      ),
    );
  }
}

class _QuantityStepper extends StatelessWidget {
  final MenuItem item;
  final int quantity;

  const _QuantityStepper({required this.item, required this.quantity});

  @override
  Widget build(BuildContext context) {
    final cart = context.read<CartState>();
    return Container(
      decoration: BoxDecoration(
        border: Border.all(color: AppTheme.primaryRed),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          InkWell(
            onTap: () => cart.removeOne(item),
            child: const Padding(
              padding: EdgeInsets.all(6),
              child: Icon(Icons.remove, size: 16, color: AppTheme.primaryRed),
            ),
          ),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 4),
            child: Text(
              '$quantity',
              style: const TextStyle(color: AppTheme.primaryRed, fontWeight: FontWeight.w800),
            ),
          ),
          InkWell(
            onTap: () => cart.add(item, cart.vendor!),
            child: const Padding(
              padding: EdgeInsets.all(6),
              child: Icon(Icons.add, size: 16, color: AppTheme.primaryRed),
            ),
          ),
        ],
      ),
    );
  }
}
