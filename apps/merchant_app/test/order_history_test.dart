import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hb_shared/hb_shared.dart';
import 'package:merchant_app/screens/order_history_screen.dart';

/// The day-by-day history behind the Orders figure.
void main() {
  List<DayPoint> week() => [
        DayPoint(day: DateTime(2026, 1, 1), orders: 4, revenue: 400),
        DayPoint(day: DateTime(2026, 1, 2), orders: 0, revenue: 0),
        DayPoint(day: DateTime(2026, 1, 3), orders: 9, revenue: 1200),
      ];

  Future<void> mount(WidgetTester tester, List<DayPoint> days) =>
      tester.pumpWidget(
        MaterialApp(home: OrderHistoryScreen(days: days, rangeDays: 7)),
      );

  testWidgets('every day in the range is listed', (tester) async {
    await mount(tester, week());

    expect(find.text('1 Jan'), findsOneWidget);
    expect(find.text('3 Jan'), findsOneWidget);
    // Including the quiet one. A closed Friday is a trough, not a gap - the
    // same reasoning the chart on the dashboard uses.
    expect(find.text('2 Jan'), findsOneWidget);
  });

  testWidgets('newest first, since the question is usually about today',
      (tester) async {
    await mount(tester, week());

    final third = tester.getTopLeft(find.text('3 Jan')).dy;
    final first = tester.getTopLeft(find.text('1 Jan')).dy;
    expect(third, lessThan(first));
  });

  testWidgets('the totals across the range are shown', (tester) async {
    await mount(tester, week());

    expect(find.text('13'), findsOneWidget, reason: '4 + 0 + 9 orders');
    expect(find.text('₹1,600'), findsOneWidget, reason: '400 + 1,200 taken');
  });

  testWidgets('a day with nothing reads as nothing, not as zero rupees',
      (tester) async {
    await mount(tester, week());

    expect(find.text('—'), findsOneWidget);
    expect(find.text('0 orders'), findsNothing);
  });

  testWidgets('an empty range does not divide by zero', (tester) async {
    await mount(tester, [
      DayPoint(day: DateTime(2026, 1, 1), orders: 0, revenue: 0),
    ]);
    await tester.pumpAndSettle();

    expect(tester.takeException(), isNull);
    expect(find.text('0'), findsOneWidget);
  });
}
