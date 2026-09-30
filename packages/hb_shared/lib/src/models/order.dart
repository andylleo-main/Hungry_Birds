import 'fulfilment.dart';

enum OrderStatus {
  placed,
  accepted,
  preparing,
  ready,
  completed,
  rejected,
  cancelled,

  /// A status this build of the app does not know about, because the server is
  /// newer than the app.
  ///
  /// Without this, [fromJson] was a bare `firstWhere` that threw StateError on
  /// an unrecognised value, and the two places that decode an order both
  /// swallow it badly: in a list fetch the throw abandons the whole response,
  /// so one unfamiliar order blanks the merchant's entire queue, and inside the
  /// socket's onData callback it is not caught by onError at all, so the update
  /// is silently dropped. A stall losing its order list mid-rush because the
  /// backend shipped a new status is not an acceptable way to find out.
  unknown;

  static OrderStatus fromJson(String value) => OrderStatus.values.firstWhere(
        (e) => e.name == value,
        orElse: () => OrderStatus.unknown,
      );

  String get label => switch (this) {
        OrderStatus.placed => 'Order placed',
        OrderStatus.accepted => 'Accepted',
        OrderStatus.preparing => 'Preparing',
        OrderStatus.ready => 'Ready for pickup',
        OrderStatus.completed => 'Completed',
        OrderStatus.rejected => 'Rejected',
        OrderStatus.cancelled => 'Cancelled',
        OrderStatus.unknown => 'Updated',
      };

  bool get isActive =>
      this == OrderStatus.placed ||
      this == OrderStatus.accepted ||
      this == OrderStatus.preparing ||
      this == OrderStatus.ready ||
      // Counted as active on purpose. If a newer server sends a status this
      // build cannot name, showing the order as something odd is far safer for
      // a stall than filing it under "done" and hiding it.
      this == OrderStatus.unknown;

  bool get isTerminal => !isActive;
}

class OrderLineItem {
  final String id;
  final String? menuItemId;
  final String nameSnapshot;
  final double priceSnapshot;
  final int quantity;

  const OrderLineItem({
    required this.id,
    required this.menuItemId,
    required this.nameSnapshot,
    required this.priceSnapshot,
    required this.quantity,
  });

  factory OrderLineItem.fromJson(Map<String, dynamic> json) => OrderLineItem(
        id: json['id'] as String,
        menuItemId: json['menu_item_id'] as String?,
        nameSnapshot: json['name_snapshot'] as String,
        priceSnapshot: double.parse(json['price_snapshot'].toString()),
        quantity: json['quantity'] as int,
      );
}

class Order {
  final String id;
  final String vendorId;
  final String customerId;
  final OrderStatus status;
  final String paymentMethod;
  final double totalAmount;
  final String? note;
  final DateTime createdAt;
  final DateTime updatedAt;
  final List<OrderLineItem> items;

  /// Customer contact, so a stall can call about a ready order. Only sent to
  /// the order's own customer, the owning vendor, or an admin.
  final String? customerName;
  final String? customerPhone;

  /// How this order is being handed over, and - for a delivery - where to.
  /// [deliveryLocationLabel] is the human name; the code is what the API takes.
  final FulfilmentType fulfilmentType;
  final String? deliveryLocation;
  final String? deliveryLocationLabel;

  const Order({
    required this.id,
    required this.vendorId,
    required this.customerId,
    required this.status,
    required this.paymentMethod,
    required this.totalAmount,
    required this.note,
    required this.createdAt,
    required this.updatedAt,
    required this.items,
    required this.customerName,
    required this.customerPhone,
    required this.fulfilmentType,
    required this.deliveryLocation,
    required this.deliveryLocationLabel,
  });

  bool get isDelivery => fulfilmentType == FulfilmentType.delivery;

  factory Order.fromJson(Map<String, dynamic> json) => Order(
        id: json['id'] as String,
        vendorId: json['vendor_id'] as String,
        customerId: json['customer_id'] as String,
        status: OrderStatus.fromJson(json['status'] as String),
        paymentMethod: json['payment_method'] as String,
        totalAmount: double.parse(json['total_amount'].toString()),
        note: json['note'] as String?,
        createdAt: DateTime.parse(json['created_at'] as String),
        updatedAt: DateTime.parse(json['updated_at'] as String),
        items: (json['items'] as List)
            .map((e) => OrderLineItem.fromJson(e as Map<String, dynamic>))
            .toList(),
        customerName: json['customer_name'] as String?,
        customerPhone: json['customer_phone'] as String?,
        // Defaulted, not required, so an order serialised by a server that
        // predates delivery still decodes.
        fulfilmentType: FulfilmentType.fromJson(
          (json['fulfilment_type'] as String?) ?? 'dine_in',
        ),
        deliveryLocation: json['delivery_location'] as String?,
        deliveryLocationLabel: json['delivery_location_label'] as String?,
      );
}
