import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:hb_shared/hb_shared.dart';
import 'package:provider/provider.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

import '../../widgets/order_status_timeline.dart';

class OrderTrackingScreen extends StatefulWidget {
  final String orderId;
  final String? vendorName;

  const OrderTrackingScreen({super.key, required this.orderId, this.vendorName});

  @override
  State<OrderTrackingScreen> createState() => _OrderTrackingScreenState();
}

class _OrderTrackingScreenState extends State<OrderTrackingScreen> {
  Order? _order;
  Object? _error;
  bool _cancelling = false;

  WebSocketChannel? _channel;
  StreamSubscription? _subscription;
  Timer? _reconnectTimer;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _reconnectTimer?.cancel();
    _subscription?.cancel();
    _channel?.sink.close();
    super.dispose();
  }

  Future<void> _load() async {
    try {
      final order = await context.read<ApiClient>().orderDetail(widget.orderId);
      if (!mounted) return;
      setState(() {
        _order = order;
        _error = null;
      });
      unawaited(_connectSocket());
    } catch (e) {
      if (!mounted) return;
      setState(() => _error = e);
    }
  }

  // Async because the socket URL needs a ticket fetched from the API first
  // (see ApiClient._wsUri); failing to get one just schedules a reconnect.
  Future<void> _connectSocket() async {
    _subscription?.cancel();
    _channel?.sink.close();

    final api = context.read<ApiClient>();
    try {
      final url = await api.orderSocketUrl(widget.orderId);
      if (!mounted) return;
      final channel = WebSocketChannel.connect(url);
      _channel = channel;
      _subscription = channel.stream.listen(
        (event) {
          final decoded = jsonDecode(event as String) as Map<String, dynamic>;
          if (!mounted) return;
          setState(() => _order = Order.fromJson(decoded));
        },
        onDone: _scheduleReconnect,
        onError: (_) => _scheduleReconnect(),
      );
    } catch (_) {
      _scheduleReconnect();
    }
  }

  /// The socket only pushes deltas, so on every reconnect we re-fetch the
  /// order to make sure we didn't miss a status change while disconnected.
  void _scheduleReconnect() {
    if (!mounted) return;
    if (_order?.status.isTerminal ?? false) return;
    _reconnectTimer?.cancel();
    _reconnectTimer = Timer(const Duration(seconds: 3), () {
      if (!mounted) return;
      _load();
    });
  }

  Future<void> _cancel() async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Cancel this order?'),
        content: const Text('The stall will be told you cancelled.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Keep it')),
          TextButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Cancel order'),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;

    setState(() => _cancelling = true);
    try {
      final order = await context.read<ApiClient>().cancelOrder(widget.orderId);
      if (!mounted) return;
      setState(() => _order = order);
    } on ApiException catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.message)));
    } finally {
      if (mounted) setState(() => _cancelling = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(widget.vendorName ?? 'Your order')),
      body: _buildBody(),
    );
  }

  Widget _buildBody() {
    if (_error != null) {
      return ErrorRetry(message: _error.toString(), onRetry: _load);
    }
    final order = _order;
    if (order == null) {
      return const Center(child: CircularProgressIndicator(color: AppTheme.primaryRed));
    }

    return ListView(
      padding: const EdgeInsets.fromLTRB(16, 16, 16, 32),
      children: [
        _StatusBanner(status: order.status),
        const SizedBox(height: 20),
        if (order.status.isActive) ...[
          Card(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: OrderStatusTimeline(status: order.status),
            ),
          ),
          const SizedBox(height: 16),
        ],
        Card(
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  'Order summary',
                  style: TextStyle(fontWeight: FontWeight.w800, fontSize: 16),
                ),
                const SizedBox(height: 12),
                for (final item in order.items)
                  Padding(
                    padding: const EdgeInsets.symmetric(vertical: 5),
                    child: Row(
                      children: [
                        Text(
                          '${item.quantity}x ',
                          style: const TextStyle(fontWeight: FontWeight.w700),
                        ),
                        Expanded(child: Text(item.nameSnapshot)),
                        Text('₹${(item.priceSnapshot * item.quantity).toStringAsFixed(0)}'),
                      ],
                    ),
                  ),
                const Padding(
                  padding: EdgeInsets.symmetric(vertical: 10),
                  child: Divider(height: 1),
                ),
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    const Text(
                      'Total (cash)',
                      style: TextStyle(fontWeight: FontWeight.w800, fontSize: 16),
                    ),
                    Text(
                      '₹${order.totalAmount.toStringAsFixed(0)}',
                      style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 16),
                    ),
                  ],
                ),
                if (order.note != null && order.note!.isNotEmpty) ...[
                  const SizedBox(height: 12),
                  Text(
                    'Note: ${order.note}',
                    style: const TextStyle(color: AppTheme.textSecondary, fontSize: 13),
                  ),
                ],
              ],
            ),
          ),
        ),
        if (order.status == OrderStatus.placed) ...[
          const SizedBox(height: 16),
          OutlinedButton(
            onPressed: _cancelling ? null : _cancel,
            child: Text(_cancelling ? 'Cancelling…' : 'Cancel order'),
          ),
        ],
      ],
    );
  }
}

class _StatusBanner extends StatelessWidget {
  final OrderStatus status;

  const _StatusBanner({required this.status});

  @override
  Widget build(BuildContext context) {
    final (color, icon, message) = switch (status) {
      OrderStatus.placed => (
          AppTheme.warning,
          Icons.hourglass_top,
          'Waiting for the stall to accept your order',
        ),
      OrderStatus.accepted => (AppTheme.success, Icons.thumb_up_alt_outlined, 'Order accepted'),
      OrderStatus.preparing => (AppTheme.warning, Icons.soup_kitchen_outlined, 'Being prepared'),
      OrderStatus.ready => (AppTheme.success, Icons.shopping_bag_outlined, 'Ready for pickup'),
      OrderStatus.completed => (AppTheme.success, Icons.check_circle_outline, 'Order completed'),
      OrderStatus.rejected => (
          AppTheme.primaryRed,
          Icons.cancel_outlined,
          'The stall could not take this order',
        ),
      OrderStatus.cancelled => (AppTheme.textSecondary, Icons.do_not_disturb_on_outlined, 'Order cancelled'),
    };

    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.1),
        borderRadius: BorderRadius.circular(14),
      ),
      child: Row(
        children: [
          Icon(icon, color: color),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  status.label,
                  style: TextStyle(color: color, fontWeight: FontWeight.w800, fontSize: 16),
                ),
                const SizedBox(height: 2),
                Text(message, style: const TextStyle(fontSize: 13, color: AppTheme.textSecondary)),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
