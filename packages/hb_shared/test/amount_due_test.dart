import 'package:flutter_test/flutter_test.dart';
import 'package:hb_shared/hb_shared.dart';

/// What the stall is owed, and what the customer hands over.
///
/// Two figures, and until cashback existed they were the same number, which is
/// why every screen read `totalAmount` and why this is worth pinning. Hungry
/// Birds funds a redemption, so the stall keeps being owed the full value of
/// the food while the customer pays less - and a rider, a QR and a printed
/// ticket all have to show the smaller one.
void main() {
  Order order({Object? cashback = 0, Object? coupon = 0, double total = 200}) =>
      Order.fromJson({
        'id': 'o1',
        'order_number': '000001-4821',
        'token_number': 7,
        'vendor_id': 'v1',
        'customer_id': 'c1',
        'status': 'placed',
        'payment_method': 'cod',
        'payment_status': 'due',
        'total_amount': total.toString(),
        if (cashback != null) 'cashback_applied': cashback,
        if (coupon != null) 'coupon_discount': coupon,
        'note': null,
        'created_at': '2026-10-07T09:00:00',
        'updated_at': '2026-10-07T09:00:00',
        'items': const [],
        'fulfilment_type': 'delivery',
        'delivery_location': 'hostel_5',
      });

  test('with no cashback the two figures are the same', () {
    final o = order();
    expect(o.totalAmount, 200);
    expect(o.amountDue, 200);
    expect(o.hasDiscount, isFalse);
  });

  test('a discount comes off what is owed, not off the order', () {
    final o = order(cashback: '40.00');
    expect(o.totalAmount, 200, reason: 'the stall is still owed the full value');
    expect(o.cashbackApplied, 40);
    expect(o.amountDue, 160);
    expect(o.hasDiscount, isTrue);
  });

  test('a decimal string is read, like every other money field', () {
    // pydantic sends Decimal as a string, so `as double` would throw here.
    expect(order(cashback: '12.50').cashbackApplied, 12.5);
  });

  test('a bare JSON number is read too', () {
    expect(order(cashback: 40).cashbackApplied, 40);
  });

  test('an older server that sends no field at all still parses', () {
    // An installed APK outlives any one deploy. Absent means zero, which makes
    // amountDue equal the total - exactly how every order behaved before this.
    final o = order(cashback: null);
    expect(o.cashbackApplied, 0);
    expect(o.amountDue, 200);
    expect(o.hasDiscount, isFalse);
  });

  test('an explicit null is treated the same way', () {
    expect(order(cashback: 'null').cashbackApplied, 0);
  });

  test('a redemption can never cover the whole order', () {
    // The server caps redemption at 60% of the cart, so there is no free order.
    // Asserted here because it is the property the collect screens rely on:
    // there is always something to collect on a cash delivery.
    final o = order(cashback: '120.00');
    expect(o.amountDue, greaterThan(0));
  });

  group('a discount code', () {
    test('comes off what is owed, like cashback does', () {
      final o = order(coupon: '50.00');
      expect(o.totalAmount, 200, reason: 'the stall is still owed the full value');
      expect(o.couponDiscount, 50);
      expect(o.amountDue, 150);
      expect(o.hasDiscount, isTrue);
    });

    test('is named on a receipt so the line is not simply wrong', () {
      // The two never apply together, so the slip names one rather than
      // breaking a single figure into two lines on 58mm paper.
      expect(order(coupon: '50.00').discountLabel, 'Coupon');
      expect(order(cashback: '40.00').discountLabel, 'Cashback');
    });

    test('an older server that sends no field still parses', () {
      final o = order(coupon: null);
      expect(o.couponDiscount, 0);
      expect(o.amountDue, 200);
    });

    test('a decimal string is read, like every other money field', () {
      expect(order(coupon: '12.50').couponDiscount, 12.5);
    });

    test('discountApplied is whatever actually came off', () {
      expect(order(coupon: '50.00').discountApplied, 50);
      expect(order(cashback: '40.00').discountApplied, 40);
      expect(order().discountApplied, 0);
      expect(order().hasDiscount, isFalse);
    });
  });
}
