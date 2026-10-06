import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:hb_shared/hb_shared.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// A stall's smallest delivery order, on the wire.
///
/// Both halves of this are places the obvious code is wrong. The server sends a
/// Decimal, which arrives as the *string* `"100.00"`, so `as double` throws and
/// the settings screen fails to load at all. And sending a Dart double back puts
/// `100.0` in the body, which pydantic's `decimal_places=2` will take but which
/// is one `toString()` change away from `1e+21`.
void main() {
  setUp(() {
    TestWidgetsFlutterBinding.ensureInitialized();
    SharedPreferences.setMockInitialValues({});
  });

  Map<String, dynamic> json({Object minimum = '100.00'}) => {
        'dine_in_enabled': true,
        'delivery_enabled': true,
        'min_delivery_order': minimum,
        'locations': [
          {'code': 'hostel_5', 'label': 'Hostel 5', 'enabled': true},
        ],
      };

  group('decoding', () {
    test('a decimal string is read as a number', () {
      final s = FulfilmentSettings.fromJson(json());
      expect(s.minDeliveryOrder, 100.0);
    });

    test('a bare JSON number is read too', () {
      // Not what this server sends, but a cheap guard: nothing about the app
      // should depend on which of the two shapes arrives.
      final s = FulfilmentSettings.fromJson(json(minimum: 100));
      expect(s.minDeliveryOrder, 100.0);
    });

    test('an older server that sends no figure still parses', () {
      // An APK outlives any one deploy. Before this was tolerant, a response
      // without the key threw a FormatException out of fromJson and the stall
      // could not open its settings screen at all.
      final bare = json()..remove('min_delivery_order');
      final s = FulfilmentSettings.fromJson(bare);
      expect(s.minDeliveryOrder, 0.0);
      expect(s.hasMinimum, isFalse);
    });

    test('so does an explicit null', () {
      final s = FulfilmentSettings.fromJson({
        ...json(),
        'min_delivery_order': null,
      });
      expect(s.minDeliveryOrder, 0.0);
    });

    test('zero means no minimum', () {
      final s = FulfilmentSettings.fromJson(json(minimum: '0.00'));
      expect(s.minDeliveryOrder, 0.0);
      expect(s.hasMinimum, isFalse);
    });

    test('anything above zero is a minimum', () {
      expect(FulfilmentSettings.fromJson(json()).hasMinimum, isTrue);
    });
  });

  group('copyWith', () {
    test('carries the minimum when something else changes', () {
      // The settings screen flips a switch by copying the whole object. If this
      // dropped the figure, saving a switch would silently reset the minimum.
      final s = FulfilmentSettings.fromJson(json(minimum: '250.00'));
      expect(s.copyWith(deliveryEnabled: false).minDeliveryOrder, 250.0);
    });

    test('replaces it when that is what changed', () {
      final s = FulfilmentSettings.fromJson(json());
      expect(s.copyWith(minDeliveryOrder: 0).minDeliveryOrder, 0.0);
    });
  });

  group('encoding', () {
    (ApiClient, List<http.Request>) recorder() {
      final seen = <http.Request>[];
      final transport = MockClient((request) async {
        seen.add(request);
        return http.Response(jsonEncode(json()), 200);
      });
      return (
        ApiClient(
          baseUrl: 'https://test.local/api',
          authStorage: AuthStorage(),
          client: transport,
        ),
        seen,
      );
    }

    test('the figure goes out as a two-decimal string', () async {
      final (client, seen) = recorder();
      await client.updateFulfilment(
        dineInEnabled: true,
        deliveryEnabled: true,
        enabledLocations: const ['hostel_5'],
        minDeliveryOrder: 150,
      );
      final body = jsonDecode(seen.single.body) as Map<String, dynamic>;
      expect(body['min_delivery_order'], '150.00');
    });

    test('omitting it sends no key at all', () async {
      // Not `null`, and not 0: the server reads an absent key as "leave this
      // stall's figure alone", which is what keeps a merchant build that
      // predates the field from wiping the minimum every time it saves.
      final (client, seen) = recorder();
      await client.updateFulfilment(
        dineInEnabled: true,
        deliveryEnabled: false,
        enabledLocations: const [],
      );
      final body = jsonDecode(seen.single.body) as Map<String, dynamic>;
      expect(body.containsKey('min_delivery_order'), isFalse);
    });
  });
}
