import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hb_shared/hb_shared.dart';
import 'package:merchant_app/screens/orders_tab.dart';
import 'package:merchant_app/services/printer.dart';
import 'package:merchant_app/state/merchant_state.dart';
import 'package:merchant_app/state/orders_state.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Reaching the printer at all.
///
/// The print action used to live inside the "accepted" branch of the card's
/// action row, so it existed only between tapping Accept and tapping Start
/// preparing - which stalls do in one motion. In practice the button was gone
/// before anybody went looking for it, and a jammed ticket could never be
/// reprinted, which is the one thing a separate print tap was meant to allow.
///
/// So the thing worth pinning is not how printing works but *when it is
/// offered*: at every status, and on finished orders too.
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
    // loading starts true, so the tab would otherwise render a spinner and no
    // cards at all. This stands in for the first load having come back.
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

  // Every status a stall can be looking at. placed and accepted are the ones
  // where a ticket is actually wanted; the rest are where somebody comes back
  // to it because the first copy jammed, smudged or went in the bin.
  for (final status in [
    OrderStatus.placed,
    OrderStatus.accepted,
    OrderStatus.preparing,
    OrderStatus.ready,
  ]) {
    testWidgets('a ${status.wire} order can be printed', (tester) async {
      await mountWith(tester, [order(status)]);
      expect(
        find.byTooltip('Print ticket'),
        findsOneWidget,
        reason: 'no way to print a ${status.wire} order',
      );
    });
  }

  testWidgets('a finished order can still be reprinted', (tester) async {
    // "Can you print that receipt again" is asked after the fact, not during.
    // Past orders share the one list under their own heading, so there is no
    // tab to switch to - the card is already on screen.
    await mountWith(tester, [order(OrderStatus.completed)]);

    expect(find.text('Past orders'), findsOneWidget);
    expect(find.byTooltip('Print ticket'), findsOneWidget);
  });

  testWidgets('one button per order, not one per status branch', (tester) async {
    await mountWith(tester, [order(OrderStatus.accepted)]);
    expect(find.byTooltip('Print ticket'), findsOneWidget);
  });
}
