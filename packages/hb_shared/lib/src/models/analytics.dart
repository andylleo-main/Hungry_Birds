/// What a stall sold, when, and what it turned away.
///
/// Mirrors VendorAnalyticsOut. Deliberately carries none of the platform-wide
/// figures the admin dashboard has - a merchant's app has no business holding a
/// competitor's revenue even if nothing drew it.
class VendorTotals {
  final int orders;
  final double revenue;
  final int activeOrders;
  final int refusedOrders;
  final double refusedValue;

  const VendorTotals({
    required this.orders,
    required this.revenue,
    required this.activeOrders,
    required this.refusedOrders,
    required this.refusedValue,
  });

  /// What share of orders this stall turned away. Null when there is nothing to
  /// divide by - a quiet day should read as quiet, not as a perfect record.
  double? get refusalRate => orders == 0 ? null : refusedOrders / orders;

  factory VendorTotals.fromJson(Map<String, dynamic> json) => VendorTotals(
        orders: json['orders'] as int,
        revenue: double.parse(json['revenue'].toString()),
        activeOrders: json['active_orders'] as int,
        refusedOrders: json['refused_orders'] as int,
        refusedValue: double.parse(json['refused_value'].toString()),
      );
}

class DayPoint {
  final DateTime day;
  final int orders;
  final double revenue;

  const DayPoint({required this.day, required this.orders, required this.revenue});

  factory DayPoint.fromJson(Map<String, dynamic> json) => DayPoint(
        day: DateTime.parse(json['day'] as String),
        orders: json['orders'] as int,
        revenue: double.parse(json['revenue'].toString()),
      );
}

class HourPoint {
  final int hour;
  final int orders;

  const HourPoint({required this.hour, required this.orders});

  factory HourPoint.fromJson(Map<String, dynamic> json) =>
      HourPoint(hour: json['hour'] as int, orders: json['orders'] as int);
}

class TopDish {
  final String name;

  /// Null for a dish with no sizes.
  final String? variantName;
  final int quantity;
  final double revenue;

  const TopDish({
    required this.name,
    required this.variantName,
    required this.quantity,
    required this.revenue,
  });

  /// What to print on one line: "Momos · Half".
  String get label => variantName == null ? name : '$name · $variantName';

  factory TopDish.fromJson(Map<String, dynamic> json) => TopDish(
        name: json['name'] as String,
        variantName: json['variant_name'] as String?,
        quantity: json['quantity'] as int,
        revenue: double.parse(json['revenue'].toString()),
      );
}

class VendorAnalytics {
  final int rangeDays;
  final DateTime generatedAt;
  final VendorTotals totals;
  final List<DayPoint> ordersByDay;
  final List<HourPoint> hours;
  final List<TopDish> topDishes;
  final int pendingPriceChanges;

  const VendorAnalytics({
    required this.rangeDays,
    required this.generatedAt,
    required this.totals,
    required this.ordersByDay,
    required this.hours,
    required this.topDishes,
    required this.pendingPriceChanges,
  });

  /// The busiest hour of the local day, or null when nothing has sold.
  HourPoint? get busiestHour {
    final busy = [for (final h in hours) if (h.orders > 0) h];
    if (busy.isEmpty) return null;
    return busy.reduce((a, b) => a.orders >= b.orders ? a : b);
  }

  factory VendorAnalytics.fromJson(Map<String, dynamic> json) => VendorAnalytics(
        rangeDays: json['range_days'] as int,
        generatedAt: DateTime.parse(json['generated_at'] as String),
        totals: VendorTotals.fromJson(json['totals'] as Map<String, dynamic>),
        ordersByDay: [
          for (final d in (json['orders_by_day'] as List))
            DayPoint.fromJson(d as Map<String, dynamic>),
        ],
        hours: [
          for (final h in (json['hours'] as List)) HourPoint.fromJson(h as Map<String, dynamic>),
        ],
        topDishes: [
          for (final d in (json['top_dishes'] as List))
            TopDish.fromJson(d as Map<String, dynamic>),
        ],
        pendingPriceChanges: (json['pending_price_changes'] as int?) ?? 0,
      );
}
