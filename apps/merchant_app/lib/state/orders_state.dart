import 'dart:async';
import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:hb_shared/hb_shared.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

import '../services/new_order_alert.dart';

/// The vendor's order queue. Seeded by a fetch, then kept current by the
/// vendor WebSocket so new orders and status changes land without polling.
class OrdersState extends ChangeNotifier {
  final ApiClient api;

  OrdersState(this.api);

  /// The chime. Owned here because its lifetime is the queue's: it starts when
  /// an order lands and has to stop when this is torn down.
  final NewOrderAlert alert = NewOrderAlert();

  List<Order> orders = [];
  bool loading = true;
  Object? error;

  /// Orders that have arrived and not yet been looked at.
  ///
  /// A list rather than a flag because two can land during one rush, and the
  /// merchant should be told about the second after dismissing the first rather
  /// than finding it silently in the queue.
  final List<Order> pendingAlerts = [];

  /// Whether the first load has finished.
  ///
  /// The guard that stops this screaming at the wrong time. `load()` replaces
  /// the whole list without going through `_apply`, and `_scheduleReconnect`
  /// calls it every three seconds while the socket is down - so without this,
  /// a merchant with bad wifi would be alerted about their entire queue, over
  /// and over.
  bool _loadedOnce = false;

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
      _loadedOnce = true;
    } catch (e) {
      error = e;
    } finally {
      loading = false;
      notifyListeners();
    }
  }

  /// Re-read the queue without letting a failure reach the screen.
  ///
  /// For the QR sheet, where the socket is the real path and this is only
  /// insurance against a dropped one. A stall owner holding a phone out to a
  /// customer must not get an error banner because the campus wifi blinked.
  Future<void> reloadQuietly() async {
    try {
      orders = await api.vendorOrders();
      notifyListeners();
    } catch (_) {
      // Deliberately silent: the next tick, or the socket, will catch up.
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

  /// The socket's funnel, reachable from a test.
  ///
  /// Exposed because OrdersState has no socket seam - start() connects for real
  /// - and the alert guards are the part worth pinning, not the WebSocket.
  @visibleForTesting
  void applyForTest(Order incoming) => _apply(incoming);

  void _apply(Order incoming) {
    final index = orders.indexWhere((o) => o.id == incoming.id);
    if (index == -1) {
      orders = [incoming, ...orders];
      _maybeAlert(incoming);
    } else {
      orders = [...orders]..[index] = incoming;
    }
    notifyListeners();
  }

  /// Raise the alarm, if this is genuinely a new order somebody should see.
  ///
  /// Three things have to be true, and each of them has bitten a version of
  /// this feature somewhere:
  ///
  ///  * the first load has finished, or a reconnect re-announces the whole
  ///    queue every three seconds;
  ///  * the order is `placed`, so the stall is not alerted about something it
  ///    has already accepted or about an order arriving mid-flight from
  ///    another device;
  ///  * nothing is already ringing for it, since `_apply` also runs for the
  ///    merchant's own status changes.
  void _maybeAlert(Order order) {
    if (!_loadedOnce) return;
    if (order.status != OrderStatus.placed) return;
    if (pendingAlerts.any((o) => o.id == order.id)) return;
    pendingAlerts.add(order);
    unawaited(alert.start());
  }

  /// Called when the merchant has seen it - by accepting, or by dismissing.
  Future<void> acknowledge(Order order) async {
    pendingAlerts.removeWhere((o) => o.id == order.id);
    if (pendingAlerts.isEmpty) await alert.stop();
    notifyListeners();
  }

  /// Moves an order along, optionally saying how long the kitchen needs.
  ///
  /// [prepMinutes] is only read by the server when accepting. Omitting it keeps
  /// whatever the menu's own times worked out at placement, which is also what
  /// the accept dialog pre-fills - so accepting the suggestion and accepting
  /// without thinking about it are the same request.
  Future<void> updateStatus(Order order, OrderStatus status, {int? prepMinutes}) async {
    final updated = await api.updateOrderStatus(order.id, status, prepMinutes: prepMinutes);
    _apply(updated);
  }

  /// The owner took cash at the door on their own round.
  ///
  /// Only reachable on a self-delivery order; the server refuses it otherwise,
  /// because an order a rider is carrying is the rider's to collect for.
  Future<void> collectCash(Order order) async {
    final updated = await api.collectCashAtDoor(order.id);
    _apply(updated);
  }

  /// A single-use QR for exactly this order's total.
  ///
  /// Nothing is applied here on purpose: a minted QR does not mean anybody has
  /// paid. The order flips to paid when Razorpay says so through
  /// qr_code.credited, which arrives on the same socket as every other change.
  Future<UpiQr> upiQr(Order order) => api.stallUpiQr(order.id);

  @override
  void dispose() {
    _reconnectTimer?.cancel();
    _subscription?.cancel();
    _channel?.sink.close();
    // Or the chime outlives the screen that raised it and plays over whatever
    // the merchant opened next.
    unawaited(alert.stop());
    super.dispose();
  }
}
