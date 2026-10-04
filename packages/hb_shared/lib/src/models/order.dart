import 'fulfilment.dart';

enum OrderStatus {
  /// Created but not paid for. No stall ever sees an order in this state, so it
  /// appears in the customer's own views only.
  awaitingPayment,
  placed,
  accepted,
  preparing,
  ready,
  outForDelivery,
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

  /// The value the API uses. Not [name]: Dart enum members are camelCase and the
  /// API is snake_case, so outForDelivery would otherwise be sent as
  /// "outForDelivery" and rejected - and read back as [unknown], which would
  /// look like a server problem rather than a client one.
  String get wire => switch (this) {
        OrderStatus.awaitingPayment => 'awaiting_payment',
        OrderStatus.placed => 'placed',
        OrderStatus.accepted => 'accepted',
        OrderStatus.preparing => 'preparing',
        OrderStatus.ready => 'ready',
        OrderStatus.outForDelivery => 'out_for_delivery',
        OrderStatus.completed => 'completed',
        OrderStatus.rejected => 'rejected',
        OrderStatus.cancelled => 'cancelled',
        OrderStatus.unknown => 'unknown',
      };

  static OrderStatus fromJson(String value) => OrderStatus.values.firstWhere(
        (e) => e.wire == value,
        orElse: () => OrderStatus.unknown,
      );

  String get label => switch (this) {
        OrderStatus.awaitingPayment => 'Payment pending',
        OrderStatus.placed => 'Order placed',
        OrderStatus.accepted => 'Accepted',
        OrderStatus.preparing => 'Preparing',
        OrderStatus.ready => 'Ready',
        OrderStatus.outForDelivery => 'Out for delivery',
        OrderStatus.completed => 'Completed',
        OrderStatus.rejected => 'Rejected',
        OrderStatus.cancelled => 'Cancelled',
        OrderStatus.unknown => 'Updated',
      };

  bool get isActive =>
      this == OrderStatus.awaitingPayment ||
      this == OrderStatus.placed ||
      this == OrderStatus.accepted ||
      this == OrderStatus.preparing ||
      this == OrderStatus.ready ||
      this == OrderStatus.outForDelivery ||
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

  /// "Half", "Full", or null for a dish with no sizes.
  ///
  /// Snapshotted like the name and price, so a ticket reprinted next week shows
  /// the size that was actually bought even if the stall has since renamed or
  /// removed it.
  final String? variantName;
  final double priceSnapshot;
  final int quantity;

  const OrderLineItem({
    required this.id,
    required this.menuItemId,
    required this.nameSnapshot,
    this.variantName,
    required this.priceSnapshot,
    required this.quantity,
  });

  factory OrderLineItem.fromJson(Map<String, dynamic> json) => OrderLineItem(
        id: json['id'] as String,
        menuItemId: json['menu_item_id'] as String?,
        nameSnapshot: json['name_snapshot'] as String,
        variantName: json['variant_name_snapshot'] as String?,
        priceSnapshot: double.parse(json['price_snapshot'].toString()),
        quantity: json['quantity'] as int,
      );
}

class Order {
  final String id;

  /// What a customer quotes when something goes wrong, and what gets printed on
  /// the stall's ticket. Format NNNNNN-RRRR, e.g. "014237-5096".
  ///
  /// [id] is still the identifier every API path is built from; this one exists
  /// to be read aloud and written down.
  final String orderNumber;

  /// The small number this stall calls across its counter: 1, 2, 3 and up,
  /// restarting each day.
  ///
  /// Null until the order is paid for and reaches the queue, and null on every
  /// order placed before tokens existed - so anything drawing it has to cope
  /// with its absence rather than assume a number.
  final int? tokenNumber;

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

  /// Who is carrying it. [riderPhone] is what the customer's call button dials,
  /// and both are null until the merchant assigns the order - so a rider's
  /// number never reaches a customer they are not delivering to.
  final String? riderId;
  final String? riderName;
  final String? riderPhone;

  /// The merchant is taking this one themselves.
  final bool selfDelivery;

  /// The four digits the customer reads out when their food arrives.
  ///
  /// Null in the rider app, always - the endpoints riders call return a payload
  /// without this field at all, which is the whole point. A rider who could read
  /// it could close an order without ever reaching the customer.
  final String? deliveryCode;

  const Order({
    required this.id,
    required this.orderNumber,
    // Optional because an order genuinely may not have one: it has not been
    // paid for yet, or it predates tokens. orderNumber stays required - every
    // order has one from birth, so a construction that cannot name it is a
    // construction that has lost track of which order it is talking about.
    this.tokenNumber,
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
    this.riderId,
    this.riderName,
    this.riderPhone,
    this.selfDelivery = false,
    this.deliveryCode,
  });

  /// True once somebody is carrying it, whether a rider or the merchant.
  bool get hasCourier => riderId != null || selfDelivery;

  bool get isDelivery => fulfilmentType == FulfilmentType.delivery;

  factory Order.fromJson(Map<String, dynamic> json) => Order(
        id: json['id'] as String,
        // Defaulted rather than required so an order serialised by a server
        // that predates order numbers still decodes instead of blanking the
        // whole queue - the same reason fulfilment_type is defaulted below.
        orderNumber: (json['order_number'] as String?) ?? '',
        tokenNumber: json['token_number'] as int?,
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
        riderId: json['rider_id'] as String?,
        riderName: json['rider_name'] as String?,
        riderPhone: json['rider_phone'] as String?,
        selfDelivery: (json['self_delivery'] as bool?) ?? false,
        deliveryCode: json['delivery_code'] as String?,
      );
}
