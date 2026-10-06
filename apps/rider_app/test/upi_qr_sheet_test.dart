import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hb_shared/hb_shared.dart';
import 'package:provider/provider.dart';
import 'package:rider_app/screens/deliveries_screen.dart';
import 'package:rider_app/state/rider_state.dart';

/// Telling the rider the money arrived.
///
/// The sheet used to be a static picture: the rider held it up, the customer
/// paid, Razorpay told the server - and nothing told the rider, who had to close
/// it and notice the card behind had changed. These tests are that regression.
void main() {
  Order order(String id, {required PaymentStatus payment, String? collectedVia}) => Order(
        id: id,
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
        riderId: 'r1',
      );

  final qr = UpiQr(
    'https://rzp.io/i/testqr',
    150,
    DateTime(2026, 1, 1, 14, 30),
  );

  /// A state object with no API behind it.
  ///
  /// The sheet polls by calling refresh(), which would reach for a client that
  /// does not exist here - so the test drives the orders list directly, which is
  /// what a successful poll does anyway.
  RiderState stateWith(List<Order> orders) {
    final state = RiderState(ApiClient(baseUrl: 'https://test.local/api', authStorage: AuthStorage()));
    state.orders = orders;
    return state;
  }

  Future<void> mount(WidgetTester tester, RiderState state) async {
    await tester.pumpWidget(
      ChangeNotifierProvider<RiderState>.value(
        value: state,
        child: MaterialApp(
          home: Scaffold(body: UpiQrSheet(orderId: 'o1', qr: qr)),
        ),
      ),
    );
  }

  testWidgets('while the money is owed it shows the code and says it is waiting',
      (tester) async {
    await mount(tester, stateWith([order('o1', payment: PaymentStatus.due)]));

    expect(find.textContaining('Waiting for the payment'), findsOneWidget);
    expect(find.textContaining('scan with any UPI app'), findsOneWidget);
    expect(find.textContaining('received'), findsNothing);
  });

  testWidgets('the moment the order is paid it says so without being reopened',
      (tester) async {
    // The whole regression: this transition used to leave the rider staring at a
    // QR for an order that was already settled.
    final state = stateWith([order('o1', payment: PaymentStatus.due)]);
    await mount(tester, state);
    expect(find.textContaining('received'), findsNothing);

    // What a successful poll does once Razorpay's webhook has landed.
    state.orders = [order('o1', payment: PaymentStatus.paid, collectedVia: 'upi')];
    state.notifyListeners();
    await tester.pump();

    expect(find.text('₹150 received'), findsOneWidget);
    expect(find.textContaining('Paid by UPI'), findsOneWidget);
    expect(find.textContaining('Waiting for the payment'), findsNothing);
  });

  testWidgets('an order that has left the list counts as settled', (tester) async {
    // It only leaves once it is finished, so showing a code for it would be
    // asking a customer to pay for something no longer the rider's.
    await mount(tester, stateWith([]));

    expect(find.textContaining('received'), findsOneWidget);
    expect(find.textContaining('Waiting for the payment'), findsNothing);
  });

  testWidgets('cash collected while the sheet is open closes it out too',
      (tester) async {
    // A customer who gives up on scanning and hands over notes instead: the
    // rider taps Cash on the card behind, and this must not keep insisting.
    final state = stateWith([order('o1', payment: PaymentStatus.due)]);
    await mount(tester, state);

    state.orders = [order('o1', payment: PaymentStatus.paid, collectedVia: 'cash')];
    state.notifyListeners();
    await tester.pump();

    expect(find.textContaining('Paid in cash'), findsOneWidget);
  });
}
