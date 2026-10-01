import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:hb_shared/hb_shared.dart';

enum RiderStage { loading, loggedOut, ready }

/// The signed-in rider and the orders they are carrying.
///
/// Polls rather than holding a WebSocket. A rider has one or two orders at a
/// time, so re-reading a small list every few seconds costs less than giving the
/// rider app its own ticket-and-socket path - and a poll cannot wedge in a way
/// that silently stops delivering updates, which is the failure mode that
/// matters when somebody is waiting on food.
class RiderState extends ChangeNotifier {
  RiderState(this.api);

  final ApiClient api;

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
  }

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
  Future<void> setStatus(Order order, OrderStatus status) async {
    final updated = await api.riderUpdateOrderStatus(order.id, status);
    orders = [
      for (final o in orders)
        if (o.id == updated.id) updated else o,
    ];
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
