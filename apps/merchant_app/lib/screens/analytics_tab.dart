import 'package:flutter/material.dart';
import 'package:hb_shared/hb_shared.dart';
import 'package:intl/intl.dart';
import 'package:provider/provider.dart';

/// What this stall sold, when its rush is, and what it turned away.
///
/// Four questions a stall owner actually has, which the service-wide admin
/// dashboard does not answer: what to prep, when to staff, what it is costing to
/// refuse orders, and whether anything is stuck waiting on an admin.
class AnalyticsTab extends StatefulWidget {
  const AnalyticsTab({super.key});

  @override
  State<AnalyticsTab> createState() => _AnalyticsTabState();
}

class _AnalyticsTabState extends State<AnalyticsTab> {
  VendorAnalytics? _data;
  String? _error;
  bool _loading = false;
  int _days = 7;

  // The dashboard keeps every tab alive in an IndexedStack, so initState runs
  // once for the life of the session. Loading only there would mean a merchant
  // who opened this on Monday still reading Monday's numbers on Friday, so the
  // load is also driven by didChangeDependencies-free explicit refresh and by
  // the range buttons.
  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final data = await context.read<ApiClient>().myAnalytics(days: _days);
      if (mounted) setState(() => _data = data);
    } on ApiException catch (e) {
      if (mounted) setState(() => _error = e.message);
    } catch (_) {
      if (mounted) {
        setState(() => _error = "Couldn't reach the server. Check your connection.");
      }
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _setRange(int days) async {
    if (days == _days) return;
    setState(() => _days = days);
    await _load();
  }

  @override
  Widget build(BuildContext context) {
    final data = _data;

    return Scaffold(
      appBar: AppBar(
        title: const Text('How you are doing'),
        actions: [
          IconButton(
            onPressed: _loading ? null : _load,
            icon: const Icon(Icons.refresh),
            tooltip: 'Refresh',
          ),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: _load,
        child: switch ((data, _error)) {
          (_, final String error) => ListView(
              padding: const EdgeInsets.all(24),
              children: [
                const SizedBox(height: 60),
                Text(error, textAlign: TextAlign.center),
                const SizedBox(height: 16),
                Center(
                  child: OutlinedButton(onPressed: _load, child: const Text('Try again')),
                ),
              ],
            ),
          (null, _) => const Center(child: CircularProgressIndicator()),
          (final VendorAnalytics d, _) => _body(d),
        },
      ),
    );
  }

  Widget _body(VendorAnalytics d) {
    final money = NumberFormat.decimalPattern('en_IN');

    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Row(
          children: [
            for (final option in const [7, 30, 90])
              Padding(
                padding: const EdgeInsets.only(right: 8),
                child: ChoiceChip(
                  label: Text(option == 7 ? 'Week' : '$option days'),
                  selected: _days == option,
                  onSelected: _loading ? null : (_) => _setRange(option),
                ),
              ),
          ],
        ),
        const SizedBox(height: 14),

        Row(
          children: [
            Expanded(
              child: _Stat(
                label: 'Taken',
                value: '₹${money.format(d.totals.revenue.round())}',
                tone: AppTheme.success,
              ),
            ),
            const SizedBox(width: 10),
            Expanded(child: _Stat(label: 'Orders', value: '${d.totals.orders}')),
          ],
        ),
        const SizedBox(height: 10),
        Row(
          children: [
            Expanded(
              child: _Stat(label: 'On the counter now', value: '${d.totals.activeOrders}'),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: _Stat(
                label: 'Turned away',
                value: d.totals.refusalRate == null
                    ? '—'
                    : '${(d.totals.refusalRate! * 100).round()}%',
                // Only coloured once it is worth looking at. A stall refusing
                // nothing should not have a red number on its dashboard.
                tone: (d.totals.refusalRate ?? 0) >= 0.1 ? AppTheme.primaryRed : null,
                footnote: d.totals.refusedOrders == 0
                    ? null
                    : '₹${money.format(d.totals.refusedValue.round())} of orders',
              ),
            ),
          ],
        ),

        const SizedBox(height: 22),
        _SectionTitle(
          'Where it came from',
          subtitle: 'Of the ₹${money.format(d.totals.revenue.round())} taken. '
              'Each pair adds up to that.',
        ),
        _SplitRow(
          left: _SplitStat(
            label: 'Dine in',
            icon: Icons.restaurant,
            split: d.totals.dineIn,
            total: d.totals.revenue,
            money: money,
          ),
          right: _SplitStat(
            label: 'Delivery',
            icon: Icons.delivery_dining,
            split: d.totals.delivery,
            total: d.totals.revenue,
            money: money,
          ),
        ),
        const SizedBox(height: 10),
        _SplitRow(
          left: _SplitStat(
            label: 'Prepaid',
            icon: Icons.account_balance,
            split: d.totals.prepaid,
            total: d.totals.revenue,
            money: money,
          ),
          right: _SplitStat(
            label: 'Cash in hand',
            icon: Icons.payments_outlined,
            split: d.totals.cash,
            total: d.totals.revenue,
            // The number to count the till against, so it gets the emphasis.
            tone: AppTheme.success,
            money: money,
          ),
        ),
        const SizedBox(height: 8),
        const Padding(
          padding: EdgeInsets.symmetric(horizontal: 2),
          child: Text(
            // The one rule nobody would guess, and the one that decides whether
            // the till adds up: a doorstep UPI payment is not cash.
            'A pay-on-delivery order paid by UPI counts as prepaid — that '
            'money is with Razorpay, not in your cash box.',
            style: TextStyle(fontSize: 11, color: AppTheme.textSecondary),
          ),
        ),

        if (d.pendingPriceChanges > 0) ...[
          const SizedBox(height: 12),
          Container(
            width: double.infinity,
            padding: const EdgeInsets.fromLTRB(12, 10, 12, 10),
            decoration: BoxDecoration(
              color: AppTheme.warning.withValues(alpha: 0.12),
              borderRadius: BorderRadius.circular(8),
              border: const Border(left: BorderSide(color: AppTheme.warning, width: 4)),
            ),
            child: Row(
              children: [
                const Icon(Icons.hourglass_top, size: 16, color: AppTheme.warning),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    d.pendingPriceChanges == 1
                        ? '1 price change is waiting for approval'
                        : '${d.pendingPriceChanges} price changes are waiting for approval',
                    style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w600),
                  ),
                ),
              ],
            ),
          ),
        ],

        const SizedBox(height: 22),
        _SectionTitle(
          'What sells',
          subtitle: 'Across every size. Prep the top of this list.',
        ),
        if (d.topDishes.isEmpty)
          const _Nothing('Nothing has sold in this period yet.')
        else
          for (final dish in d.topDishes)
            Padding(
              padding: const EdgeInsets.only(bottom: 6),
              child: Row(
                children: [
                  SizedBox(
                    width: 38,
                    child: Text(
                      '${dish.quantity}×',
                      style: const TextStyle(fontWeight: FontWeight.w800),
                    ),
                  ),
                  Expanded(child: Text(dish.label)),
                  Text(
                    '₹${money.format(dish.revenue.round())}',
                    style: const TextStyle(color: AppTheme.textSecondary, fontSize: 13),
                  ),
                ],
              ),
            ),

        const SizedBox(height: 22),
        _SectionTitle(
          'When you are busy',
          subtitle: d.busiestHour == null
              ? 'No orders yet in this period.'
              : 'Busiest around ${_hourLabel(d.busiestHour!.hour)}.',
        ),
        _HourBars(hours: d.hours),

        const SizedBox(height: 22),
        _SectionTitle('Day by day'),
        _DayBars(days: d.ordersByDay),
        const SizedBox(height: 32),
      ],
    );
  }
}

