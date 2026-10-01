import 'package:shared_preferences/shared_preferences.dart';

/// Persists the JWT pair across app restarts using SharedPreferences (backed
/// by localStorage on web, plist/prefs files on iOS/Android). Not encrypted
/// at rest - acceptable for a campus-scale app with no payment data on
/// device; revisit with flutter_secure_storage if this ever needs to harden.
class AuthStorage {
  static const _accessKey = 'hb_access_token';
  static const _refreshKey = 'hb_refresh_token';

  String? _accessToken;
  String? _refreshToken;

  String? get accessToken => _accessToken;
  String? get refreshToken => _refreshToken;
  bool get isLoggedIn => _accessToken != null;

  Future<void> load() async {
    final prefs = await SharedPreferences.getInstance();
    _accessToken = prefs.getString(_accessKey);
    _refreshToken = prefs.getString(_refreshKey);
  }

  Future<void> saveTokens({required String accessToken, required String refreshToken}) async {
    _accessToken = accessToken;
    _refreshToken = refreshToken;
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_accessKey, accessToken);
    await prefs.setString(_refreshKey, refreshToken);
  }

  /// Stores a session that has no refresh token behind it.
  ///
  /// The rider app's token is like this: riders sign in at the start of a shift
  /// and their token simply lasts, with regenerating the password as the way to
  /// end it early. Clearing the refresh slot matters - ApiClient only attempts a
  /// refresh when one is present, so leaving a stale value from an earlier login
  /// would send the rider's 401 down a path that cannot work.
  Future<void> saveAccessTokenOnly(String accessToken) async {
    _accessToken = accessToken;
    _refreshToken = null;
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_accessKey, accessToken);
    await prefs.remove(_refreshKey);
  }

  Future<void> updateAccessToken(String accessToken) async {
    _accessToken = accessToken;
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_accessKey, accessToken);
  }

  Future<void> clear() async {
    _accessToken = null;
    _refreshToken = null;
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_accessKey);
    await prefs.remove(_refreshKey);
  }
}
