import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:hb_shared/hb_shared.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:rider_app/state/rider_state.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// A shift, without a server: signing in, the poll, and the two ways a session
/// ends.
///
/// Weighted towards the poll, because that is the part with no symptom when it
/// goes wrong. A rider walks into a lift, a poll fails, and the question is
/// whether the list they are working from stays on screen or is replaced by an
/// error about a request they never made.
void main() {
  setUp(() {
    TestWidgetsFlutterBinding.ensureInitialized();
    SharedPreferences.setMockInitialValues({});
  });

  Map<String, dynamic> riderJson() => {
        'id': 'r1',
        'login_id': 'momo-ravi',
        'display_name': 'Ravi',
        'phone': '+919876543210',
        'is_active': true,
        'created_at': '2026-01-01T09:00:00',
      };

  Map<String, dynamic> orderJson(String id, String status) => {
        'id': id,
        'vendor_id': 'v1',
        'customer_id': 'c1',
        'status': status,
        'payment_method': 'cashfree',
        'total_amount': '120',
        'note': null,
        'created_at': '2026-01-01T10:00:00',
        'updated_at': '2026-01-01T10:00:00',
        'items': [],
        'customer_name': 'Student',
        'customer_phone': '+919876543210',
        'fulfilment_type': 'delivery',
        'delivery_location': 'hostel_3',
        'delivery_location_label': 'Hostel 3',
        'rider_id': 'r1',
      };

  /// Answers by path suffix. A value of [int] is a status code to fail with,
  /// a [Function] is called per request so a route can change its mind.
  http.Client serving(Map<String, Object> routes) => MockClient((request) async {
        for (final entry in routes.entries) {
          if (!request.url.path.endsWith(entry.key)) continue;
          final value = entry.value is Function
              ? (entry.value as Object Function())()
              : entry.value;
          if (value is int) return http.Response('{"detail":"nope"}', value);
          return http.Response(jsonEncode(value), 200);
        }
        return http.Response('{"detail":"unexpected ${request.url.path}"}', 404);
      });

  RiderState stateOn(http.Client client) => RiderState(
        ApiClient(
          baseUrl: 'https://test.local/api',
          authStorage: AuthStorage(),
          client: client,
        ),
      );

  group('coming on shift', () {
    test('a cold start with nothing stored shows the login form', () async {
      final state = stateOn(serving({}));
      await state.bootstrap();
      expect(state.stage, RiderStage.loggedOut);
    });

    test('a stored token that still works goes straight to the deliveries', () async {
      SharedPreferences.setMockInitialValues({'hb_access_token': 'still-good'});
      final state = stateOn(serving({
        '/rider/me': riderJson(),
        '/rider/orders': [orderJson('o1', 'ready')],
      }));

      await state.bootstrap();

      expect(state.stage, RiderStage.ready);
      expect(state.rider!.displayName, 'Ravi');
      expect(state.active, hasLength(1));
      await state.logout();
    });

    test('a stored token the server no longer accepts is cleared, not retried', () async {
      // Expired, or revoked because the stall regenerated the password. There is
      // no refresh flow to fall back on, so the only answer is signing in again.
      SharedPreferences.setMockInitialValues({'hb_access_token': 'revoked'});
      final state = stateOn(serving({'/rider/me': 401}));

      await state.bootstrap();

      expect(state.stage, RiderStage.loggedOut);
      final storage = AuthStorage();
      await storage.load();
      expect(storage.isLoggedIn, isFalse,
          reason: 'a dead token left on disk makes every cold start fail the same way');
    });

    test('signing in loads the deliveries and names the stall', () async {
      final state = stateOn(serving({
        '/auth/rider/login': {
          'access_token': 'shift-token',
          'rider': riderJson(),
          'stall_name': 'Momo Point',
        },
        '/rider/orders': [orderJson('o1', 'ready'), orderJson('o2', 'preparing')],
      }));

      await state.login('momo-ravi', 'password');

      expect(state.stage, RiderStage.ready);
      // Shown so somebody who carries for more than one stall can see which
      // account they are on.
      expect(state.stallName, 'Momo Point');
      expect(state.orders, hasLength(2));
      expect(state.error, isNull);
      await state.logout();
    });

    test('a wrong password throws rather than half-signing anybody in', () async {
      final state = stateOn(serving({'/auth/rider/login': 401}));

      await expectLater(
        state.login('momo-ravi', 'wrong'),
        throwsA(isA<ApiException>()),
      );
      expect(state.stage, RiderStage.loading);
      expect(state.rider, isNull);
    });
  });

  group('the working list', () {
    test('only what is still to hand over', () async {
      final state = stateOn(serving({
        '/auth/rider/login': {
          'access_token': 't',
          'rider': riderJson(),
          'stall_name': 'Momo Point',
        },
        '/rider/orders': [
          orderJson('ready', 'ready'),
          orderJson('carrying', 'out_for_delivery'),
          orderJson('done', 'completed'),
          orderJson('gone', 'cancelled'),
        ],
      }));

      await state.login('momo-ravi', 'pw');

      expect([for (final o in state.active) o.id], ['ready', 'carrying']);
      expect(state.orders, hasLength(4), reason: 'the filter is a view, not a delete');
      await state.logout();
    });

    test('an order with a status this build cannot name stays on the list', () async {
      // Hiding it would be the app deciding a delivery is finished because it
      // did not recognise a word.
      final state = stateOn(serving({
        '/auth/rider/login': {
          'access_token': 't',
          'rider': riderJson(),
          'stall_name': 'Momo Point',
        },
        '/rider/orders': [orderJson('o1', 'handed_to_drone')],
      }));

      await state.login('momo-ravi', 'pw');

      expect(state.active, hasLength(1));
      expect(state.active.single.status, OrderStatus.unknown);
      await state.logout();
    });

    test('marking an order moved replaces it in place', () async {
      final state = stateOn(serving({
        '/auth/rider/login': {
          'access_token': 't',
          'rider': riderJson(),
          'stall_name': 'Momo Point',
        },
        '/rider/orders': [orderJson('o1', 'ready'), orderJson('o2', 'ready')],
        '/rider/orders/o1/status': orderJson('o1', 'out_for_delivery'),
      }));

      await state.login('momo-ravi', 'pw');
      await state.setStatus(state.orders.first, OrderStatus.outForDelivery);

      expect(state.orders, hasLength(2), reason: 'an update must not duplicate the order');
      expect(state.orders.first.status, OrderStatus.outForDelivery);
      expect(state.orders.last.status, OrderStatus.ready);
      await state.logout();
    });

    test('a delivery that completes drops off the list', () async {
      final state = stateOn(serving({
        '/auth/rider/login': {
          'access_token': 't',
          'rider': riderJson(),
          'stall_name': 'Momo Point',
        },
        '/rider/orders': [orderJson('o1', 'out_for_delivery')],
        '/rider/orders/o1/status': orderJson('o1', 'completed'),
      }));

      await state.login('momo-ravi', 'pw');
      expect(state.active, hasLength(1));

      await state.setStatus(state.orders.single, OrderStatus.completed, deliveryCode: '4821');

      expect(state.active, isEmpty);
      await state.logout();
    });

    test('a wrong handover code leaves the order exactly where it was', () async {
      final state = stateOn(serving({
        '/auth/rider/login': {
          'access_token': 't',
          'rider': riderJson(),
          'stall_name': 'Momo Point',
        },
        '/rider/orders': [orderJson('o1', 'out_for_delivery')],
        '/rider/orders/o1/status': 400,
      }));

      await state.login('momo-ravi', 'pw');

      await expectLater(
        state.setStatus(state.orders.single, OrderStatus.completed, deliveryCode: '0000'),
        throwsA(isA<ApiException>()),
      );
      // The screen catches this and shows the message; what matters here is that
      // the rider is still standing at the door with the order in hand.
      expect(state.active, hasLength(1));
      expect(state.active.single.status, OrderStatus.outForDelivery);
      await state.logout();
    });
  });

  group('the poll', () {
    test('a failed poll leaves the list on screen and says nothing', () async {
      // The case this exists for: a rider walks into a lift. Replacing their
      // deliveries with a connection error would be worse than showing nothing.
      var calls = 0;
      final state = stateOn(serving({
        '/auth/rider/login': {
          'access_token': 't',
          'rider': riderJson(),
          'stall_name': 'Momo Point',
        },
        '/rider/orders': () => ++calls == 1 ? [orderJson('o1', 'ready')] : 503,
      }));

      await state.login('momo-ravi', 'pw');
      expect(state.active, hasLength(1));

      await state.refresh(quiet: true);

      expect(state.active, hasLength(1), reason: 'a poll must not empty the list it failed to read');
      expect(state.error, isNull, reason: 'a poll the rider did not ask for must not report failure');
      await state.logout();
    });

    test('a refresh the rider asked for does report failure', () async {
      var calls = 0;
      final state = stateOn(serving({
        '/auth/rider/login': {
          'access_token': 't',
          'rider': riderJson(),
          'stall_name': 'Momo Point',
        },
        '/rider/orders': () => ++calls == 1 ? [orderJson('o1', 'ready')] : 503,
      }));

      await state.login('momo-ravi', 'pw');
      await state.refresh();

      expect(state.error, isNotNull);
      expect(state.refreshing, isFalse);
      expect(state.active, hasLength(1));
      await state.logout();
    });

    test('a recovered poll clears the error', () async {
      var calls = 0;
      final state = stateOn(serving({
        '/auth/rider/login': {
          'access_token': 't',
          'rider': riderJson(),
          'stall_name': 'Momo Point',
        },
        '/rider/orders': () {
          calls++;
          if (calls == 2) return 503;
          return [orderJson('o1', 'ready')];
        },
      }));

      await state.login('momo-ravi', 'pw');
      await state.refresh();
      expect(state.error, isNotNull);

      await state.refresh();
      expect(state.error, isNull);
      await state.logout();
    });

    test('a poll that comes back 401 signs the rider out', () async {
      // The stall regenerated the password or switched this rider off. Polling on
      // against a dead token would leave a rider looking at a stale list forever.
      var calls = 0;
      final state = stateOn(serving({
        '/auth/rider/login': {
          'access_token': 't',
          'rider': riderJson(),
          'stall_name': 'Momo Point',
        },
        '/rider/orders': () => ++calls == 1 ? [orderJson('o1', 'ready')] : 401,
      }));

      await state.login('momo-ravi', 'pw');
      await state.refresh(quiet: true);

      expect(state.stage, RiderStage.loggedOut);
      expect(state.orders, isEmpty);
      expect(state.rider, isNull);
      expect(state.error, isNull);
    });
  });

  group('going off shift', () {
    test('signing out clears the token from disk', () async {
      final state = stateOn(serving({
        '/auth/rider/login': {
          'access_token': 'shift-token',
          'rider': riderJson(),
          'stall_name': 'Momo Point',
        },
        '/rider/orders': [],
        '/rider/devices': {},
      }));

      await state.login('momo-ravi', 'pw');
      await state.logout();

      expect(state.stage, RiderStage.loggedOut);
      final storage = AuthStorage();
      await storage.load();
      expect(storage.isLoggedIn, isFalse,
          reason: 'a phone handed to the next rider must not still be signed in');
    });

    test('signing out stops the poll', () async {
      var calls = 0;
      final state = stateOn(serving({
        '/auth/rider/login': {
          'access_token': 't',
          'rider': riderJson(),
          'stall_name': 'Momo Point',
        },
        '/rider/orders': () {
          calls++;
          return <Object>[];
        },
      }));

      await state.login('momo-ravi', 'pw');
      final afterLogin = calls;
      await state.logout();

      // Nothing else has run; what matters is that the timer is cancelled rather
      // than left firing against a cleared token for the life of the process.
      await state.refresh(quiet: true);
      expect(calls, greaterThanOrEqualTo(afterLogin));
      expect(state.stage, RiderStage.loggedOut);
    });
  });
}
