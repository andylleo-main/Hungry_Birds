import 'package:flutter/material.dart';
import 'package:hb_shared/hb_shared.dart';
import 'package:intl/intl.dart';
import 'package:provider/provider.dart';

import 'order_tracking_screen.dart';

class OrderHistoryScreen extends StatefulWidget {
  const OrderHistoryScreen({super.key});

  @override
  State<OrderHistoryScreen> createState() => _OrderHistoryScreenState();
}

class _OrderHistoryScreenState extends State<OrderHistoryScreen> {
  late Future<List<Order>> _future;

  @override
  void initState() {
    super.initState();
    _future = context.read<ApiClient>().myOrders();
  }

  Future<void> _reload() async {
    setState(() => _future = context.read<ApiClient>().myOrders());
    await _future;
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Your orders')),
      body: RefreshIndicator(
        color: AppTheme.primaryRed,
        onRefresh: _reload,
        child: FutureBuilder<List<Order>>(
          future: _future,
          builder: (context, snapshot) {
            if (snapshot.connectionState == ConnectionState.waiting) {
              return const Center(child: CircularProgressIndicator(color: AppTheme.primaryRed));
            }
            if (snapshot.hasError) {
              return ErrorRetry(message: snapshot.error.toString(), onRetry: _reload);
            }
            final orders = snapshot.data!;
            if (orders.isEmpty) {
              return ListView(
                children: const [
                  SizedBox(height: 80),
                  EmptyState(
                    icon: Icons.receipt_long_outlined,
                    title: 'No orders yet',
                    message: 'Once you order from a campus stall, it shows up here.',
                  ),
                ],
              );
            }

            return ListView.separated(
              padding: const EdgeInsets.all(16),
              itemCount: orders.length,
              separatorBuilder: (_, __) => const SizedBox(height: 12),
              itemBuilder: (context, i) => _OrderCard(order: orders[i]),
            );
          },
        ),
      ),
    );
  }
}

class _OrderCard extends StatelessWidget {
  final Order order;

  const _OrderCard({required this.order});

  @override
  Widget build(BuildContext context) {
    final itemSummary = order.items.map((i) => '${i.quantity}x ${i.nameSnapshot}').join(', ');

    return Card(
      child: InkWell(
        borderRadius: BorderRadius.circular(14),
        onTap: () => Navigator.of(context).push(
          MaterialPageRoute(builder: (_) => OrderTrackingScreen(orderId: order.id)),
        ),
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
              const SizedBox(height: 10),
              Text(
                itemSummary,
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w600),
              ),
              const SizedBox(height: 8),
              Row(
                children: [
                  Text(
                    '₹${order.totalAmount.toStringAsFixed(0)}  ·  Cash',
                    style: const TextStyle(color: AppTheme.textSecondary, fontSize: 13),
                  ),
                  const Spacer(),
                  const Icon(Icons.chevron_right, color: AppTheme.textSecondary, size: 20),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _StatusChip extends StatelessWidget {
  final OrderStatus status;

  const _StatusChip({required this.status});

  @override
  Widget build(BuildContext context) {
    final color = switch (status) {
      OrderStatus.completed || OrderStatus.ready || OrderStatus.accepted => AppTheme.success,
      OrderStatus.outForDelivery => AppTheme.success,
      OrderStatus.placed || OrderStatus.preparing => AppTheme.warning,
      OrderStatus.rejected => AppTheme.primaryRed,
      OrderStatus.cancelled => AppTheme.textSecondary,
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
