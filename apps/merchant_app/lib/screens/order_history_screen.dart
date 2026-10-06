import 'package:flutter/material.dart';
import 'package:hb_shared/hb_shared.dart';
import 'package:intl/intl.dart';

/// Every day in the range, with what it sold.
///
/// Reached by tapping Orders on the finance tab, because that figure invites
/// the next question - a stall that sees "142 orders" wants to know which days
/// they were, and the bar chart on the dashboard shows the shape without the
/// numbers.
///
/// Built from the same `orders_by_day` the chart uses rather than fetching
/// anything, so the two cannot disagree about a day and opening this costs
/// nothing.
class OrderHistoryScreen extends StatelessWidget {
  const OrderHistoryScreen({super.key, required this.days, required this.rangeDays});

  final List<DayPoint> days;
  final int rangeDays;

  @override
  Widget build(BuildContext context) {
    final money = NumberFormat.decimalPattern('en_IN');
    // Newest first. The question behind this is almost always about today or
    // yesterday; last month is what you scroll for.
    final ordered = [...days.reversed];
    final orders = days.fold<int>(0, (sum, d) => sum + d.orders);
    final revenue = days.fold<double>(0, (sum, d) => sum + d.revenue);
    final busiest = days.fold<double>(0, (m, d) => d.revenue > m ? d.revenue : m);

    return Scaffold(
      appBar: AppBar(title: Text('Last $rangeDays days')),
      body: ListView.separated(
        padding: const EdgeInsets.all(16),
        itemCount: ordered.length + 1,
        separatorBuilder: (_, __) => const Divider(height: 1),
        itemBuilder: (context, index) {
          if (index == 0) {
            return Padding(
              padding: const EdgeInsets.only(bottom: 12),
              child: Row(
                children: [
                  Expanded(
                    child: _Summary(
                      label: 'Orders',
                      value: '$orders',
                    ),
                  ),
                  Expanded(
                    child: _Summary(
                      label: 'Taken',
                      value: '₹${money.format(revenue.round())}',
                      tone: AppTheme.success,
                    ),
                  ),
                ],
              ),
            );
          }

          final day = ordered[index - 1];
          return _DayRow(day: day, money: money, busiest: busiest);
        },
      ),
    );
  }
}

class _Summary extends StatelessWidget {
  const _Summary({required this.label, required this.value, this.tone});

  final String label;
  final String value;
  final Color? tone;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(label, style: const TextStyle(fontSize: 12, color: AppTheme.textSecondary)),
        Text(
          value,
          style: TextStyle(
            fontSize: 22,
            fontWeight: FontWeight.w800,
            color: tone ?? AppTheme.textPrimary,
          ),
        ),
      ],
    );
  }
}

class _DayRow extends StatelessWidget {
  const _DayRow({required this.day, required this.money, required this.busiest});

  final DayPoint day;
  final NumberFormat money;

  /// The best day in the range, so each row can show its share as a bar. A
  /// column of numbers hides the shape of a week; this is the shape without
  /// needing a second screen for it.
  final double busiest;

  @override
  Widget build(BuildContext context) {
    final quiet = day.orders == 0;
    final share = busiest <= 0 ? 0.0 : day.revenue / busiest;

    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 10),
      child: Row(
        children: [
          SizedBox(
            width: 92,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  DateFormat('EEE').format(day.day),
                  style: const TextStyle(fontSize: 11, color: AppTheme.textSecondary),
                ),
                Text(
                  DateFormat('d MMM').format(day.day),
                  style: TextStyle(
                    fontSize: 14,
                    fontWeight: FontWeight.w700,
                    color: quiet ? AppTheme.textSecondary : AppTheme.textPrimary,
                  ),
                ),
              ],
            ),
          ),
          Expanded(
            child: ClipRRect(
              borderRadius: BorderRadius.circular(3),
              child: LinearProgressIndicator(
                value: share,
                minHeight: 6,
                backgroundColor: AppTheme.divider,
                valueColor: const AlwaysStoppedAnimation(AppTheme.primaryRed),
              ),
            ),
          ),
          const SizedBox(width: 12),
          SizedBox(
            width: 96,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.end,
              children: [
                Text(
                  // An em dash on a day with nothing, so a closed Sunday reads
                  // as closed rather than as a day that took no money.
                  quiet ? '—' : '₹${money.format(day.revenue.round())}',
                  style: TextStyle(
                    fontSize: 14,
                    fontWeight: FontWeight.w700,
                    color: quiet ? AppTheme.textSecondary : AppTheme.textPrimary,
                  ),
                ),
                if (!quiet)
                  Text(
                    '${day.orders} ${day.orders == 1 ? 'order' : 'orders'}',
                    style: const TextStyle(fontSize: 11, color: AppTheme.textSecondary),
                  ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
