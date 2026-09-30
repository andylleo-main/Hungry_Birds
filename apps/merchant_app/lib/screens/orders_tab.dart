import 'package:flutter/material.dart';
import 'package:hb_shared/hb_shared.dart';
import 'package:intl/intl.dart';
import 'package:provider/provider.dart';
import 'package:url_launcher/url_launcher.dart';

import '../state/merchant_state.dart';
import '../state/orders_state.dart';

class OrdersTab extends StatelessWidget {
  const OrdersTab({super.key});

  @override
  Widget build(BuildContext context) {
    final ordersState = context.watch<OrdersState>();
    final merchant = context.watch<MerchantState>();
    final isOpen = merchant.vendor?.isOpen ?? false;

    return Scaffold(
      appBar: AppBar(
        title: const Text('Orders'),
        actions: [
          Padding(
            padding: const EdgeInsets.only(right: 8),
            child: Row(
              children: [
                Text(
                  isOpen ? 'Open' : 'Closed',
                  style: TextStyle(
                    color: isOpen ? AppTheme.success : AppTheme.textSecondary,
                    fontWeight: FontWeight.w700,
                    fontSize: 13,
                  ),
                ),
                Switch(
                  value: isOpen,
                  activeThumbColor: AppTheme.success,
                  onChanged: (value) => context.read<MerchantState>().setOpen(value),
                ),
              ],
            ),
          ),
        ],
      ),
      body: _buildBody(context, ordersState),
    );
  }

  Widget _buildBody(BuildContext context, OrdersState state) {
    if (state.loading) {
      return const Center(child: CircularProgressIndicator(color: AppTheme.primaryRed));
    }
    if (state.error != null) {
      return ErrorRetry(message: state.error.toString(), onRetry: state.load);
    }

    final active = state.activeOrders;
    final past = state.pastOrders;

    if (active.isEmpty && past.isEmpty) {
      return const EmptyState(
        icon: Icons.receipt_long_outlined,
        title: 'No orders yet',
        message: 'New orders from students land here the moment they are placed.',
      );
    }

    return RefreshIndicator(
      color: AppTheme.primaryRed,
      onRefresh: state.load,
      child: ListView(
        padding: const EdgeInsets.fromLTRB(16, 8, 16, 24),
        children: [
          if (active.isNotEmpty) ...[
            const _SectionTitle('Live orders'),
            for (final order in active) ...[
              _OrderCard(order: order, live: true),
              const SizedBox(height: 12),
            ],
          ],
          if (past.isNotEmpty) ...[
            const SizedBox(height: 8),
            const _SectionTitle('Past orders'),
            for (final order in past) ...[
              _OrderCard(order: order, live: false),
              const SizedBox(height: 12),
            ],
          ],
        ],
      ),
    );
  }
}

class _SectionTitle extends StatelessWidget {
  final String text;

  const _SectionTitle(this.text);

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(bottom: 10, top: 4),
        child: Text(text, style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w800)),
      );
}

class _OrderCard extends StatefulWidget {
  final Order order;
  final bool live;

  const _OrderCard({required this.order, required this.live});

  @override
  State<_OrderCard> createState() => _OrderCardState();
}

class _OrderCardState extends State<_OrderCard> {
  bool _busy = false;

