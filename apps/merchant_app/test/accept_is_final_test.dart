import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hb_shared/hb_shared.dart';
import 'package:merchant_app/screens/orders_tab.dart';
import 'package:merchant_app/services/printer.dart';
import 'package:merchant_app/state/merchant_state.dart';
import 'package:merchant_app/state/orders_state.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Accepting an order is the commitment.
///
/// The stall says yes or no at `placed`, and after that the order is theirs to
/// make. This reverses an earlier decision - cancel used to sit beside "start
/// preparing" - so it is pinned, because the argument for putting it back is
/// written down in the code and somebody will read it and act on it.
///
/// Worth knowing what it closes off: the customer cannot cancel either, and
/// there is no admin route that cancels an order, so an accepted order has no
/// exit but completion.
void main() {
  setUp(() {
    TestWidgetsFlutterBinding.ensureInitialized();
    SharedPreferences.setMockInitialValues({});
  });

  Order order(OrderStatus status) => Order(
        id: 'o-${status.wire}',
        orderNumber: '000001-4821',
        tokenNumber: 7,
        vendorId: 'v1',
        customerId: 'c1',
        status: status,
        paymentMethod: 'online',
        paymentStatus: PaymentStatus.paid,
        totalAmount: 150,
        note: null,
        createdAt: DateTime(2026, 1, 1),
        updatedAt: DateTime(2026, 1, 1),
        items: const [
          OrderLineItem(
            id: 'li1',
            menuItemId: 'm1',
            nameSnapshot: 'Steamed momo',
            priceSnapshot: 75,
            quantity: 2,
          ),
        ],
        customerName: 'Student',
        customerPhone: null,
        fulfilmentType: FulfilmentType.dineIn,
        deliveryLocation: null,
        deliveryLocationLabel: null,
      );

  ApiClient api() =>
      ApiClient(baseUrl: 'https://test.local/api', authStorage: AuthStorage());

  Future<void> mountWith(WidgetTester tester, List<Order> orders) async {
    final ordersState = OrdersState(api())
      ..orders = orders
      ..loading = false;
    await tester.pumpWidget(
      MultiProvider(
        providers: [
          ChangeNotifierProvider<OrdersState>.value(value: ordersState),
          ChangeNotifierProvider<MerchantState>(create: (_) => MerchantState(api())),
          ChangeNotifierProvider<PrinterService>(create: (_) => PrinterService()),
        ],
        child: const MaterialApp(home: OrdersTab()),
      ),
    );
    await tester.pump();
  }

  testWidgets('an accepted order offers no way to cancel', (tester) async {
    await mountWith(tester, [order(OrderStatus.accepted)]);

    expect(find.text('Start preparing'), findsOneWidget);
    expect(find.text('Cancel'), findsNothing);
    expect(find.text('Cancel order'), findsNothing);
  });

  testWidgets('a placed order can still be refused outright', (tester) async {
    // The decision point did not disappear, it moved earlier. Taking this away
    // too would leave a stall unable to say no at all.
    await mountWith(tester, [order(OrderStatus.placed)]);

    expect(find.text('Reject'), findsOneWidget);
    expect(find.text('Accept'), findsOneWidget);
  });

  testWidgets('nothing further along offers a cancel either', (tester) async {
    for (final status in [OrderStatus.preparing, OrderStatus.ready]) {
      await mountWith(tester, [order(status)]);
      expect(find.text('Cancel'), findsNothing, reason: 'on ${status.wire}');
    }
  });
}
