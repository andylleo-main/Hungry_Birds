import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hb_shared/hb_shared.dart';
import 'package:provider/provider.dart';
import 'package:rider_app/screens/deliveries_screen.dart';
import 'package:rider_app/state/rider_state.dart';

/// What a rider is told to collect.
///
/// Before cashback existed the order's value and the amount owed were one
/// number, so every screen read `totalAmount`. Now a student can put
/// promotional credit towards an order, Hungry Birds funds it, and the rider
/// must ask for the smaller figure - while the stall is still owed the larger
/// one.
///
/// Getting this wrong is not a silent bug. A rider asking for ₹200 on an order
/// the app told the customer was ₹160 has an argument at a hostel gate, and the
/// customer is right.
void main() {
  Order order({double total = 200, double cashback = 0}) => Order(
        id: 'o1',
        orderNumber: '000001-4821',
        tokenNumber: 7,
        vendorId: 'v1',
        customerId: 'c1',
        status: OrderStatus.outForDelivery,
        paymentMethod: 'cod',
        paymentStatus: PaymentStatus.due,
        totalAmount: total,
        cashbackApplied: cashback,
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

  Future<void> mount(WidgetTester tester, Order o) async {
    final state = RiderState(
      ApiClient(baseUrl: 'https://test.local/api', authStorage: AuthStorage()),
    );
    state.orders = [o];
    await tester.pumpWidget(
      ChangeNotifierProvider<RiderState>.value(
        value: state,
        child: const MaterialApp(home: DeliveriesScreen()),
      ),
    );
    await tester.pumpAndSettle();
  }

  testWidgets('an ordinary order asks for its full value', (tester) async {
    await mount(tester, order());
    expect(find.text('COLLECT ₹200'), findsOneWidget);
  });

  testWidgets('a discounted order asks for what is owed', (tester) async {
    await mount(tester, order(cashback: 40));

    expect(find.text('COLLECT ₹160'), findsOneWidget);
    expect(find.text('COLLECT ₹200'), findsNothing);
  });

  testWidgets('and says why it is less than the food', (tester) async {
    // Without this the rider cannot tell a discount from a bug, and the safe
    // thing for them to do - ask for the bigger number - is the wrong thing.
    await mount(tester, order(cashback: 40));

    expect(find.textContaining('paid by cashback'), findsOneWidget);
    expect(find.textContaining('₹200'), findsOneWidget);
  });

  testWidgets('an ordinary order says nothing about cashback', (tester) async {
    // Almost every delivery. The extra line must not become permanent furniture
    // on a screen a rider reads while walking.
    await mount(tester, order());
    expect(find.textContaining('cashback'), findsNothing);
  });
}
