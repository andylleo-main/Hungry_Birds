class MenuCategory {
  final String id;
  final String name;
  final int sortOrder;

  const MenuCategory({required this.id, required this.name, required this.sortOrder});

  factory MenuCategory.fromJson(Map<String, dynamic> json) => MenuCategory(
        id: json['id'] as String,
        name: json['name'] as String,
        sortOrder: json['sort_order'] as int,
      );
}

/// One size of a dish: "Half" at 120, "Full" at 200.
///
/// A dish with no variants is priced by [MenuItem.price] and behaves exactly as
/// it did before sizes existed, which is most dishes.
class MenuVariant {
  final String id;
  final String name;

  /// What this size sells at today. A pending change does not touch it.
  final double price;

  final int sortOrder;

  /// Per size, because "Full is finished, Half is still on" is the ordinary
  /// case and the dish-level flag cannot say it.
  final bool isAvailable;

  /// The price the stall has asked to change to, still waiting on an admin.
  /// Readable, never writable: the server takes a proposed price on its own
  /// route and decides what to do with it.
  final double? pendingPrice;

  const MenuVariant({
    required this.id,
    required this.name,
    required this.price,
    this.sortOrder = 0,
    this.isAvailable = true,
    this.pendingPrice,
  });

  bool get priceAwaitingApproval => pendingPrice != null;

  factory MenuVariant.fromJson(Map<String, dynamic> json) => MenuVariant(
        id: json['id'] as String,
        name: json['name'] as String,
        price: double.parse(json['price'].toString()),
        sortOrder: (json['sort_order'] as int?) ?? 0,
        isAvailable: (json['is_available'] as bool?) ?? true,
        pendingPrice: json['pending_price'] == null
            ? null
            : double.parse(json['pending_price'].toString()),
      );
}

class MenuItem {
  final String id;
  final String name;
  final String? description;

  /// What the dish sells at today, and what an order placed right now pays.
  ///
  /// Ignored once the dish has sizes - see [priceFrom]. A pending price change
  /// does not touch this, which is the whole of the approval gate: the number a
  /// merchant proposes lives in [pendingPrice], and nothing that charges anybody
  /// reads that field.
  final double price;

  final String? categoryId;
  final String? imageUrl;
  final bool isAvailable;

  /// Empty for a dish with no sizes. Already ordered by the server.
  final List<MenuVariant> variants;

  /// The proposed price, waiting on an admin. Null when nothing is pending.
  final double? pendingPrice;

  const MenuItem({
    required this.id,
    required this.name,
    required this.description,
    required this.price,
    required this.categoryId,
    required this.imageUrl,
    required this.isAvailable,
    this.variants = const [],
    this.pendingPrice,
  });

  bool get priceAwaitingApproval => pendingPrice != null;

  bool get hasVariants => variants.isNotEmpty;

  /// What to put under the dish name: the cheapest size somebody can actually
  /// buy, or the dish's own price when it has none.
  ///
  /// A sold-out size is left out deliberately - advertising "from 120" when the
  /// only 120 is finished is a lie on the menu.
  double get priceFrom {
    final sellable = [
      for (final v in variants)
        if (v.isAvailable) v.price,
    ];
    if (sellable.isEmpty) return price;
    return sellable.reduce((a, b) => a < b ? a : b);
  }

  factory MenuItem.fromJson(Map<String, dynamic> json) => MenuItem(
        id: json['id'] as String,
        name: json['name'] as String,
        description: json['description'] as String?,
        price: double.parse(json['price'].toString()),
        categoryId: json['category_id'] as String?,
        imageUrl: json['image_url'] as String?,
        isAvailable: json['is_available'] as bool,
        // Defaulted rather than required, so an item serialised by a server
        // that predates sizes still decodes instead of throwing and taking the
        // whole menu with it. Same reasoning as fulfilment_type on Order.
        variants: [
          for (final v in (json['variants'] as List? ?? const []))
            MenuVariant.fromJson(v as Map<String, dynamic>),
        ],
        pendingPrice: json['pending_price'] == null
            ? null
            : double.parse(json['pending_price'].toString()),
      );
}
