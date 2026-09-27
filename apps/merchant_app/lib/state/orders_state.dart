import 'dart:async';
import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:hb_shared/hb_shared.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

/// The vendor's order queue. Seeded by a fetch, then kept current by the
/// vendor WebSocket so new orders and status changes land without polling.
class OrdersState extends ChangeNotifier {
  final ApiClient api;

  OrdersState(this.api);

  List<Order> orders = [];
  bool loading = true;
  Object? error;

  String? _vendorId;
  WebSocketChannel? _channel;
  StreamSubscription? _subscription;
  Timer? _reconnectTimer;

  List<Order> get activeOrders => orders.where((o) => o.status.isActive).toList();
  List<Order> get pastOrders => orders.where((o) => o.status.isTerminal).toList();

  Future<void> start(String vendorId) async {
    _vendorId = vendorId;
    await load();
    await _connect();
  }

  Future<void> load() async {
    try {
      orders = await api.vendorOrders();
      error = null;
    } catch (e) {
      error = e;
    } finally {
      loading = false;
      notifyListeners();
    }
  }

  // Async because the socket URL now needs a ticket fetched from the API first
  // (see ApiClient._wsUri). A failure to get one is just another reason to
  // retry, handled by the same reconnect path as a dropped socket.
  Future<void> _connect() async {
    if (_vendorId == null) return;
    _subscription?.cancel();
    _channel?.sink.close();
    try {
      final channel = WebSocketChannel.connect(await api.vendorSocketUrl(_vendorId!));
      _channel = channel;
      _subscription = channel.stream.listen(
        (event) => _apply(Order.fromJson(jsonDecode(event as String) as Map<String, dynamic>)),
        onDone: _scheduleReconnect,
        onError: (_) => _scheduleReconnect(),
      );
    } catch (_) {
      _scheduleReconnect();
    }
  }

  /// Refetch on every reconnect so anything missed while the socket was down
  /// is picked up rather than silently lost.
  void _scheduleReconnect() {
    _reconnectTimer?.cancel();
    _reconnectTimer = Timer(const Duration(seconds: 3), () async {
      await load();
      await _connect();
    });
  }

  void _apply(Order incoming) {
    final index = orders.indexWhere((o) => o.id == incoming.id);
    if (index == -1) {
      orders = [incoming, ...orders];
    } else {
      orders = [...orders]..[index] = incoming;
    }
    notifyListeners();
  }

  Future<void> updateStatus(Order order, OrderStatus status) async {
    final updated = await api.updateOrderStatus(order.id, status);
    _apply(updated);
  }

  @override
  void dispose() {
    _reconnectTimer?.cancel();
    _subscription?.cancel();
    _channel?.sink.close();
    super.dispose();
  }
}
