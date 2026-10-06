import 'package:flutter_test/flutter_test.dart';
import 'package:hb_shared/hb_shared.dart';

/// The finance breakdown as the merchant app reads it.
///
/// The screen is checked against a cash box, so the two things worth pinning
/// are that the slices decode at all and that a server too old to send them
/// leaves a gap rather than crashing the tab.
void main() {
  Map<String, dynamic> totals({Map<String, dynamic>? extra}) => {
        'orders': 3,
        'revenue': '450',
        'active_orders': 1,
        'refused_orders': 0,
        'refused_value': '0',
        ...?extra,
      };

  test('the slices decode and keep their own order counts', () {
    final t = VendorTotals.fromJson(totals(extra: {
      'dine_in': {'orders': 1, 'revenue': '150'},
      'delivery': {'orders': 2, 'revenue': '300'},
      'cash': {'orders': 1, 'revenue': '150'},
      'prepaid': {'orders': 2, 'revenue': '300'},
    }));

    expect(t.dineIn.revenue, 150);
    expect(t.delivery.orders, 2);
    expect(t.cash.revenue, 150);
    expect(t.prepaid.orders, 2);

    // Each pair reconciles against the takings, which is what the caption on
    // the screen promises.
    expect(t.dineIn.revenue + t.delivery.revenue, t.revenue);
    expect(t.cash.revenue + t.prepaid.revenue, t.revenue);
  });

  test('a server that sends no breakdown leaves zeroes, not an exception', () {
    // An app newer than the deployment it is pointed at should show a screen
    // with a gap in it. Same convention the order model uses for fields added
    // after a build shipped.
    final t = VendorTotals.fromJson(totals());

    expect(t.dineIn.orders, 0);
    expect(t.prepaid.revenue, 0);
    expect(t.revenue, 450);
  });

  test('the cross-tab decodes and both margins reconcile', () {
    final t = VendorTotals.fromJson(totals(extra: {
      'dine_in': {'orders': 1, 'revenue': '150'},
      'delivery': {'orders': 2, 'revenue': '300'},
      'cash': {'orders': 1, 'revenue': '150'},
      'prepaid': {'orders': 2, 'revenue': '300'},
      'dine_in_prepaid': {'orders': 1, 'revenue': '150'},
      'dine_in_cash': {'orders': 0, 'revenue': '0'},
      'delivery_prepaid': {'orders': 1, 'revenue': '150'},
      'delivery_cash': {'orders': 1, 'revenue': '150'},
      'outstanding': {'orders': 1, 'revenue': '150'},
      'refunded': {'orders': 1, 'revenue': '75'},
    }));

    // Rows.
    expect(t.dineInPrepaid.revenue + t.dineInCash.revenue, t.dineIn.revenue);
    expect(t.deliveryPrepaid.revenue + t.deliveryCash.revenue, t.delivery.revenue);
    // Columns.
    expect(t.dineInPrepaid.revenue + t.deliveryPrepaid.revenue, t.prepaid.revenue);
    expect(t.dineInCash.revenue + t.deliveryCash.revenue, t.cash.revenue);
    // Corner.
    expect(
      t.dineInPrepaid.revenue +
          t.dineInCash.revenue +
          t.deliveryPrepaid.revenue +
          t.deliveryCash.revenue,
      t.revenue,
    );

    // Neither of these is takings, so neither is in the table.
    expect(t.outstanding.revenue, 150);
    expect(t.refunded.revenue, 75);
  });

  test('the average is over paid orders, not over every order placed', () {
    // `orders` counts the refused ones too. Dividing by it would quietly
    // understate what an order is worth on a day with rejections.
    final t = VendorTotals.fromJson(totals(extra: {
      'dine_in': {'orders': 1, 'revenue': '150'},
      'delivery': {'orders': 2, 'revenue': '300'},
    }));

    expect(t.orders, 3, reason: 'the fixture places three');
    expect(t.paidOrders, 3);
    expect(t.averageOrder, closeTo(150, 1e-9));
  });

  test('the average is null rather than zero when nothing sold', () {
    expect(VendorTotals.fromJson(totals()).averageOrder, isNull);
  });

  test('shares are computed against the takings, and null when nothing sold', () {
    const slice = MoneySplit(orders: 2, revenue: 300);

    expect(slice.shareOf(450), closeTo(2 / 3, 1e-9));
    // A quiet day reads as quiet rather than as a real zero per cent.
    expect(slice.shareOf(0), isNull);
    expect(MoneySplit.empty.shareOf(0), isNull);
  });
}
