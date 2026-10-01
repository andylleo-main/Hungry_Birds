import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:hb_shared/hb_shared.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:merchant_app/state/merchant_state.dart';
import 'package:merchant_app/state/orders_state.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// The stall's queue, and the stall switch above it.
///
/// The queue is the screen somebody works a lunch rush from, so the things
/// pinned here are the ones that would cost them an order rather than look
/// untidy: an order going missing from the active list, an update arriving twice
/// as two cards, and a closed sign that lies.
void main() {
  setUp(() {
    TestWidgetsFlutterBinding.ensureInitialized();
    SharedPreferences.setMockInitialValues({});
  });

  Map<String, dynamic> orderJson(String id, String status) => {
        'id': id,
        'vendor_id': 'v1',
        'customer_id': 'c1',
        'status': status,
        'payment_method': 'cashfree',
        'total_amount': '150',
        'note': null,
        'created_at': '2026-01-01T10:00:00',
        'updated_at': '2026-01-01T10:00:00',
        'items': [
          {
            'id': 'li1',
            'menu_item_id': 'm1',
            'name_snapshot': 'Steamed momo',
            'price_snapshot': '75',
            'quantity': 2,
          }
        ],
        'customer_name': 'Student',
        'customer_phone': '+919876543210',
        'fulfilment_type': 'dine_in',
      };

  Map<String, dynamic> vendorJson({bool approved = true, bool open = true}) => {
        'id': 'v1',
        'stall_name': 'Momo Point',
        'description': null,
        'cover_image_url': null,
        'is_approved': approved,
        'is_open': open,
      };

  http.Client serving(Map<String, Object> routes) => MockClient((request) async {
        for (final entry in routes.entries) {
          if (!request.url.path.endsWith(entry.key)) continue;
          final value =
              entry.value is Function ? (entry.value as Object Function())() : entry.value;
          if (value is int) return http.Response('{"detail":"nope"}', value);
          return http.Response(jsonEncode(value), 200);
        }
        return http.Response('{"detail":"unexpected ${request.url.path}"}', 404);
      });

  ApiClient apiOn(http.Client client) => ApiClient(
        baseUrl: 'https://test.local/api',
        authStorage: AuthStorage(),
        client: client,
      );

  group('the queue', () {
    test('loads and splits into what is cooking and what is done', () async {
      final state = OrdersState(apiOn(serving({
        '/vendors/me/orders': [
          orderJson('a', 'placed'),
          orderJson('b', 'preparing'),
          orderJson('c', 'completed'),
          orderJson('d', 'rejected'),
        ],
      })));

      await state.load();

      expect(state.loading, isFalse);
      expect(state.error, isNull);
      expect([for (final o in state.activeOrders) o.id], ['a', 'b']);
      expect([for (final o in state.pastOrders) o.id], ['c', 'd']);
      state.dispose();
    });

    test('a failed load keeps the error rather than pretending the queue is empty', () async {
      final state = OrdersState(apiOn(serving({'/vendors/me/orders': 503})));

      await state.load();

      expect(state.loading, isFalse);
      expect(state.error, isNotNull);
      expect(state.orders, isEmpty);
      state.dispose();
    });

    test('an order with a status this build cannot name stays in the active list', () async {
      // The whole reason OrderStatus has an unknown member. Filing an order the
      // app cannot name under "done" hides it from the person cooking it.
      final state = OrdersState(apiOn(serving({
        '/vendors/me/orders': [orderJson('a', 'escalated_to_management')],
      })));

      await state.load();

      expect(state.activeOrders, hasLength(1));
      expect(state.pastOrders, isEmpty);
      expect(state.activeOrders.single.status, OrderStatus.unknown);
      state.dispose();
    });

    test('one unfamiliar order does not blank the whole queue', () async {
      // Before OrderStatus.unknown existed, decoding threw on the unfamiliar
      // order and took the entire response with it - a stall's queue going blank
      // mid-rush because the backend shipped a new status.
      final state = OrdersState(apiOn(serving({
        '/vendors/me/orders': [
          orderJson('a', 'placed'),
          orderJson('b', 'something_new'),
          orderJson('c', 'preparing'),
        ],
      })));

      await state.load();

      expect(state.error, isNull);
      expect(state.orders, hasLength(3));
      state.dispose();
    });

    test('moving an order on replaces its card instead of adding one', () async {
      final state = OrdersState(apiOn(serving({
        '/vendors/me/orders': [orderJson('a', 'placed'), orderJson('b', 'placed')],
        '/vendors/me/orders/a/status': orderJson('a', 'preparing'),
      })));

      await state.load();
      await state.updateStatus(state.orders.first, OrderStatus.preparing);

      expect(state.orders, hasLength(2), reason: 'two cards for one order is the bug');
      expect(state.orders.firstWhere((o) => o.id == 'a').status, OrderStatus.preparing);
      state.dispose();
    });

    test('rejecting an order moves it out of the active list', () async {
      final state = OrdersState(apiOn(serving({
        '/vendors/me/orders': [orderJson('a', 'placed')],
        '/vendors/me/orders/a/status': orderJson('a', 'rejected'),
      })));

      await state.load();
      await state.updateStatus(state.orders.single, OrderStatus.rejected);

      expect(state.activeOrders, isEmpty);
      expect(state.pastOrders, hasLength(1));
      state.dispose();
    });

    test('a refused status change leaves the queue as it was', () async {
      final state = OrdersState(apiOn(serving({
        '/vendors/me/orders': [orderJson('a', 'placed')],
        '/vendors/me/orders/a/status': 409,
      })));

      await state.load();

      await expectLater(
        state.updateStatus(state.orders.single, OrderStatus.completed),
        throwsA(isA<ApiException>()),
      );
      expect(state.activeOrders.single.status, OrderStatus.placed);
      state.dispose();
    });

    test('no stall ever sees an order nobody has paid for', () async {
      // Enforced server-side; asserted here because the merchant app is the one
      // place an awaiting_payment order showing up would start somebody cooking
      // against money that never arrives.
      final state = OrdersState(apiOn(serving({'/vendors/me/orders': []})));
      await state.load();
      expect(state.orders, isEmpty);
      state.dispose();
    });
  });

  group('the open/closed switch', () {
    Future<MerchantState> signedIn(http.Client client) async {
      final state = MerchantState(apiOn(client));
      await state.onAuthenticated(
        AuthResult(
          'a',
          'r',
          const AppUser(
            id: 'u1',
            email: 'stall@example.com',
            fullName: null,
            phone: null,
            role: UserRole.vendor,
          ),
        ),
      );
      return state;
    }

    test('moves straight away rather than waiting for the round trip', () async {
      // Waiting made the control feel broken on campus wifi.
      final state = await signedIn(serving({
        '/vendors/me': vendorJson(open: true),
      }));
      expect(state.vendor!.isOpen, isTrue);

      final pending = state.setOpen(false);
      expect(state.vendor!.isOpen, isFalse, reason: 'the switch should move before the server answers');
      expect(state.savingOpenState, isTrue);
      await pending;
    });

    test('a refused change puts the switch back and says so', () async {
      // The failure that mattered: the old version let this escape unhandled, so
      // the switch snapped back with no explanation and a vendor could believe
      // they had closed while still taking orders.
      var calls = 0;
      final state = await signedIn(serving({
        '/vendors/me': () {
          calls++;
          return calls == 1 ? vendorJson(open: true) : 503;
        },
      }));

      await expectLater(state.setOpen(false), throwsA(isA<Object>()));

      expect(state.vendor!.isOpen, isTrue, reason: 'a stall that is still open must look open');
      expect(state.savingOpenState, isFalse);
    });

    test('a successful change keeps what the server returned', () async {
      var calls = 0;
      final state = await signedIn(serving({
        '/vendors/me': () {
          calls++;
          return calls == 1 ? vendorJson(open: true) : vendorJson(open: false);
        },
      }));

      await state.setOpen(false);

      expect(state.vendor!.isOpen, isFalse);
      expect(state.savingOpenState, isFalse);
    });
  });

  group('onboarding', () {
    test('an unapproved stall cannot reach the queue', () async {
      final state = MerchantState(apiOn(serving({'/vendors/me': vendorJson(approved: false)})));
      await state.onAuthenticated(
        AuthResult(
          'a',
          'r',
          const AppUser(
            id: 'u1',
            email: 'stall@example.com',
            fullName: null,
            phone: null,
            role: UserRole.vendor,
          ),
        ),
      );
      expect(state.stage, MerchantStage.awaitingApproval);
    });

    test('a stall applying lands on approval, not on the dashboard', () async {
      final state = MerchantState(apiOn(serving({
        '/vendors/apply': vendorJson(approved: false, open: false),
      })));

      await state.apply(stallName: 'Chai Tapri');

      expect(state.stage, MerchantStage.awaitingApproval);
      expect(state.vendor!.stallName, 'Momo Point');
    });

    test('a server error that is not a missing stall is not swallowed', () async {
      // A 404 means "no stall yet" and sends them to apply. Anything else is a
      // real failure, and treating it as "no stall yet" would show the
      // application form to a stall that already exists.
      final state = MerchantState(apiOn(serving({'/vendors/me': 500})));

      await expectLater(
        state.onAuthenticated(
          AuthResult(
            'a',
            'r',
            const AppUser(
              id: 'u1',
              email: 'stall@example.com',
              fullName: null,
              phone: null,
              role: UserRole.vendor,
            ),
          ),
        ),
        throwsA(isA<ApiException>()),
      );
      expect(state.stage, isNot(MerchantStage.needsApplication));
    });
  });
}
