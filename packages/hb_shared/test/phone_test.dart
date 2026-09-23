import 'package:flutter_test/flutter_test.dart';
import 'package:hb_shared/hb_shared.dart';

void main() {
  group('validateIndianMobile mirrors the backend rules', () {
    for (final raw in [
      '9876543210',
      '+919876543210',
      '919876543210',
      '09876543210',
      '+91 98765 43210',
      '98765-43210',
    ]) {
      test('accepts $raw', () => expect(validateIndianMobile(raw), isNull));
    }

    for (final raw in ['123456789', '98765432100', '5876543210', '', 'abc']) {
      test('rejects $raw', () => expect(validateIndianMobile(raw), isNotNull));
    }

    test('rejects null', () => expect(validateIndianMobile(null), isNotNull));
  });

  group('formatPhoneForDisplay', () {
    test('splits a stored E.164 number for readability', () {
      expect(formatPhoneForDisplay('+919876543210'), '98765 43210');
    });

    test('leaves an unexpected shape alone rather than mangling it', () {
      expect(formatPhoneForDisplay('12345'), '12345');
    });
  });

  group('AppUser.hasPhone', () {
    AppUser userWith(String? phone) =>
        AppUser(id: 'u', email: 'a@b.c', fullName: null, phone: phone, role: UserRole.customer);

    test('false when null', () => expect(userWith(null).hasPhone, isFalse));
    test('false when empty', () => expect(userWith('').hasPhone, isFalse));
    test('true when set', () => expect(userWith('+919876543210').hasPhone, isTrue));
  });
}
