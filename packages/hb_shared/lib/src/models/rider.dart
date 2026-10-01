/// One of a stall's riders, as the merchant's list shows them.
///
/// Has no password field, deliberately. Only [RiderCredentials] carries one, and
/// it is only ever built from the response that creates or regenerates a
/// password - so no amount of editing this class can start leaking one into a
/// list.
class Rider {
  final String id;
  final String loginId;
  final String displayName;
  final String phone;
  final bool isActive;
  final DateTime createdAt;

  const Rider({
    required this.id,
    required this.loginId,
    required this.displayName,
    required this.phone,
    required this.isActive,
    required this.createdAt,
  });

  factory Rider.fromJson(Map<String, dynamic> json) => Rider(
        id: json['id'] as String,
        loginId: json['login_id'] as String,
        displayName: json['display_name'] as String,
        phone: json['phone'] as String,
        isActive: json['is_active'] as bool,
        createdAt: DateTime.parse(json['created_at'] as String),
      );
}

/// A rider plus the one readable copy of their password.
///
/// Returned when a rider is created and when their password is regenerated, and
/// at no other time - the server stores only a hash. The merchant app shows it
/// once and tells them so; if nobody wrote it down, Regenerate issues another.
class RiderCredentials extends Rider {
  final String password;

  const RiderCredentials({
    required super.id,
    required super.loginId,
    required super.displayName,
    required super.phone,
    required super.isActive,
    required super.createdAt,
    required this.password,
  });

  factory RiderCredentials.fromJson(Map<String, dynamic> json) => RiderCredentials(
        id: json['id'] as String,
        loginId: json['login_id'] as String,
        displayName: json['display_name'] as String,
        phone: json['phone'] as String,
        isActive: json['is_active'] as bool,
        createdAt: DateTime.parse(json['created_at'] as String),
        password: json['password'] as String,
      );
}

/// What the rider app gets back when it signs in.
class RiderSession {
  final String accessToken;
  final Rider rider;

  /// Shown in the rider app so somebody who carries for more than one stall can
  /// see which account they are on.
  final String stallName;

  const RiderSession({
    required this.accessToken,
    required this.rider,
    required this.stallName,
  });

  factory RiderSession.fromJson(Map<String, dynamic> json) => RiderSession(
        accessToken: json['access_token'] as String,
        rider: Rider.fromJson(json['rider'] as Map<String, dynamic>),
        stallName: json['stall_name'] as String,
      );
}
