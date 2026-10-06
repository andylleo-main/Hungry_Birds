import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:hb_shared/hb_shared.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:merchant_app/services/new_order_alert.dart';
import 'package:merchant_app/state/orders_state.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// When the queue raises the alarm, and - mostly - when it must not.
///
/// The guards exist because of specific ways this feature screams at the wrong
/// time: the queue a stall already has when it opens the app is not news,
/// `_apply` also runs for the merchant's own status changes, and an order that
/// is already accepted is not news either.
///
/// The opposite failure is the one that actually shipped, and it is pinned at
/// the bottom. Alerting used to happen only inside `_apply`, which is the
/// socket's path - but `load()` replaces the whole list without going through
/// it, and the reconnect loop calls `load()` every three seconds while the
/// socket is down. So an order arriving during socket trouble was absorbed in
/// silence, and on a phone whose socket never connected the alarm never rang
/// once, while the queue looked perfectly healthy because the reload was
/// quietly doing all the work.
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

  _arrivalsByAnyPath();
  _whenTheSoundFails();

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


/// The reason it never rang: arrivals that came in by any path but the socket.
void _arrivalsByAnyPath() {
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
        'payment_method': 'online',
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

  /// A queue the test can change between calls, as the server's would.
  List<Map<String, dynamic>> queue = [];

  http.Client serving() => MockClient((request) async {
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

  test('an order that appears on a reload rings, with no socket involved',
      () async {
    // This is the whole bug. The reconnect loop reloads every three seconds
    // while the socket is down, so on a phone that never connects this is the
    // only way an order ever arrives - and it used to arrive in silence.
    queue = [orderJson('a', 'placed')];
    final state = stateOn(serving());
    await state.load();
    expect(state.pendingAlerts, isEmpty, reason: 'the opening queue is not news');

    queue = [orderJson('a', 'placed'), orderJson('b', 'placed')];
    await state.load();

    expect(state.pendingAlerts.map((o) => o.id), ['b']);
    state.dispose();
  });

  test('reloading the same queue again does not ring again', () async {
    // The reconnect loop does this every three seconds. Ringing each time would
    // be worse than never ringing at all.
    queue = [orderJson('a', 'placed')];
    final state = stateOn(serving());
    await state.load();

    await state.load();
    await state.load();

    expect(state.pendingAlerts, isEmpty);
    state.dispose();
  });

  test('an order the socket announces after a reload does not ring twice',
      () async {
    // Both paths run for the same order within a second of each other when a
    // socket comes back up mid-rush.
    queue = [orderJson('a', 'placed')];
    final state = stateOn(serving());
    await state.load();

    queue = [orderJson('a', 'placed'), orderJson('b', 'placed')];
    await state.load();
    state.applyForTest(Order.fromJson(orderJson('b', 'placed')));

    expect(state.pendingAlerts.map((o) => o.id), ['b']);
    state.dispose();
  });

  test('an order that is already accepted when it first appears stays quiet',
      () async {
    // A second device accepted it while this one was offline. Arriving for the
    // first time is not the same as being new work.
    queue = [orderJson('a', 'placed')];
    final state = stateOn(serving());
    await state.load();

    queue = [orderJson('a', 'placed'), orderJson('b', 'accepted')];
    await state.load();

    expect(state.pendingAlerts, isEmpty);
    state.dispose();
  });

  test('an order that comes back after leaving the list does not ring again',
      () async {
    // Orders drop out of the queue as they finish. Keying on "have I seen this
    // id" rather than on list membership is what stops a reappearance ringing.
    queue = [orderJson('a', 'placed')];
    final state = stateOn(serving());
    await state.load();

    queue = [];
    await state.load();
    expect(state.orders, isEmpty);

    queue = [orderJson('a', 'placed')];
    await state.load();

    expect(state.pendingAlerts, isEmpty);
    state.dispose();
  });

  test('a quiet reload still announces, since the owner is holding a QR out',
      () async {
    queue = [orderJson('a', 'placed')];
    final state = stateOn(serving());
    await state.load();

    queue = [orderJson('a', 'placed'), orderJson('b', 'placed')];
    await state.reloadQuietly();

    expect(state.pendingAlerts.map((o) => o.id), ['b']);
    state.dispose();
  });
}

/// What the alarm does when the audio will not play.
///
/// The sound itself cannot be exercised here - there is no audio device - so
/// what is pinned is everything around it: that a failure is recorded rather
/// than swallowed, that the phone still buzzes, and that the self-test answers
/// in words instead of throwing. Those are the parts that were missing when
/// "the alarm doesn't ring" arrived with nothing to act on.
void _whenTheSoundFails() {
  setUp(() {
    TestWidgetsFlutterBinding.ensureInitialized();
    SharedPreferences.setMockInitialValues({});
  });

  test('a failure to play is recorded, not swallowed', () async {
    // No audio platform under the test binding, so both routes fail - which is
    // exactly the condition that used to produce silence and no explanation.
    final alert = NewOrderAlert();

    await alert.start();

    expect(alert.isRinging, isFalse);
    expect(alert.lastProblem, isNotNull);
    expect(alert.lastProblem, contains('volume'),
        reason: 'it should name the route it tried');
    alert.dispose();
  });

  test('the self-test answers in words rather than throwing', () async {
    final alert = NewOrderAlert();

    final result = await alert.selfTest();

    expect(result, isNotEmpty);
    expect(result, contains('buzzed'));
    alert.dispose();
  });

  test('stopping something that never started is harmless', () async {
    final alert = NewOrderAlert();
    await alert.stop();
    expect(alert.isRinging, isFalse);
    alert.dispose();
  });

  test('start is safe to call twice', () async {
    // _apply and a reload can both land on the same order within a second.
    final alert = NewOrderAlert();

    await Future.wait([alert.start(), alert.start()]);

    expect(alert.isRinging, isFalse, reason: 'no audio here either way');
    alert.dispose();
  });
}
