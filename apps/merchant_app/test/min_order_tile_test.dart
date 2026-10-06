import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hb_shared/hb_shared.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:merchant_app/screens/fulfilment_screen.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// The stall's smallest delivery order, from the settings screen.
///
/// The figure is enforced by the API, so what matters here is the three ways
/// this screen could misrepresent it: showing the wrong number, letting a stall
/// edit it while delivery is off (where it does nothing), and - the one with no
/// visible symptom - saving a switch without carrying the figure along, which
/// would quietly reset the minimum every time a location was toggled.
void main() {
  setUp(() {
    TestWidgetsFlutterBinding.ensureInitialized();
    SharedPreferences.setMockInitialValues({});
  });

  Map<String, dynamic> settings({
    Object minimum = '100.00',
    bool delivery = true,
  }) => {
        'dine_in_enabled': true,
        'delivery_enabled': delivery,
        'min_delivery_order': minimum,
        'locations': [
          {'code': 'hostel_5', 'label': 'Hostel 5', 'enabled': true},
          {'code': 'hostel_6', 'label': 'Hostel 6', 'enabled': false},
        ],
      };

  /// The screen, wired to a transport that answers every GET with [initial] and
  /// echoes back whatever a PUT sends. Returns the recorded requests.
  Future<List<http.Request>> pump(
    WidgetTester tester, {
    required Map<String, dynamic> initial,
  }) async {
    final seen = <http.Request>[];
    var current = initial;
    final transport = MockClient((request) async {
      seen.add(request);
      if (request.method == 'PUT') {
        final sent = jsonDecode(request.body) as Map<String, dynamic>;
        current = {
          ...current,
          'dine_in_enabled': sent['dine_in_enabled'],
          'delivery_enabled': sent['delivery_enabled'],
          // Exactly the server's rule: an absent figure leaves the old one.
          if (sent.containsKey('min_delivery_order'))
            'min_delivery_order': sent['min_delivery_order'],
        };
      }
      return http.Response(jsonEncode(current), 200);
    });

    final api = ApiClient(
      baseUrl: 'https://test.local/api',
      authStorage: AuthStorage(),
      client: transport,
    );

    await tester.pumpWidget(
      Provider<ApiClient>.value(
        value: api,
        child: const MaterialApp(home: FulfilmentScreen()),
      ),
    );
    await tester.pumpAndSettle();
    return seen;
  }

  testWidgets('the current minimum is on the tile', (tester) async {
    await pump(tester, initial: settings(minimum: '150.00'));

    expect(find.text('Smallest delivery order'), findsOneWidget);
    expect(find.text('₹150'), findsOneWidget);
    expect(
      find.textContaining('Students need ₹150 in the cart'),
      findsOneWidget,
    );
  });

  testWidgets('no minimum reads as None, not as zero rupees', (tester) async {
    await pump(tester, initial: settings(minimum: '0.00'));

    expect(find.text('None'), findsOneWidget);
    expect(find.text('₹0'), findsNothing);
    expect(find.textContaining('No minimum'), findsOneWidget);
  });

  testWidgets('editing it saves the new figure', (tester) async {
    final seen = await pump(tester, initial: settings(minimum: '100.00'));

    await tester.tap(find.text('Smallest delivery order'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextField), '250');
    await tester.tap(find.text('Save'));
    await tester.pumpAndSettle();

    final put = seen.lastWhere((r) => r.method == 'PUT');
    expect(
      (jsonDecode(put.body) as Map<String, dynamic>)['min_delivery_order'],
      '250.00',
    );
    expect(find.text('₹250'), findsOneWidget);
  });

  testWidgets('zero is accepted and clears the minimum', (tester) async {
    await pump(tester, initial: settings(minimum: '100.00'));

    await tester.tap(find.text('Smallest delivery order'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextField), '0');
    await tester.tap(find.text('Save'));
    await tester.pumpAndSettle();

    expect(find.text('None'), findsOneWidget);
  });

  testWidgets('nonsense is refused without a request', (tester) async {
    final seen = await pump(tester, initial: settings());

    await tester.tap(find.text('Smallest delivery order'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextField), 'free food please');
    await tester.tap(find.text('Save'));
    await tester.pumpAndSettle();

    // Still open, saying why, and nothing sent.
    expect(find.text('Enter an amount in rupees'), findsOneWidget);
    expect(seen.where((r) => r.method == 'PUT'), isEmpty);
  });

  testWidgets('a figure the server would reject never leaves the phone',
      (tester) async {
    final seen = await pump(tester, initial: settings());

    await tester.tap(find.text('Smallest delivery order'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextField), '99999');
    await tester.tap(find.text('Save'));
    await tester.pumpAndSettle();

    expect(find.textContaining('too high'), findsOneWidget);
    expect(seen.where((r) => r.method == 'PUT'), isEmpty);
  });

  testWidgets('the tile is not editable while delivery is off', (tester) async {
    final seen = await pump(tester, initial: settings(delivery: false));

    await tester.tap(find.text('Smallest delivery order'));
    await tester.pumpAndSettle();

    // No dialog: a minimum on a stall that is not delivering decides nothing,
    // and an editable field that changes nothing is worse than a disabled one.
    expect(find.text('Cancel'), findsNothing);
    expect(seen.where((r) => r.method == 'PUT'), isEmpty);
  });

  testWidgets('flipping a location carries the minimum along', (tester) async {
    // The one with no visible symptom. _save sends the whole settings object,
    // so if it stopped including the figure, every location toggle would reset
    // the stall's minimum and nobody would notice until a Rs.20 delivery landed.
    final seen = await pump(tester, initial: settings(minimum: '150.00'));

    await tester.tap(find.text('Hostel 6'));
    await tester.pumpAndSettle();

    final put = seen.lastWhere((r) => r.method == 'PUT');
    expect(
      (jsonDecode(put.body) as Map<String, dynamic>)['min_delivery_order'],
      '150.00',
    );
    expect(find.text('₹150'), findsOneWidget);
  });
}
