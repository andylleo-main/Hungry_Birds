import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hb_shared/hb_shared.dart';
import 'package:merchant_app/screens/orders_tab.dart';
import 'package:merchant_app/state/orders_state.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Telling the stall owner the money arrived, on their own delivery round.
///
/// Pay on delivery shipped with collection living entirely in the rider app, so
/// an owner walking an order over had no QR, no cash button, and no guard
/// stopping them from closing the order with nothing collected. This is the
/// sheet half of that fix, and these tests are the regression.
void main() {
  setUp(() {
    TestWidgetsFlutterBinding.ensureInitialized();
    SharedPreferences.setMockInitialValues({});
  });

  Order order({required PaymentStatus payment, String? collectedVia}) => Order(
        id: 'o1',
        orderNumber: '000001-4821',
        tokenNumber: 7,
        vendorId: 'v1',
        customerId: 'c1',
        status: OrderStatus.outForDelivery,
        paymentMethod: 'cod',
        paymentStatus: payment,
        collectedVia: collectedVia,
        totalAmount: 150,
        note: null,
        createdAt: DateTime(2026, 1, 1),
        updatedAt: DateTime(2026, 1, 1),
        items: const [],
        customerName: 'Student',
        customerPhone: '+919876543210',
        fulfilmentType: FulfilmentType.delivery,
        deliveryLocation: 'hostel_3',
        deliveryLocationLabel: 'Hostel 3',
        selfDelivery: true,
      );

  final qr = UpiQr('https://rzp.io/i/testqr', 150, DateTime(2026, 1, 1, 14, 30));

  /// A state object with no server behind it.
  ///
  /// The sheet's safety poll calls reloadQuietly, which swallows its own
  /// failures - so an unreachable client here is harmless, and the test drives
  /// the orders list directly, which is what a successful poll or a socket
  /// message does anyway.
  OrdersState stateWith(List<Order> orders) {
    final state = OrdersState(
      ApiClient(baseUrl: 'https://test.local/api', authStorage: AuthStorage()),
    );
    state.orders = orders;
    return state;
  }

  Future<void> mount(WidgetTester tester, OrdersState state) async {
    await tester.pumpWidget(
      ChangeNotifierProvider<OrdersState>.value(
        value: state,
        child: MaterialApp(
          home: Scaffold(body: StallUpiQrSheet(orderId: 'o1', qr: qr)),
        ),
      ),
    );
  }

  testWidgets('while the money is owed it shows the code and says it is waiting',
      (tester) async {
    await mount(tester, stateWith([order(payment: PaymentStatus.due)]));

    expect(find.textContaining('Waiting for the payment'), findsOneWidget);
    expect(find.textContaining('scan with any UPI app'), findsOneWidget);
    expect(find.textContaining('received'), findsNothing);
  });

  testWidgets('the moment Razorpay confirms it, the sheet says so', (tester) async {
    // The regression. qr_code.credited arrives on the stall's socket, and before
    // this the sheet was a static picture that never looked at the order again.
    final state = stateWith([order(payment: PaymentStatus.due)]);
    await mount(tester, state);
    expect(find.textContaining('received'), findsNothing);

    state.orders = [order(payment: PaymentStatus.paid, collectedVia: 'upi')];
    state.notifyListeners();
    await tester.pump();

    expect(find.text('₹150 received'), findsOneWidget);
    expect(find.textContaining('Paid by UPI'), findsOneWidget);
    expect(find.textContaining('Waiting for the payment'), findsNothing);
  });

  testWidgets('cash taken while the sheet is open closes it out too', (tester) async {
    // A customer who gives up on scanning and hands over notes: the owner taps
    // "Took cash" on the card behind, and this must stop insisting.
    final state = stateWith([order(payment: PaymentStatus.due)]);
    await mount(tester, state);

    state.orders = [order(payment: PaymentStatus.paid, collectedVia: 'cash')];
    state.notifyListeners();
    await tester.pump();

    expect(find.textContaining('Paid in cash'), findsOneWidget);
  });

  testWidgets('an order that has left the queue counts as settled', (tester) async {
    await mount(tester, stateWith([]));

    expect(find.textContaining('received'), findsOneWidget);
    expect(find.textContaining('Waiting for the payment'), findsNothing);
  });
}