String _hourLabel(int hour) {
  if (hour == 0) return '12 am';
  if (hour < 12) return '$hour am';
  if (hour == 12) return '12 pm';
  return '${hour - 12} pm';
}

class _Stat extends StatelessWidget {
  const _Stat({required this.label, required this.value, this.tone, this.footnote});

  final String label;
  final String value;
  final Color? tone;
  final String? footnote;

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              label,
              style: const TextStyle(fontSize: 12, color: AppTheme.textSecondary),
            ),
            const SizedBox(height: 4),
            Text(
              value,
              style: TextStyle(
                fontSize: 22,
                fontWeight: FontWeight.w800,
                color: tone ?? AppTheme.textPrimary,
              ),
            ),
            if (footnote != null)
              Text(
                footnote!,
                style: const TextStyle(fontSize: 11, color: AppTheme.textSecondary),
              ),
          ],
        ),
      ),
    );
  }
}

/// Two slices side by side, sized equally so the pair reads as one row.
class _SplitRow extends StatelessWidget {
  const _SplitRow({required this.left, required this.right});

  final Widget left;
  final Widget right;

  @override
  Widget build(BuildContext context) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Expanded(child: left),
        const SizedBox(width: 10),
        Expanded(child: right),
      ],
    );
  }
}

/// One slice: what it came to, how many orders, and what share of the total.
///
/// The share is the part a stall actually uses. An absolute figure says little
/// without knowing the total; "62% of takings" is the thing worth noticing when
/// it moves.
class _SplitStat extends StatelessWidget {
  const _SplitStat({
    required this.label,
    required this.icon,
    required this.split,
    required this.total,
    required this.money,
    this.tone,
  });

