import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:hb_shared/hb_shared.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:merchant_app/state/merchant_state.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Serves canned API responses so the onboarding stages can be exercised
/// without a live backend.
http.Client _clientReturning(Map<String, Object> routes) {
  return MockClient((request) async {
    for (final entry in routes.entries) {
      if (request.url.path.endsWith(entry.key)) {
        final value = entry.value;
        if (value is int) return http.Response('{"detail":"nope"}', value);
        return http.Response(jsonEncode(value), 200);
      }
    }
    return http.Response('{"detail":"unexpected ${request.url.path}"}', 404);
  });
}

MerchantState _stateWith(http.Client client) {
  final storage = AuthStorage();
  return MerchantState(
    ApiClient(baseUrl: 'http://test.local', authStorage: storage, client: client),
  );
}

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  test('a signed-out user starts at the login stage', () async {
    final state = _stateWith(_clientReturning({}));
    await state.bootstrap();
    expect(state.stage, MerchantStage.loggedOut);
  });

  test('a customer-role user is asked to apply', () async {
    final state = _stateWith(_clientReturning({}));
    await state.onAuthenticated(
      AuthResult('a', 'r', const AppUser(id: 'u1', email: 'a@b.c', fullName: null, phone: null, role: UserRole.customer)),
    );
    expect(state.stage, MerchantStage.needsApplication);
  });

  test('an unapproved vendor waits for approval', () async {
    final state = _stateWith(_clientReturning({
      '/vendors/me': {
        'id': 'v1',
        'stall_name': 'Momo Point',
        'description': null,
        'cover_image_url': null,
        'is_approved': false,
        'is_open': false,
      },
    }));
    await state.onAuthenticated(
      AuthResult('a', 'r', const AppUser(id: 'u1', email: 'a@b.c', fullName: null, phone: null, role: UserRole.vendor)),
    );
    expect(state.stage, MerchantStage.awaitingApproval);
  });

  test('an approved vendor reaches the dashboard', () async {
    final state = _stateWith(_clientReturning({
      '/vendors/me': {
        'id': 'v1',
        'stall_name': 'Momo Point',
        'description': null,
        'cover_image_url': null,
        'is_approved': true,
        'is_open': true,
      },
    }));
    await state.onAuthenticated(
      AuthResult('a', 'r', const AppUser(id: 'u1', email: 'a@b.c', fullName: null, phone: null, role: UserRole.vendor)),
    );
    expect(state.stage, MerchantStage.ready);
    expect(state.vendor!.stallName, 'Momo Point');
  });

  test('a vendor-role user with no vendor row is sent back to apply', () async {
    final state = _stateWith(_clientReturning({'/vendors/me': 404}));
    await state.onAuthenticated(
      AuthResult('a', 'r', const AppUser(id: 'u1', email: 'a@b.c', fullName: null, phone: null, role: UserRole.vendor)),
    );
    expect(state.stage, MerchantStage.needsApplication);
  });
}
