enum UserRole {
  customer,
  vendor,
  admin;

  static UserRole fromJson(String value) => UserRole.values.firstWhere(
        (e) => e.name == value,
        orElse: () => UserRole.customer,
      );
}

class AppUser {
  final String id;
  final String email;
  final String? fullName;

  /// E.164, e.g. +919876543210. Null until the customer sets one; the backend
  /// refuses to accept an order without it so the stall can call about pickup.
  final String? phone;
  final UserRole role;

  const AppUser({
    required this.id,
    required this.email,
    required this.fullName,
    required this.phone,
    required this.role,
  });

  bool get hasPhone => phone != null && phone!.isNotEmpty;

  factory AppUser.fromJson(Map<String, dynamic> json) => AppUser(
        id: json['id'] as String,
        email: json['email'] as String,
        fullName: json['full_name'] as String?,
        phone: json['phone'] as String?,
        role: UserRole.fromJson(json['role'] as String),
      );
}