  final String label;
  final IconData icon;
  final MoneySplit split;
  final double total;
  final NumberFormat money;
  final Color? tone;

  @override
  Widget build(BuildContext context) {
    final share = split.shareOf(total);

    return Card(
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(icon, size: 14, color: AppTheme.textSecondary),
                const SizedBox(width: 6),
                Text(
                  label,
                  style: const TextStyle(fontSize: 12, color: AppTheme.textSecondary),
                ),
              ],
            ),
            const SizedBox(height: 4),
            Text(
              '₹${money.format(split.revenue.round())}',
              style: TextStyle(
                fontSize: 20,
                fontWeight: FontWeight.w800,
                color: tone ?? AppTheme.textPrimary,
              ),
            ),
            Text(
              // An em dash rather than "0%" when nothing has sold: a quiet day
              // should read as quiet, not as a real zero share.
              share == null
                  ? '—'
                  : '${(share * 100).round()}% · '
                      '${split.orders} ${split.orders == 1 ? 'order' : 'orders'}',
              style: const TextStyle(fontSize: 11, color: AppTheme.textSecondary),
            ),
          ],
        ),
      ),
    );
  }
}

class _SectionTitle extends StatelessWidget {
  const _SectionTitle(this.title, {this.subtitle});

  final String title;
  final String? subtitle;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(title, style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w800)),
          if (subtitle != null)
            Text(
              subtitle!,
              style: const TextStyle(fontSize: 12, color: AppTheme.textSecondary),
            ),
        ],
      ),
    );
  }
}

class _Nothing extends StatelessWidget {
  const _Nothing(this.message);
  final String message;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 8),
        child: Text(
          message,
          style: const TextStyle(fontSize: 13, color: AppTheme.textSecondary),
        ),
      );
}

/// Hand-drawn bars rather than a charting package.
///
/// Two dozen values with no axes, no legend and no interaction is less code
/// than configuring a chart library, and it adds no dependency to an APK that a
/// stall owner downloads over campus wifi.
class _HourBars extends StatelessWidget {
  const _HourBars({required this.hours});

  final List<HourPoint> hours;

  @override
  Widget build(BuildContext context) {
    final peak = hours.fold<int>(0, (m, h) => h.orders > m ? h.orders : m);
    if (peak == 0) return const _Nothing('No orders yet in this period.');

    return Column(
      children: [
        SizedBox(
          height: 90,
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              for (final h in hours)
                Expanded(
                  child: Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 1),
                    child: Container(
                      // A floor of 2px so an hour with one order is visibly
                      // different from an hour with none.
                      height: h.orders == 0 ? 2 : 2 + (86 * h.orders / peak),
                      decoration: BoxDecoration(
                        color: h.orders == 0
                            ? AppTheme.divider
                            : AppTheme.primaryRed.withValues(alpha: 0.85),
                        borderRadius: const BorderRadius.vertical(top: Radius.circular(2)),
                      ),
                    ),
                  ),
                ),
            ],
          ),
        ),
        const SizedBox(height: 4),
        const Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            Text('12 am', style: TextStyle(fontSize: 10, color: AppTheme.textSecondary)),
            Text('noon', style: TextStyle(fontSize: 10, color: AppTheme.textSecondary)),
            Text('11 pm', style: TextStyle(fontSize: 10, color: AppTheme.textSecondary)),
          ],
        ),
      ],
    );
  }
}

class _DayBars extends StatelessWidget {
  const _DayBars({required this.days});

  final List<DayPoint> days;

  @override
  Widget build(BuildContext context) {
    final peak = days.fold<double>(0, (m, d) => d.revenue > m ? d.revenue : m);
    final label = DateFormat('d MMM');

    return Column(
      children: [
        for (final d in days.reversed.take(10).toList().reversed)
          Padding(
            padding: const EdgeInsets.only(bottom: 6),
            child: Row(
              children: [
                SizedBox(
                  width: 54,
                  child: Text(
                    label.format(d.day),
                    style: const TextStyle(fontSize: 11, color: AppTheme.textSecondary),
                  ),
                ),
                Expanded(
                  child: Stack(
                    children: [
                      Container(height: 16, color: AppTheme.divider.withValues(alpha: 0.5)),
                      FractionallySizedBox(
                        widthFactor: peak == 0 ? 0 : (d.revenue / peak).clamp(0.0, 1.0),
                        child: Container(height: 16, color: AppTheme.primaryRed),
                      ),
                    ],
                  ),
                ),
                const SizedBox(width: 8),
                SizedBox(
                  width: 44,
                  child: Text(
                    '${d.orders}',
                    textAlign: TextAlign.right,
                    style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w700),
                  ),
                ),
              ],
            ),
          ),
      ],
    );
  }
}
