import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hb_shared/hb_shared.dart';
import 'package:merchant_app/screens/new_order_dialog.dart';

/// Getting out of the new-order dialog.
///
/// It used to call `context.read<OrdersState>()` from its only button.
/// OrdersState is created inside DashboardScreen, but showDialog defaults to
/// `useRootNavigator: true`, so the dialog is built in the root Overlay - above
/// DashboardScreen in the tree. The lookup walked up past MaterialApp, never
/// passed the provider, and threw - before Navigator.pop().
///
/// So "Got it" did nothing, on a full-screen dialog with barrierDismissible
/// off: the app froze with a stall unable to reach its own queue. These tests
/// mount the dialog with no provider above it at all, which is the condition
/// that used to break it.
void main() {
  Order order({String? note}) => Order(
        id: 'o1',
        orderNumber: '000001-4821',
        tokenNumber: 12,
        vendorId: 'v1',
        customerId: 'c1',
        status: OrderStatus.placed,
        paymentMethod: 'online',
        paymentStatus: PaymentStatus.paid,
        totalAmount: 1,
        note: note,
        createdAt: DateTime(2026, 1, 1),
        updatedAt: DateTime(2026, 1, 1),
        items: const [
          OrderLineItem(
            id: 'li1',
            menuItemId: 'm1',
            nameSnapshot: 'chewing gum',
            priceSnapshot: 1,
            quantity: 1,
          ),
        ],
        customerName: 'Student',
        customerPhone: null,
        fulfilmentType: FulfilmentType.delivery,
        deliveryLocation: 'hostel_9',
        deliveryLocationLabel: 'Hostel 9',
      );

  testWidgets('Got it closes the dialog and acknowledges, with no provider above',
      (tester) async {
    var acknowledged = 0;

    await tester.pumpWidget(
      MaterialApp(
        home: Builder(
          builder: (context) => Scaffold(
            body: ElevatedButton(
              onPressed: () => NewOrderDialog.show(
                context,
                order(),
                onAcknowledge: () => acknowledged++,
              ),
              child: const Text('open'),
            ),
          ),
        ),
      ),
    );

    await tester.tap(find.text('open'));
    await tester.pumpAndSettle();
    expect(find.text('NEW ORDER'), findsOneWidget);

    await tester.tap(find.text('Got it'));
    await tester.pumpAndSettle();

    expect(find.text('NEW ORDER'), findsNothing, reason: 'the dialog must close');
    expect(acknowledged, 1);
  });

  testWidgets('the order is readable on it', (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        home: NewOrderDialog(order: order(note: 'asdf'), onAcknowledge: () {}),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('Token #12'), findsOneWidget);
    expect(find.textContaining('Hostel 9'), findsOneWidget);
    expect(find.text('chewing gum'), findsOneWidget);
    expect(find.text('asdf'), findsOneWidget);
  });

  testWidgets('it cannot be dismissed by tapping outside', (tester) async {
    // A stray tap while wiping a counter must not clear an order nobody read.
    // This is also why the button failing was fatal rather than annoying.
    await tester.pumpWidget(
      MaterialApp(
        home: Builder(
          builder: (context) => Scaffold(
            body: ElevatedButton(
              onPressed: () =>
                  NewOrderDialog.show(context, order(), onAcknowledge: () {}),
              child: const Text('open'),
            ),
          ),
        ),
      ),
    );

    await tester.tap(find.text('open'));
    await tester.pumpAndSettle();

    await tester.tapAt(const Offset(5, 5));
    await tester.pumpAndSettle();

    expect(find.text('NEW ORDER'), findsOneWidget);
  });
}
