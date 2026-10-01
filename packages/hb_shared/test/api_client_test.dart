import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:hb_shared/hb_shared.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// The transport, rather than any screen: who gets an Authorization header, what
/// happens on a 401, and what a rider's session is allowed to keep on disk.
///
/// These are the behaviours with no visible symptom when they break. A rider
/// whose stale refresh token survives a login does not see anything wrong until
/// their first 401, at which point the app tries a refresh flow that cannot work
/// and signs them out mid-shift.
void main() {
  setUp(() {
    TestWidgetsFlutterBinding.ensureInitialized();
    SharedPreferences.setMockInitialValues({});
  });

  /// Records every request, and answers each from [replies] in turn.
  (http.Client, List<http.Request>) recorder(List<http.Response> replies) {
    final seen = <http.Request>[];
    var i = 0;
    final client = MockClient((request) async {
      seen.add(request);
      return i < replies.length ? replies[i++] : http.Response('{}', 200);
    });
    return (client, seen);
  }

  http.Response ok(Object body) => http.Response(jsonEncode(body), 200);
  http.Response fail(int code, [String detail = 'nope']) =>
      http.Response(jsonEncode({'detail': detail}), code);

  ApiClient clientWith(http.Client transport, {AuthStorage? storage}) => ApiClient(
        baseUrl: 'https://test.local/api',
        authStorage: storage ?? AuthStorage(),
        client: transport,
      );

  Map<String, dynamic> riderJson() => {
        'id': 'r1',
        'login_id': 'momo-ravi',
        'display_name': 'Ravi',
        'phone': '+919876543210',
        'is_active': true,
        'created_at': '2026-01-01T09:00:00',
      };

  group('authorization', () {
    test('a signed-out client sends no bearer token', () async {
      final (transport, seen) = recorder([ok([])]);
      await clientWith(transport).riderOrders();
      expect(seen.single.headers.containsKey('Authorization'), isFalse);
    });

    test('a signed-in client sends one', () async {
      final storage = AuthStorage();
      await storage.saveTokens(accessToken: 'access-1', refreshToken: 'refresh-1');
      final (transport, seen) = recorder([ok([])]);

      await clientWith(transport, storage: storage).riderOrders();
      expect(seen.single.headers['Authorization'], 'Bearer access-1');
    });

    test('signing in does not send the token being asked for', () async {
      // The rider login route is the one call that must go out unauthenticated,
      // or a dead token from the previous shift would be attached to the request
      // that is meant to replace it.
      final storage = AuthStorage();
      await storage.saveTokens(accessToken: 'stale', refreshToken: 'stale-r');
      final (transport, seen) = recorder([
        ok({'access_token': 'fresh', 'rider': riderJson(), 'stall_name': 'Momo Point'}),
      ]);

      await clientWith(transport, storage: storage).riderLogin('momo-ravi', 'pw');
      expect(seen.single.headers.containsKey('Authorization'), isFalse);
    });
  });

  group('the silent refresh', () {
    test('a 401 is retried once with the new token', () async {
      final storage = AuthStorage();
      await storage.saveTokens(accessToken: 'old', refreshToken: 'refresh-1');
      final (transport, seen) = recorder([
        fail(401),
        ok({'access_token': 'new', 'refresh_token': 'refresh-2'}),
        ok([]),
      ]);

      await clientWith(transport, storage: storage).riderOrders();

      expect(seen, hasLength(3));
      expect(seen[1].url.path, endsWith('/auth/refresh'));
      expect(seen[2].headers['Authorization'], 'Bearer new');
    });

    test('the rotated refresh token is kept, not the spent one', () async {
      // The server treats a retired refresh token as a replay, so keeping the
      // old value would make this client destroy its own session the next time
      // it refreshed - a sign-out with no cause anybody could see.
      final storage = AuthStorage();
      await storage.saveTokens(accessToken: 'old', refreshToken: 'refresh-1');
      final (transport, _) = recorder([
        fail(401),
        ok({'access_token': 'new', 'refresh_token': 'refresh-2'}),
        ok([]),
      ]);

      await clientWith(transport, storage: storage).riderOrders();
      expect(storage.refreshToken, 'refresh-2');
      expect(storage.accessToken, 'new');
    });

    test('a refresh that fails drops the dead pair instead of resending it', () async {
      final storage = AuthStorage();
      await storage.saveTokens(accessToken: 'old', refreshToken: 'revoked');
      final (transport, seen) = recorder([fail(401), fail(401)]);

      await expectLater(
        clientWith(transport, storage: storage).riderOrders(),
        throwsA(isA<ApiException>()),
      );
      expect(storage.isLoggedIn, isFalse);
      expect(storage.refreshToken, isNull);
      // The original call, the refresh attempt, and no blind retry after it.
      expect(seen, hasLength(2));
    });

    test('a 401 with no refresh token behind it is not retried', () async {
      // This is every rider request. Retrying would cost a round trip that
      // cannot succeed before the sign-out they are getting anyway.
      final storage = AuthStorage();
      await storage.saveAccessTokenOnly('rider-token');
      final (transport, seen) = recorder([fail(401)]);

      await expectLater(
        clientWith(transport, storage: storage).riderOrders(),
        throwsA(isA<ApiException>().having((e) => e.statusCode, 'statusCode', 401)),
      );
      expect(seen, hasLength(1));
    });

    test('a 403 is not a refresh - the token is fine, the role is not', () async {
      final storage = AuthStorage();
      await storage.saveTokens(accessToken: 'a', refreshToken: 'r');
      final (transport, seen) = recorder([fail(403, 'Not your order')]);

      await expectLater(
        clientWith(transport, storage: storage).riderOrders(),
        throwsA(isA<ApiException>().having((e) => e.message, 'message', 'Not your order')),
      );
      expect(seen, hasLength(1));
    });
  });

  group('error messages reach the person reading the screen', () {
    test("FastAPI's string detail is used as-is", () async {
      final (transport, _) = recorder([fail(400, 'That code has expired')]);
      await expectLater(
        clientWith(transport).riderOrders(),
        throwsA(isA<ApiException>().having((e) => e.message, 'message', 'That code has expired')),
      );
    });

    test('a validation list becomes one named field rather than a blob', () async {
      // FastAPI answers a bad body with a list of objects. Printed raw it is a
      // paragraph of Python-looking punctuation on a stall owner's screen.
      final (transport, _) = recorder([
        http.Response(
          jsonEncode({
            'detail': [
              {'loc': ['body', 'phone'], 'msg': 'not a valid phone number'}
            ]
          }),
          422,
        )
      ]);
      await expectLater(
        clientWith(transport).riderOrders(),
        throwsA(isA<ApiException>()
            .having((e) => e.message, 'message', 'phone: not a valid phone number')),
      );
    });

    test('a non-JSON body still produces something sayable', () async {
      // A proxy 502 is HTML. Nothing may throw while building the message.
      final (transport, _) = recorder([http.Response('<html>bad gateway</html>', 502)]);
      await expectLater(
        clientWith(transport).riderOrders(),
        throwsA(isA<ApiException>()
            .having((e) => e.message, 'message', contains('502'))),
      );
    });
  });

  group('the rider session', () {
    test('a rider login stores an access token and no refresh token', () async {
      // Rider sessions have no refresh flow: they last the shift, and
      // regenerating the password is what ends one early.
      final storage = AuthStorage();
      await storage.saveTokens(accessToken: 'stale', refreshToken: 'stale-refresh');
      final (transport, _) = recorder([
        ok({'access_token': 'shift-token', 'rider': riderJson(), 'stall_name': 'Momo Point'}),
      ]);

      final session = await clientWith(transport, storage: storage).riderLogin('momo-ravi', 'pw');

      expect(session.stallName, 'Momo Point');
      expect(session.rider.loginId, 'momo-ravi');
      expect(storage.accessToken, 'shift-token');
      expect(storage.refreshToken, isNull,
          reason: 'a leftover refresh token sends the rider 401 down a path that cannot work');
    });

    test('the refresh slot is cleared on disk, not just in memory', () async {
      SharedPreferences.setMockInitialValues({'hb_refresh_token': 'from-last-login'});
      final storage = AuthStorage();
      await storage.load();
      expect(storage.refreshToken, 'from-last-login');

      await storage.saveAccessTokenOnly('shift-token');

      // What the next cold start will read.
      final reloaded = AuthStorage();
      await reloaded.load();
      expect(reloaded.accessToken, 'shift-token');
      expect(reloaded.refreshToken, isNull);
    });

    test('completing a delivery sends the code the customer read out', () async {
      final (transport, seen) = recorder([
        ok({
          'id': 'o1',
          'vendor_id': 'v1',
          'customer_id': 'c1',
          'status': 'completed',
          'payment_method': 'cashfree',
          'total_amount': '120',
          'note': null,
          'created_at': '2026-01-01T10:00:00',
          'updated_at': '2026-01-01T10:30:00',
          'items': [],
          'customer_name': null,
          'customer_phone': null,
        })
      ]);

      final order = await clientWith(transport)
          .riderUpdateOrderStatus('o1', OrderStatus.completed, deliveryCode: '4821');

      final body = jsonDecode(seen.single.body) as Map<String, dynamic>;
      expect(seen.single.method, 'PATCH');
      expect(body['status'], 'completed');
      expect(body['delivery_code'], '4821');
      expect(order.status, OrderStatus.completed);
    });

    test('picking an order up carries no code at all', () async {
      // Sending delivery_code: null would be a different request from sending
      // nothing, and the server validates the two differently.
      final (transport, seen) = recorder([
        ok({
          'id': 'o1',
          'vendor_id': 'v1',
          'customer_id': 'c1',
          'status': 'out_for_delivery',
          'payment_method': 'cashfree',
          'total_amount': '120',
          'note': null,
          'created_at': '2026-01-01T10:00:00',
          'updated_at': '2026-01-01T10:10:00',
          'items': [],
          'customer_name': null,
          'customer_phone': null,
        })
      ]);

      await clientWith(transport).riderUpdateOrderStatus('o1', OrderStatus.outForDelivery);

      final body = jsonDecode(seen.single.body) as Map<String, dynamic>;
      expect(body.containsKey('delivery_code'), isFalse);
      expect(body['status'], 'out_for_delivery');
    });

    test('a rider in a list carries no password field to leak', () async {
      final rider = Rider.fromJson(riderJson());
      expect(rider.displayName, 'Ravi');
      // Only RiderCredentials has one, and it is only ever built from the two
      // responses that create or regenerate a password.
      final credentials = RiderCredentials.fromJson({...riderJson(), 'password': 'one-time'});
      expect(credentials.password, 'one-time');
      expect(rider, isNot(isA<RiderCredentials>()));
    });
  });

  group('signing out', () {
    test('the refresh token is handed back to the server to be revoked', () async {
      // Clearing local storage alone used to be the whole of "log out", which
      // left the token usable by anything holding a copy for another 30 days.
      final storage = AuthStorage();
      await storage.saveTokens(accessToken: 'a', refreshToken: 'r');
      final (transport, seen) = recorder([ok({})]);

      await clientWith(transport, storage: storage).logout();

      expect(seen.single.url.path, endsWith('/auth/logout'));
      expect(jsonDecode(seen.single.body)['refresh_token'], 'r');
      expect(storage.isLoggedIn, isFalse);
    });

    test('being offline does not block a sign-out', () async {
      final storage = AuthStorage();
      await storage.saveTokens(accessToken: 'a', refreshToken: 'r');
      final transport = MockClient((_) async => throw const SocketLikeFailure());

      await clientWith(transport, storage: storage).logout();
      expect(storage.isLoggedIn, isFalse);
    });

    test('a rider signing out has nothing to revoke and does not try', () async {
      final storage = AuthStorage();
      await storage.saveAccessTokenOnly('shift-token');
      final (transport, seen) = recorder([ok({})]);

      await clientWith(transport, storage: storage).logout();
      expect(seen, isEmpty);
      expect(storage.isLoggedIn, isFalse);
    });
  });
}

/// Stands in for a network failure without depending on dart:io in a test that
/// also has to run on web.
class SocketLikeFailure implements Exception {
  const SocketLikeFailure();
}
