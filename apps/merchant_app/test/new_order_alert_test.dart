import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:hb_shared/hb_shared.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:merchant_app/state/orders_state.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// When the queue raises the alarm, and - mostly - when it must not.
///
/// All three guards exist because of a specific way this feature screams at the
/// wrong time. `load()` replaces the whole list without going through `_apply`,
/// and the reconnect loop calls it every three seconds while the socket is down,
/// so a merchant on bad wifi would be alerted about their entire queue over and
/// over. `_apply` also runs for the merchant's own status changes. And an order
/// that is already accepted is not news.
///
/// The audio itself is not exercised - there is no audio device here, and
/// NewOrderAlert swallows its own failures by design. What is pinned is the
/// decision to ring, which is the part with the logic in it.
void main() {
  setUp(() {
    TestWidgetsFlutterBinding.ensureInitialized();
    SharedPreferences.setMockInitialValues({});
  });

  Map<String, dynamic> orderJson(String id, String status) => {
        'id': id,
        'order_number': '000001-4821',
        'token_number': 7,
        'vendor_id': 'v1',
        'customer_id': 'c1',
        'status': status,
        'payment_method': 'cashfree',
        'payment_status': 'paid',
        'total_amount': '150',
        'note': null,
        'created_at': '2026-01-01T10:00:00',
        'updated_at': '2026-01-01T10:00:00',
        'items': [],
        'customer_name': 'Student',
        'customer_phone': '+919876543210',
        'fulfilment_type': 'dine_in',
      };

  http.Client serving(List<Map<String, dynamic>> queue) => MockClient((request) async {
        if (request.url.path.endsWith('/vendors/me/orders')) {
          return http.Response(jsonEncode(queue), 200);
        }
        return http.Response('{"detail":"unexpected ${request.url.path}"}', 404);
      });

  OrdersState stateOn(http.Client client) => OrdersState(
        ApiClient(
          baseUrl: 'https://test.local/api',
          authStorage: AuthStorage(),
          client: client,
        ),
      );

  Order order(String id, OrderStatus status) =>
      Order.fromJson(orderJson(id, status.wire));

  test('the first load does not announce the whole queue', () async {
    // The one that would make this unusable: a stall opening the app mid-service
    // would be alarmed about every order already on the counter.
    final state = stateOn(serving([orderJson('a', 'placed'), orderJson('b', 'placed')]));

    await state.load();

    expect(state.orders, hasLength(2));
    expect(state.pendingAlerts, isEmpty);
    state.dispose();
  });

  test('an order arriving after that does announce itself', () async {
    final state = stateOn(serving([]));
    await state.load();

    state.applyForTest(order('new', OrderStatus.placed));

    expect([for (final o in state.pendingAlerts) o.id], ['new']);
    state.dispose();
  });

  test('a reconnect refetch does not re-announce anything', () async {
    // _scheduleReconnect calls load() every three seconds while the socket is
    // down. Each of those would otherwise be a fresh alarm about orders the
    // merchant has already seen.
    final state = stateOn(serving([orderJson('a', 'placed')]));
    await state.load();
    await state.load();
    await state.load();

    expect(state.pendingAlerts, isEmpty);
    state.dispose();
  });

  test('an order that is already being cooked is not news', () async {
    final state = stateOn(serving([]));
    await state.load();

    state.applyForTest(order('a', OrderStatus.preparing));

    expect(state.pendingAlerts, isEmpty);
    state.dispose();
  });

  test('a status change on an order already in the queue is silent', () async {
    // _apply runs for the merchant's own PATCH too, so without the index check
    // accepting an order would set off the alarm for it.
    final state = stateOn(serving([orderJson('a', 'placed')]));
    await state.load();

    state.applyForTest(order('a', OrderStatus.accepted));

    expect(state.pendingAlerts, isEmpty);
    expect(state.orders.single.status, OrderStatus.accepted);
    state.dispose();
  });

  test('the same order twice only rings once', () async {
    final state = stateOn(serving([]));
    await state.load();

    state.applyForTest(order('a', OrderStatus.placed));
    state.applyForTest(order('a', OrderStatus.placed));

    expect(state.pendingAlerts, hasLength(1));
    state.dispose();
  });

  test('acknowledging clears it', () async {
    final state = stateOn(serving([]));
    await state.load();
    state.applyForTest(order('a', OrderStatus.placed));

    await state.acknowledge(state.pendingAlerts.first);

    expect(state.pendingAlerts, isEmpty);
    state.dispose();
  });

  test('two orders are acknowledged one at a time', () async {
    // Two can land in one rush, and the merchant should be told about the
    // second after dismissing the first rather than finding it in the queue.
    final state = stateOn(serving([]));
    await state.load();
    state.applyForTest(order('a', OrderStatus.placed));
    state.applyForTest(order('b', OrderStatus.placed));

    await state.acknowledge(state.pendingAlerts.first);

    expect([for (final o in state.pendingAlerts) o.id], ['b']);
    state.dispose();
  });
}
