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
  /// The guard that stops this screaming at the wrong time: the queue a stall
  /// already has when it opens the app is not news.
  bool _loadedOnce = false;

  /// Every order id this screen has already seen, however it arrived.
  ///
  /// This is what makes the alarm work at all. It used to live implicitly in
  /// `orders` and be checked only inside `_apply`, which is the socket's path -
  /// but `load()` replaces the whole list without going through `_apply`, and
  /// `_scheduleReconnect` calls `load()` every three seconds while the socket
  /// is down. So a new order arriving during any socket trouble was absorbed
  /// silently, and by the time the socket came back and re-announced it,
  /// `_apply` found it already in the list and said nothing.
  ///
  /// On a phone whose socket never connected at all - a flaky campus wifi, a
  /// ticket that would not fetch - that meant the alarm never rang once, while
  /// the queue itself looked perfectly healthy because the three-second reload
  /// was quietly doing all the work.
  ///
  /// Keyed on id rather than on list membership because an order leaves
  /// `orders` eventually and must not ring again if it comes back.
  final Set<String> _seen = {};

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
      final fetched = await api.vendorOrders();
      orders = fetched;
      error = null;
      // Through the same funnel as the socket. A new order is a new order
      // whichever way it reached the phone.
      _noticeArrivals(fetched, fromSnapshot: true);
    } catch (e) {
      error = e;
    } finally {
      loading = false;
      notifyListeners();
    }
  }

  /// Ring for anything here that has not been seen before.
  ///
  /// [fromSnapshot] says whether this is the whole queue as the server has it
  /// (a load) or a single thing that just happened (a socket frame). The
  /// difference decides whether silence is the right answer, and getting it
  /// wrong is how a cash order went unheard:
  ///
  ///  * A **snapshot** can legitimately be full of orders nobody should be
  ///    shouted at about - a stall opening the app to six waiting orders wants
  ///    to see them, not hear six alarms. So the first successful snapshot only
  ///    records, and establishes the baseline.
  ///  * A **socket frame** is never a baseline. Redis pub/sub has no replay, so
  ///    anything arriving that way is by definition something that just
  ///    happened, and it rings whether or not a baseline was ever established.
  ///
  /// That second rule is the fix. `_loadedOnce` used to be set here by whichever
  /// path arrived first, so if the opening `load()` threw - campus wifi at app
  /// open - the *next order to arrive* was mistaken for part of the queue that
  /// was already there: recorded silently, with the baseline flipped true behind
  /// it. And because `_seen` is keyed on id, that order could never ring
  /// afterwards either. It hit cash orders hardest, which reach the stall the
  /// instant they are placed - exactly when the app has just been opened.
  void _noticeArrivals(List<Order> incoming, {required bool fromSnapshot}) {
    // A snapshot stays quiet until a baseline exists. An event never does.
    final announce = !fromSnapshot || _loadedOnce;
    for (final order in incoming) {
      // Set.add answers whether it was actually new, which is exactly the
      // question, and records it in the same step.
      final isNew = _seen.add(order.id);
      if (announce && isNew) _maybeAlert(order);
    }
    // Only a full fetch can establish the baseline. A single socket frame says
    // nothing about what else is in the queue.
    if (fromSnapshot) _loadedOnce = true;
  }

  /// Re-read the queue without letting a failure reach the screen.
  ///
  /// For the QR sheet, where the socket is the real path and this is only
  /// insurance against a dropped one. A stall owner holding a phone out to a
  /// customer must not get an error banner because the campus wifi blinked.
  Future<void> reloadQuietly() async {
    try {
      final fetched = await api.vendorOrders();
      orders = fetched;
      // Still announced. An order landing while the owner is holding a QR out
      // to a customer is the one they most need to hear about.
      _noticeArrivals(fetched, fromSnapshot: true);
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
      _noticeArrivals([incoming], fromSnapshot: false);
    } else {
      orders = [...orders]..[index] = incoming;
    }
    notifyListeners();
  }

  /// Raise the alarm for an order that has just arrived.
  ///
  /// Whether it is new at all is `_noticeArrivals`'s question, not this one.
  /// What is left here are the two conditions about the order itself:
  ///
  ///  * it is `placed`, so the stall is not alerted about something it has
  ///    already accepted, or about an order arriving mid-flight from another
  ///    device;
  ///  * nothing is already ringing for it, since an order can be announced by
  ///    the socket and a reload within the same second.
  void _maybeAlert(Order order) {
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
