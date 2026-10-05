import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:hb_shared/hb_shared.dart';

import '../services/push.dart';

enum RiderStage { loading, loggedOut, ready }

/// The signed-in rider and the orders they are carrying.
///
/// Polls rather than holding a WebSocket. A rider has one or two orders at a
/// time, so re-reading a small list every few seconds costs less than giving the
/// rider app its own ticket-and-socket path - and a poll cannot wedge in a way
/// that silently stops delivering updates, which is the failure mode that
/// matters when somebody is waiting on food.
class RiderState extends ChangeNotifier {
  RiderState(this.api) : push = PushService(api);

  final ApiClient api;

  /// Assignment notifications. Owned here because its lifetime is the signed-in
  /// rider's: it starts once there is a rider session to attach a token to, and
  /// stops before sign-out while that session's token still works.
  final PushService push;

  static const _pollInterval = Duration(seconds: 12);

  RiderStage stage = RiderStage.loading;
  Rider? rider;
  String stallName = '';
  List<Order> orders = const [];
  String? error;
  bool refreshing = false;

  Timer? _poll;

  @override
  void dispose() {
    _poll?.cancel();
    super.dispose();
  }

  Future<void> bootstrap() async {
    await api.authStorage.load();
    if (!api.authStorage.isLoggedIn) {
      _set(RiderStage.loggedOut);
      return;
    }
    try {
      rider = await api.riderMe();
      _set(RiderStage.ready);
      await refresh();
      _startPolling();
      _startPush();
    } catch (_) {
      // Any failure to identify the stored token - expired, or revoked because
      // the stall regenerated the password - means signing in again. There is no
      // refresh flow to try.
      await api.authStorage.clear();
      _set(RiderStage.loggedOut);
    }
  }

  Future<void> login(String loginId, String password) async {
    final session = await api.riderLogin(loginId, password);
    rider = session.rider;
    stallName = session.stallName;
    _set(RiderStage.ready);
    await refresh();
    _startPolling();
    _startPush();
  }

  /// Deliberately not awaited. Asking Firebase for a token can take a moment on
  /// a cold start, and the delivery list should not wait on it. Failures are
  /// swallowed inside start().
  void _startPush() => unawaited(push.start());

  void _startPolling() {
    _poll?.cancel();
    _poll = Timer.periodic(_pollInterval, (_) => refresh(quiet: true));
  }

  /// Re-reads the rider's orders.
  ///
  /// [quiet] is for the timer: a poll must not flash a spinner over a list the
  /// rider is reading, and a poll that fails because they walked into a lift
  /// must not replace the orders on screen with an error. Only a refresh the
  /// rider asked for reports failure.
  Future<void> refresh({bool quiet = false}) async {
    if (!quiet) {
      refreshing = true;
      notifyListeners();
    }
    try {
      orders = await api.riderOrders();
      error = null;
    } on ApiException catch (e) {
      if (e.statusCode == 401) {
        // The stall regenerated the password or switched this rider off.
        await logout();
        return;
      }
      if (!quiet) error = e.message;
    } catch (_) {
      if (!quiet) error = "Couldn't reach the server. Check your connection.";
    } finally {
      refreshing = false;
      notifyListeners();
    }
  }

  /// Marks an order picked up or delivered. Nothing else is accepted server-side.
  ///
  /// [deliveryCode] is what the customer reads out, and the server refuses to
  /// complete a delivery without it.
  Future<void> setStatus(Order order, OrderStatus status, {String? deliveryCode}) async {
    final updated = await api.riderUpdateOrderStatus(
      order.id,
      status,
      deliveryCode: deliveryCode,
    );
    orders = [
      for (final o in orders)
        if (o.id == updated.id) updated else o,
    ];
    notifyListeners();
  }

  /// Records cash taken at the door, and swaps the order in place.
  ///
  /// Separate from setStatus because collecting is not a status change: the food
  /// has not moved, the money has. The server refuses to complete a delivery
  /// that still owes money, so this is the step that unlocks "Delivered".
  Future<void> collectCash(Order order) async {
    final updated = await api.riderCollectCash(order.id);
    _replace(updated);
  }

  /// Mints a single-use QR for this order's total.
  ///
  /// Nothing is marked paid here. Razorpay tells the server when the money
  /// lands, and the order arrives back through the ordinary poll - which is the
  /// point of routing it through a gateway rather than trusting the screen.
  Future<UpiQr> upiQr(Order order) => api.riderUpiQr(order.id);

  void _replace(Order updated) {
    orders = [for (final o in orders) if (o.id == updated.id) updated else o];
    notifyListeners();
  }

  /// Orders still to hand over.
  List<Order> get active => [
        for (final o in orders)
          if (o.status.isActive) o,
      ];

  Future<void> logout() async {
    _poll?.cancel();
    _poll = null;
    // Before the token is cleared, while it still works - unregistering needs an
    // authenticated call, and a phone handed to the next rider on shift must stop
    // buzzing for deliveries that are no longer theirs. Called on the 401 path in
    // refresh() too, where the token is already dead; that fails harmlessly and
    // the server prunes the device when Firebase next reports it gone.
    await push.stop();
    await api.authStorage.clear();
    rider = null;
    orders = const [];
    error = null;
    _set(RiderStage.loggedOut);
  }

  void _set(RiderStage next) {
    stage = next;
    notifyListeners();
  }
}