  Future<void> _move(OrderStatus status) async {
    setState(() => _busy = true);
    try {
      await context.read<OrdersState>().updateStatus(widget.order, status);
    } on ApiException catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.message)));
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
            Row(
              children: [
                _StatusChip(status: order.status),
                const Spacer(),
                Text(
                  DateFormat('d MMM, h:mm a').format(order.createdAt.toLocal()),
                  style: const TextStyle(color: AppTheme.textSecondary, fontSize: 12),
                ),
              ],
            ),
            const SizedBox(height: 12),
            for (final item in order.items)
              Padding(
                padding: const EdgeInsets.only(bottom: 4),
                child: Row(
                  children: [
                    Text('${item.quantity}x ', style: const TextStyle(fontWeight: FontWeight.w800)),
                    Expanded(child: Text(item.nameSnapshot)),
                    Text('₹${(item.priceSnapshot * item.quantity).toStringAsFixed(0)}'),
                  ],
                ),
              ),
            const SizedBox(height: 8),
            // Where this order is going. A delivery whose destination is not on
            // the card is an order the stall cannot actually fulfil, so this sits
            // above the note rather than beside the total.
            Container(
              width: double.infinity,
              padding: const EdgeInsets.all(10),
              decoration: BoxDecoration(
                color: (order.isDelivery ? AppTheme.primaryRed : AppTheme.textSecondary)
                    .withValues(alpha: 0.08),
                borderRadius: BorderRadius.circular(8),
              ),
              child: Row(
                children: [
                  Icon(
                    order.isDelivery ? Icons.delivery_dining : Icons.restaurant,
                    size: 18,
                    color: order.isDelivery ? AppTheme.primaryRed : AppTheme.textSecondary,
                  ),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      order.isDelivery
                          ? 'Deliver to ${order.deliveryLocationLabel ?? 'an unnamed place'}'
                          : 'Dine in - collecting at the counter',
                      style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w700),
                    ),
                  ),
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
                  style: const TextStyle(fontSize: 13, color: AppTheme.textPrimary),
                ),
              ),
            ],
            const Padding(
              padding: EdgeInsets.symmetric(vertical: 10),
              child: Divider(height: 1),
            ),
            Row(
              children: [
                Expanded(
                  child: Text(
                    'Collect ₹${order.totalAmount.toStringAsFixed(0)} in cash',
                    style: const TextStyle(fontWeight: FontWeight.w700),
                  ),
                ),
              ],
            ),
            if (order.customerPhone != null) ...[
              const SizedBox(height: 10),
              _CustomerContact(name: order.customerName, phone: order.customerPhone!),
            ],
            if (widget.live) ...[
              const SizedBox(height: 12),
              _actions(order),
            ],
          ],
        ),
      ),
    );
  }

  Widget _actions(Order order) {
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

    return switch (order.status) {
      OrderStatus.placed => Row(
          children: [
            Expanded(
              child: OutlinedButton(
                onPressed: () => _move(OrderStatus.rejected),
                child: const Text('Reject'),
              ),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: ElevatedButton(
                onPressed: () => _move(OrderStatus.accepted),
                child: const Text('Accept'),
              ),
            ),
          ],
        ),
      OrderStatus.accepted => SizedBox(
          width: double.infinity,
          child: ElevatedButton(
            onPressed: () => _move(OrderStatus.preparing),
            child: const Text('Start preparing'),
          ),
        ),
      OrderStatus.preparing => SizedBox(
          width: double.infinity,
          child: ElevatedButton(
            onPressed: () => _move(OrderStatus.ready),
            child: const Text('Mark ready for pickup'),
          ),
        ),
      OrderStatus.ready => SizedBox(
          width: double.infinity,
          child: ElevatedButton(
            onPressed: () => _move(OrderStatus.completed),
            child: const Text('Mark completed'),
          ),
        ),
      _ => const SizedBox.shrink(),
    };
  }
}

class _StatusChip extends StatelessWidget {
  final OrderStatus status;

  const _StatusChip({required this.status});

  @override
  Widget build(BuildContext context) {
    final color = switch (status) {
      OrderStatus.completed || OrderStatus.ready || OrderStatus.accepted => AppTheme.success,
      OrderStatus.placed || OrderStatus.preparing => AppTheme.warning,
      OrderStatus.rejected => AppTheme.primaryRed,
      OrderStatus.cancelled => AppTheme.textSecondary,
      // A status from a newer server. Left deliberately exhaustive rather than
      // given a wildcard: the analyzer then flags every switch like this one the
      // next time a status is added, which is the whole reason the enum has an
      // unknown member instead of throwing while decoding.
      OrderStatus.unknown => AppTheme.textSecondary,
    };

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(6),
      ),
      child: Text(
        status.label,
        style: TextStyle(color: color, fontWeight: FontWeight.w700, fontSize: 12),
      ),
    );
  }
}

/// Customer name + phone with a one-tap call button. COD pickup means the
/// stall regularly needs to ring the customer when an order is ready.
class _CustomerContact extends StatelessWidget {
  const _CustomerContact({required this.name, required this.phone});

  final String? name;
  final String phone;

  Future<void> _call(BuildContext context) async {
    final uri = Uri(scheme: 'tel', path: phone);
    if (!await launchUrl(uri)) {
      if (context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Could not start a call. Number: $phone')),
        );
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
      decoration: BoxDecoration(
        color: AppTheme.background,
        borderRadius: BorderRadius.circular(8),
      ),
      child: Row(
        children: [
          const Icon(Icons.person_outline, size: 18, color: AppTheme.textSecondary),
          const SizedBox(width: 8),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  name?.isNotEmpty == true ? name! : 'Customer',
                  style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 13),
                ),
                Text(
                  '+91 ${formatPhoneForDisplay(phone)}',
                  style: const TextStyle(color: AppTheme.textSecondary, fontSize: 12),
                ),
              ],
            ),
          ),
          TextButton.icon(
            onPressed: () => _call(context),
            icon: const Icon(Icons.call, size: 16),
            label: const Text('Call'),
          ),
        ],
      ),
    );
  }
}
