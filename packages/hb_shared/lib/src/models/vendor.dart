import 'fulfilment.dart';
import 'menu.dart';

class Vendor {
  final String id;
  final String stallName;
  final String? description;
  final String? coverImageUrl;
  final bool isApproved;
  final bool isOpen;
  /// What this stall will do. Flat booleans so a list of stalls can say
  /// "delivers" without fetching a location list for each one.
  final bool dineInEnabled;
  final bool deliveryEnabled;

  const Vendor({
    required this.id,
    required this.stallName,
    required this.description,
    required this.coverImageUrl,
    required this.isApproved,
    required this.isOpen,
    this.dineInEnabled = true,
    this.deliveryEnabled = true,
  });

  factory Vendor.fromJson(Map<String, dynamic> json) => Vendor(
        id: json['id'] as String,
        stallName: json['stall_name'] as String,
        description: json['description'] as String?,
        coverImageUrl: json['cover_image_url'] as String?,
        isApproved: json['is_approved'] as bool,
        isOpen: json['is_open'] as bool,
        dineInEnabled: (json['dine_in_enabled'] as bool?) ?? true,
        deliveryEnabled: (json['delivery_enabled'] as bool?) ?? true,
      );

  /// Used to move a switch before the server has answered, and to put it back
  /// if the server refuses. Only the fields a merchant can flip locally are
  /// here; everything else is whatever the server last said.
  Vendor copyWith({
    String? stallName,
    String? description,
    bool? isOpen,
    bool? dineInEnabled,
    bool? deliveryEnabled,
  }) =>
      Vendor(
        id: id,
        stallName: stallName ?? this.stallName,
        description: description ?? this.description,
        coverImageUrl: coverImageUrl,
        isApproved: isApproved,
        isOpen: isOpen ?? this.isOpen,
        dineInEnabled: dineInEnabled ?? this.dineInEnabled,
        deliveryEnabled: deliveryEnabled ?? this.deliveryEnabled,
      );
}

class VendorDetail extends Vendor {
  final List<CategoryWithItems> categories;
  final List<MenuItem> uncategorizedItems;

  /// Only the locations this stall actually delivers to. Offering a customer one
  /// it has switched off would invite a choice the server then rejects.
  final List<DeliveryLocation> deliveryLocations;

  const VendorDetail({
    required super.id,
    required super.stallName,
    required super.description,
    required super.coverImageUrl,
    required super.isApproved,
    required super.isOpen,
    super.dineInEnabled,
    super.deliveryEnabled,
    required this.categories,
    required this.uncategorizedItems,
    required this.deliveryLocations,
  });

  factory VendorDetail.fromJson(Map<String, dynamic> json) => VendorDetail(
        id: json['id'] as String,
        stallName: json['stall_name'] as String,
        description: json['description'] as String?,
        coverImageUrl: json['cover_image_url'] as String?,
        isApproved: json['is_approved'] as bool,
        isOpen: json['is_open'] as bool,
        dineInEnabled: (json['dine_in_enabled'] as bool?) ?? true,
        deliveryEnabled: (json['delivery_enabled'] as bool?) ?? true,
        deliveryLocations: ((json['delivery_locations'] as List?) ?? [])
            .map((e) => DeliveryLocation.fromJson(e as Map<String, dynamic>))
            .toList(),
        categories: (json['categories'] as List)
            .map((e) => CategoryWithItems.fromJson(e as Map<String, dynamic>))
            .toList(),
        uncategorizedItems: (json['uncategorized_items'] as List)
            .map((e) => MenuItem.fromJson(e as Map<String, dynamic>))
            .toList(),
      );

  /// All menu items on this vendor, flattened, for quick lookups (e.g. cart).
  List<MenuItem> get allItems => [
        for (final c in categories) ...c.items,
        ...uncategorizedItems,
      ];
}
