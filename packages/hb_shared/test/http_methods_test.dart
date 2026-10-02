import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:hb_shared/hb_shared.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// That every request the client makes uses a verb the client can actually send.
///
/// _request dispatches on a method string through a switch, and an unlisted verb
/// throws ArgumentError in the default branch - before the request is built, so
/// nothing reaches the network at all. That is worse than a failed request: the
/// screens catch it in their general `catch (_)` arm, which says something about
/// the connection, so a call that was never attempted is reported as a network
/// problem on a working network.
///
/// PUT was missing, which is the whole of why a stall could not switch dine-in
/// or delivery off: updateFulfilment is the only PUT in the client, every save on
/// that screen threw, and the switch rolled back saying to check the connection.
void main() {
  setUp(() {
    TestWidgetsFlutterBinding.ensureInitialized();
    SharedPreferences.setMockInitialValues({});
  });

  http.Response _fulfilment({bool dineIn = true, bool delivery = true}) => http.Response(
        jsonEncode({
          'dine_in_enabled': dineIn,
          'delivery_enabled': delivery,
          'locations': [
            {'code': 'hostel_3', 'label': 'Hostel 3', 'enabled': delivery},
            {'code': 'library', 'label': 'Library', 'enabled': false},
          ],
        }),
        200,
      );

  test('the methods the client sends are all methods it can send', () {
    // Read from the source rather than exercised one by one: the bug was a call
    // site using a verb the dispatcher did not list, so the thing worth checking
    // is that the two sets agree - including for whatever is added next.
    final source =
        File('lib/src/api/api_client.dart').readAsStringSync();

    final handled = RegExp(r"case '([A-Z]+)':")
        .allMatches(source)
        .map((m) => m.group(1)!)
        .toSet();
    final used = RegExp(r"_request\(\s*'([A-Z]+)'")
        .allMatches(source)
        .map((m) => m.group(1)!)
        .toSet();

    expect(used, isNotEmpty, reason: 'the scan found no call sites; fix this test');
    expect(
      used.difference(handled),
      isEmpty,
      reason: 'these verbs are sent but not handled, so the call throws before '
          'any request is made',
    );
  });

  test('a PUT is actually sent as a PUT', () async {
    http.Request? seen;
    final client = ApiClient(
      baseUrl: 'https://test.local/api',
      authStorage: AuthStorage(),
      client: MockClient((request) async {
        seen = request;
        return _fulfilment(dineIn: false);
      }),
    );

    await client.updateFulfilment(
      dineInEnabled: false,
      deliveryEnabled: true,
      enabledLocations: ['hostel_3'],
    );

    expect(seen!.method, 'PUT');
    expect(seen!.url.path, endsWith('/vendors/me/fulfilment'));
    final body = jsonDecode(seen!.body) as Map<String, dynamic>;
    expect(body['dine_in_enabled'], isFalse);
    expect(body['delivery_enabled'], isTrue);
    expect(body['enabled_locations'], ['hostel_3']);
  });

  test('switching dine-in off comes back with it off', () async {
    // The symptom: the switch moved, the save threw, and it rolled straight
    // back - on a working connection, reporting a connection problem.
    final client = ApiClient(
      baseUrl: 'https://test.local/api',
      authStorage: AuthStorage(),
      client: MockClient((_) async => _fulfilment(dineIn: false)),
    );

    final saved = await client.updateFulfilment(
      dineInEnabled: false,
      deliveryEnabled: true,
      enabledLocations: ['hostel_3'],
    );

    expect(saved.dineInEnabled, isFalse);
    expect(saved.deliveryEnabled, isTrue);
  });

  test('switching delivery off comes back with it off', () async {
    final client = ApiClient(
      baseUrl: 'https://test.local/api',
      authStorage: AuthStorage(),
      client: MockClient((_) async => _fulfilment(delivery: false)),
    );

    final saved = await client.updateFulfilment(
      dineInEnabled: true,
      deliveryEnabled: false,
      enabledLocations: [],
    );

    expect(saved.deliveryEnabled, isFalse);
    expect(saved.enabledCodes, isEmpty);
  });

  test('the server refusing the last mode reaches the screen as its own words', () async {
    // Turning both off is refused on purpose - a stall that reads as open but
    // rejects every order is a confusing way to be closed. The message has to
    // arrive intact, or it looks like the same generic failure as the bug above.
    const refusal =
        'Keep dine-in or delivery switched on. To stop taking orders, close the stall instead.';
    final client = ApiClient(
      baseUrl: 'https://test.local/api',
      authStorage: AuthStorage(),
      client: MockClient(
        (_) async => http.Response(jsonEncode({'detail': refusal}), 400),
      ),
    );

    await expectLater(
      client.updateFulfilment(
        dineInEnabled: false,
        deliveryEnabled: false,
        enabledLocations: [],
      ),
      throwsA(isA<ApiException>()
          .having((e) => e.statusCode, 'statusCode', 400)
          .having((e) => e.message, 'message', refusal)),
    );
  });
}
