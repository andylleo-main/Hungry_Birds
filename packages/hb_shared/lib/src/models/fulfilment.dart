/// How a stall hands food over, and where it will carry it.
enum FulfilmentType {
  dineIn,
  delivery,

  /// A mode this build does not know about. Decoded rather than thrown, for the
  /// same reason [OrderStatus] has one: a newer server must not be able to make
  /// a stall's order list disappear.
  unknown;

  String get wire => switch (this) {
        FulfilmentType.dineIn => 'dine_in',
        FulfilmentType.delivery => 'delivery',
        FulfilmentType.unknown => 'unknown',
      };

  String get label => switch (this) {
        FulfilmentType.dineIn => 'Dine in',
        FulfilmentType.delivery => 'Delivery',
        FulfilmentType.unknown => 'Other',
      };

  static FulfilmentType fromJson(String value) => switch (value) {
        'dine_in' => FulfilmentType.dineIn,
        'delivery' => FulfilmentType.delivery,
        _ => FulfilmentType.unknown,
      };
}

/// One campus drop-off point, and whether this stall delivers to it.
class DeliveryLocation {
  final String code;
  final String label;
  final bool enabled;

  const DeliveryLocation({
    required this.code,
    required this.label,
    required this.enabled,
  });

  factory DeliveryLocation.fromJson(Map<String, dynamic> json) => DeliveryLocation(
        code: json['code'] as String,
        label: json['label'] as String,
        enabled: json['enabled'] as bool,
      );

  DeliveryLocation copyWith({bool? enabled}) =>
      DeliveryLocation(code: code, label: label, enabled: enabled ?? this.enabled);
}

/// A stall's whole fulfilment configuration, as the settings screen sees it.
///
/// Every location in the catalogue is present, including the switched-off ones,
/// because the screen draws a switch per location and needs to know which are
/// off in order to draw them off.
class FulfilmentSettings {
  final bool dineInEnabled;
  final bool deliveryEnabled;

  /// The smallest delivery this stall will cook for. Zero means no minimum.
  ///
  /// Delivery only: there is nobody to send to somebody standing at the
  /// counter, so a stall with a minimum still sells one samosa across it.
  final double minDeliveryOrder;

  final List<DeliveryLocation> locations;

  const FulfilmentSettings({
    required this.dineInEnabled,
    required this.deliveryEnabled,
    required this.minDeliveryOrder,
    required this.locations,
  });

  factory FulfilmentSettings.fromJson(Map<String, dynamic> json) => FulfilmentSettings(
        dineInEnabled: json['dine_in_enabled'] as bool,
        deliveryEnabled: json['delivery_enabled'] as bool,
        // Via toString, like every other money field in these models: the
        // server sends a Decimal, which arrives as the string "100.00", and
        // `as double` on a string throws.
        //
        // Absent means zero, for a server that predates the field - the same
        // tolerance UpiQr gives its image bytes. An APK outlives any one deploy,
        // and a missing key must not be able to take the whole settings screen
        // down. Zero is also the safe guess: the server is the authority on the
        // figure and refuses a small delivery whatever this says, so erring
        // towards "no minimum" costs a clear refusal later rather than a stall
        // that cannot reach its own settings now.
        minDeliveryOrder:
            double.tryParse(json['min_delivery_order']?.toString() ?? '') ?? 0,
        locations: (json['locations'] as List)
            .map((e) => DeliveryLocation.fromJson(e as Map<String, dynamic>))
            .toList(),
      );

  List<String> get enabledCodes =>
      [for (final l in locations) if (l.enabled) l.code];

  bool get hasMinimum => minDeliveryOrder > 0;

  FulfilmentSettings copyWith({
    bool? dineInEnabled,
    bool? deliveryEnabled,
    double? minDeliveryOrder,
    List<DeliveryLocation>? locations,
  }) =>
      FulfilmentSettings(
        dineInEnabled: dineInEnabled ?? this.dineInEnabled,
        deliveryEnabled: deliveryEnabled ?? this.deliveryEnabled,
        minDeliveryOrder: minDeliveryOrder ?? this.minDeliveryOrder,
        locations: locations ?? this.locations,
      );
}
