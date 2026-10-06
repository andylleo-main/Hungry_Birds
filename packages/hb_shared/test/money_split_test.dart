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

  test('shares are computed against the takings, and null when nothing sold', () {
    const slice = MoneySplit(orders: 2, revenue: 300);

    expect(slice.shareOf(450), closeTo(2 / 3, 1e-9));
    // A quiet day reads as quiet rather than as a real zero per cent.
    expect(slice.shareOf(0), isNull);
    expect(MoneySplit.empty.shareOf(0), isNull);
  });
}
