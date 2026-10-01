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

class MenuItem {
  final String id;
  final String name;
  final String? description;
  final double price;
  final String? categoryId;
  final String? imageUrl;
  final bool isAvailable;

  const MenuItem({
    required this.id,
    required this.name,
    required this.description,
    required this.price,
    required this.categoryId,
    required this.imageUrl,
    required this.isAvailable,
  });

  factory MenuItem.fromJson(Map<String, dynamic> json) => MenuItem(
        id: json['id'] as String,
        name: json['name'] as String,
        description: json['description'] as String?,
        price: double.parse(json['price'].toString()),
        categoryId: json['category_id'] as String?,
        imageUrl: json['image_url'] as String?,
        isAvailable: json['is_available'] as bool,
      );
}
