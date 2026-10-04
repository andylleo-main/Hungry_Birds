import 'dart:convert';

import 'package:http/http.dart' as http;

import '../models/fulfilment.dart';
import '../models/order.dart';
import '../models/rider.dart';
import '../models/user.dart';
import '../models/vendor.dart';
import '../models/analytics.dart';
import '../models/menu.dart';
import 'auth_storage.dart';
import 'api_exception.dart';

class OtpRequestResult {
  final String message;
  final String? debugCode;
  const OtpRequestResult(this.message, this.debugCode);
}

class AuthResult {
  final String accessToken;
  final String refreshToken;
  final AppUser user;
  const AuthResult(this.accessToken, this.refreshToken, this.user);
}

class UploadSignature {
  final String cloudName;
  final String apiKey;
  final int timestamp;
  final String signature;
  final String folder;

  const UploadSignature({
    required this.cloudName,
    required this.apiKey,
    required this.timestamp,
    required this.signature,
    required this.folder,
  });

  factory UploadSignature.fromJson(Map<String, dynamic> json) => UploadSignature(
        cloudName: json['cloud_name'] as String,
        apiKey: json['api_key'] as String,
        timestamp: json['timestamp'] as int,
        signature: json['signature'] as String,
        folder: json['folder'] as String,
      );
}

/// Talks to the Hungry Birds FastAPI backend. Handles JSON encode/decode,
/// bearer-token auth, and a single silent-refresh retry on a 401.
class ApiClient {
  final String baseUrl;
  final AuthStorage authStorage;
  final http.Client _client;

  ApiClient({required this.baseUrl, required this.authStorage, http.Client? client})
      : _client = client ?? http.Client();

  Uri _uri(String path, [Map<String, dynamic>? query]) =>
      Uri.parse('$baseUrl$path').replace(
        queryParameters: query?.map((k, v) => MapEntry(k, v.toString())),
      );

  Map<String, String> _headers({bool auth = true}) {
    final headers = {'Content-Type': 'application/json'};
    if (auth && authStorage.accessToken != null) {
      headers['Authorization'] = 'Bearer ${authStorage.accessToken}';
    }
    return headers;
  }

  Future<dynamic> _request(
    String method,
    String path, {
    Map<String, dynamic>? body,
    Map<String, dynamic>? query,
    bool auth = true,
    bool retrying = false,
  }) async {
    final uri = _uri(path, query);
    final headers = _headers(auth: auth);
    late http.Response response;

    switch (method) {
      case 'GET':
        response = await _client.get(uri, headers: headers);
        break;
      case 'POST':
        response = await _client.post(uri, headers: headers, body: jsonEncode(body ?? {}));
        break;
      case 'PUT':
        response = await _client.put(uri, headers: headers, body: jsonEncode(body ?? {}));
        break;
      case 'PATCH':
        response = await _client.patch(uri, headers: headers, body: jsonEncode(body ?? {}));
        break;
      case 'DELETE':
        response = await _client.delete(uri, headers: headers);
        break;
      default:
        // Reached before anything is sent, so a method missing from this switch
        // is not a failed request - it is a call that never happened. It then
        // surfaces as whatever the screen says for an unexpected error, which
        // is usually about the network. PUT was missing here and that is exactly
        // how it presented: every save on the fulfilment screen rolled its
        // switch back reporting a connection problem, on a working connection.
        throw ArgumentError('Unsupported method $method');
    }

    if (response.statusCode == 401 && auth && !retrying && authStorage.refreshToken != null) {
      final refreshed = await _tryRefresh();
      if (refreshed) {
        return _request(method, path, body: body, query: query, auth: auth, retrying: true);
      }
    }

    if (response.statusCode >= 200 && response.statusCode < 300) {
      if (response.body.isEmpty) return null;
      return jsonDecode(response.body);
    }

    String message = 'Something went wrong (${response.statusCode})';
    try {
      final decoded = jsonDecode(response.body);
      final detail = decoded is Map ? decoded['detail'] : null;
      if (detail is String) {
        message = detail;
      } else if (detail is List && detail.isNotEmpty) {
        // FastAPI reports validation failures as a list of objects. Printing
        // the list gives the vendor a blob of Python-looking punctuation, so
        // take the first message and name the field it belongs to.
        final first = detail.first;
        if (first is Map && first['msg'] != null) {
          final loc = first['loc'];
          final field = (loc is List && loc.isNotEmpty) ? loc.last.toString() : null;
          message = field == null ? '${first['msg']}' : '$field: ${first['msg']}';
        }
      } else if (detail != null) {
        message = detail.toString();
      }
    } catch (_) {
      // non-JSON error body, keep the generic message
    }
    throw ApiException(response.statusCode, message);
  }

  Future<bool> _tryRefresh() async {
    try {
      final uri = _uri('/auth/refresh');
      final response = await _client.post(
        uri,
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({'refresh_token': authStorage.refreshToken}),
      );
      if (response.statusCode != 200) {
        // Expired, revoked or replayed - none of which a retry fixes, so drop
        // the dead pair instead of sending it again on the next call.
        await authStorage.clear();
        return false;
      }
      final decoded = jsonDecode(response.body) as Map<String, dynamic>;
      // Both tokens, not just the access one. The server rotates the refresh
      // token on every use and treats the retired one as a replay - so keeping
      // the old value would make this client destroy its own session the next
      // time it refreshed.
      await authStorage.saveTokens(
        accessToken: decoded['access_token'] as String,
        refreshToken: decoded['refresh_token'] as String,
      );
      return true;
    } catch (_) {
      return false;
    }
  }

  // --- Auth ---

  /// Sends a stall owner a sign-in code, to any email address.
  ///
  /// Named for the audience because that is all it can do. The customer routes
  /// are institute-only and belong to the web app, which has its own client;
  /// nothing in Flutter signs a customer in any more. Keeping a `vendor` flag
  /// here that was only ever passed as true would suggest otherwise.
  Future<OtpRequestResult> requestVendorOtp(String email) async {
    final data = await _request(
      'POST',
      '/auth/vendor/otp/request',
      body: {'email': email},
      auth: false,
    ) as Map<String, dynamic>;
    return OtpRequestResult(data['message'] as String, data['debug_code'] as String?);
  }

  /// Exchanges a code for tokens, creating the account as a stall if it is new.
  ///
  /// The token this returns carries the merchant audience, which is the only
  /// kind the vendor endpoints accept.
  Future<AuthResult> verifyVendorOtp(String email, String code) async {
    final data = await _request(
      'POST',
      '/auth/vendor/otp/verify',
      body: {'email': email, 'code': code},
      auth: false,
    ) as Map<String, dynamic>;
    final result = AuthResult(
      data['access_token'] as String,
      data['refresh_token'] as String,
      AppUser.fromJson(data['user'] as Map<String, dynamic>),
    );
    await authStorage.saveTokens(accessToken: result.accessToken, refreshToken: result.refreshToken);
    return result;
  }

  Future<AppUser> me() async {
    final data = await _request('GET', '/auth/me') as Map<String, dynamic>;
    return AppUser.fromJson(data);
  }

  // --- Vendors ---

  Future<Vendor> applyAsVendor({required String stallName, String? description}) async {
    final data = await _request(
      'POST',
      '/vendors/apply',
      body: {'stall_name': stallName, if (description != null) 'description': description},
    ) as Map<String, dynamic>;
    return Vendor.fromJson(data);
  }

  // --- Fulfilment (vendor's own) ---

  Future<FulfilmentSettings> myFulfilment() async {
    final data = await _request('GET', '/vendors/me/fulfilment') as Map<String, dynamic>;
    return FulfilmentSettings.fromJson(data);
  }

  /// Replaces the stall's fulfilment settings wholesale.
  ///
  /// A full replacement rather than a diff, so the merchant's screen is the
  /// whole truth and two devices editing at once cannot interleave into a state
  /// neither of them chose.
  Future<FulfilmentSettings> updateFulfilment({
    required bool dineInEnabled,
    required bool deliveryEnabled,
    required List<String> enabledLocations,
  }) async {
    final data = await _request(
      'PUT',
      '/vendors/me/fulfilment',
      body: {
        'dine_in_enabled': dineInEnabled,
        'delivery_enabled': deliveryEnabled,
        'enabled_locations': enabledLocations,
      },
    ) as Map<String, dynamic>;
    return FulfilmentSettings.fromJson(data);
  }

  Future<Vendor> myVendor() async {
    final data = await _request('GET', '/vendors/me') as Map<String, dynamic>;
    return Vendor.fromJson(data);
  }

  Future<Vendor> updateMyVendor({
    String? stallName,
    String? description,
    String? coverImageUrl,
    bool? isOpen,
  }) async {
    final body = <String, dynamic>{};
    if (stallName != null) body['stall_name'] = stallName;
    if (description != null) body['description'] = description;
    if (coverImageUrl != null) body['cover_image_url'] = coverImageUrl;
    if (isOpen != null) body['is_open'] = isOpen;
    final data = await _request('PATCH', '/vendors/me', body: body) as Map<String, dynamic>;
    return Vendor.fromJson(data);
  }

  // --- Menu (vendor-owned) ---

  Future<List<MenuCategory>> myCategories() async {
    final data = await _request('GET', '/vendors/me/categories') as List;
    return data.map((e) => MenuCategory.fromJson(e as Map<String, dynamic>)).toList();
  }

  Future<MenuCategory> createCategory({required String name, int sortOrder = 0}) async {
    final data = await _request(
      'POST',
      '/vendors/me/categories',
      body: {'name': name, 'sort_order': sortOrder},
    ) as Map<String, dynamic>;
    return MenuCategory.fromJson(data);
  }

  Future<MenuCategory> updateCategory(
    String categoryId, {
    String? name,
    int? sortOrder,
  }) async {
    final body = <String, dynamic>{};
    if (name != null) body['name'] = name;
    if (sortOrder != null) body['sort_order'] = sortOrder;
    final data = await _request('PATCH', '/vendors/me/categories/$categoryId', body: body)
        as Map<String, dynamic>;
    return MenuCategory.fromJson(data);
  }

  Future<void> deleteCategory(String categoryId) =>
      _request('DELETE', '/vendors/me/categories/$categoryId');

  Future<List<MenuItem>> myItems() async {
    final data = await _request('GET', '/vendors/me/items') as List;
    return data.map((e) => MenuItem.fromJson(e as Map<String, dynamic>)).toList();
  }

  Future<MenuItem> createItem({
    required String name,
    String? description,
    required double price,
    String? categoryId,
    String? imageUrl,
  }) async {
    final data = await _request(
      'POST',
      '/vendors/me/items',
      body: {
        'name': name,
        if (description != null) 'description': description,
        'price': price,
        if (categoryId != null) 'category_id': categoryId,
        if (imageUrl != null) 'image_url': imageUrl,
      },
    ) as Map<String, dynamic>;
    return MenuItem.fromJson(data);
  }

  /// Everything about a dish except what it costs.
  ///
  /// `price` is deliberately not a parameter. Changing a price is a different
  /// decision with a different answer - it waits for an admin - so it has its
  /// own route. The server rejects a price sent here rather than ignoring it,
  /// so passing one would fail loudly rather than quietly do nothing.
  Future<MenuItem> updateItem(
    String itemId, {
    String? name,
    String? description,
    String? categoryId,
    String? imageUrl,
    bool? isAvailable,
  }) async {
    final body = <String, dynamic>{};
    if (name != null) body['name'] = name;
    if (description != null) body['description'] = description;
    if (categoryId != null) body['category_id'] = categoryId;
    if (imageUrl != null) body['image_url'] = imageUrl;
    if (isAvailable != null) body['is_available'] = isAvailable;
    final data = await _request('PATCH', '/vendors/me/items/$itemId', body: body)
        as Map<String, dynamic>;
    return MenuItem.fromJson(data);
  }

  /// Ask for a dish's price to change.
  ///
  /// Does not change what students pay. The number goes to an admin, and the
  /// dish keeps selling at its current price until they approve - so a stall
  /// whose price is under review is not a stall that has stopped selling.
  ///
  /// Sending the price it already has is a no-op server-side, and sending the
  /// old price while a change is pending withdraws that change.
  Future<MenuItem> setItemPrice(String itemId, double price) async {
    final data = await _request('PUT', '/vendors/me/items/$itemId/price', body: {'price': price})
        as Map<String, dynamic>;
    return MenuItem.fromJson(data);
  }

  /// Take back a price change nobody has decided on yet.
  Future<MenuItem> withdrawItemPrice(String itemId) async {
    final data =
        await _request('DELETE', '/vendors/me/items/$itemId/price') as Map<String, dynamic>;
    return MenuItem.fromJson(data);
  }

  Future<void> deleteItem(String itemId) => _request('DELETE', '/vendors/me/items/$itemId');

  // --- sizes ------------------------------------------------------------------

  /// Add a size. Its price goes live at once - adding is not gated, the same
  /// way adding a dish is not.
  Future<MenuVariant> createVariant(
    String itemId, {
    required String name,
    required double price,
    int sortOrder = 0,
  }) async {
    final data = await _request(
      'POST',
      '/vendors/me/items/$itemId/variants',
      body: {'name': name, 'price': price, 'sort_order': sortOrder},
    ) as Map<String, dynamic>;
    return MenuVariant.fromJson(data);
  }

  /// Rename, reorder or switch a size off. Not its price - see
  /// [setVariantPrice], which is gated exactly as a dish's price is.
  Future<MenuVariant> updateVariant(
    String itemId,
    String variantId, {
    String? name,
    int? sortOrder,
    bool? isAvailable,
  }) async {
    final body = <String, dynamic>{};
    if (name != null) body['name'] = name;
    if (sortOrder != null) body['sort_order'] = sortOrder;
    if (isAvailable != null) body['is_available'] = isAvailable;
    final data = await _request(
      'PATCH',
      '/vendors/me/items/$itemId/variants/$variantId',
      body: body,
    ) as Map<String, dynamic>;
    return MenuVariant.fromJson(data);
  }

  Future<MenuVariant> setVariantPrice(String itemId, String variantId, double price) async {
    final data = await _request(
      'PUT',
      '/vendors/me/items/$itemId/variants/$variantId/price',
      body: {'price': price},
    ) as Map<String, dynamic>;
    return MenuVariant.fromJson(data);
  }

  Future<void> deleteVariant(String itemId, String variantId) =>
      _request('DELETE', '/vendors/me/items/$itemId/variants/$variantId');

  /// This stall's own numbers. Scoped server-side by the signed-in stall, so
  /// there is no id to pass and none to tamper with.
  Future<VendorAnalytics> myAnalytics({int days = 30}) async {
    final data = await _request('GET', '/vendors/me/analytics', query: {'days': days})
        as Map<String, dynamic>;
    return VendorAnalytics.fromJson(data);
  }

  Future<UploadSignature> uploadSignature() async {
    final data = await _request('GET', '/media/signature') as Map<String, dynamic>;
    return UploadSignature.fromJson(data);
  }

  // --- Orders (the stall's queue) ---

  Future<List<Order>> vendorOrders() async {
    final data = await _request('GET', '/vendors/me/orders') as List;
    return data.map((e) => Order.fromJson(e as Map<String, dynamic>)).toList();
  }

  /// Sends a delivery out with a rider, or with the merchant themselves.
  ///
  /// Pass a [riderId] or set [selfDelivery]; passing both is refused. Passing
  /// neither un-assigns the order, which is what a merchant needs when a rider
  /// calls in sick after being given it.
  Future<Order> assignOrder(
    String orderId, {
    String? riderId,
    bool selfDelivery = false,
  }) async {
    final data = await _request(
      'POST',
      '/vendors/me/orders/$orderId/assign',
      body: {
        if (riderId != null) 'rider_id': riderId,
        'self_delivery': selfDelivery,
      },
    ) as Map<String, dynamic>;
    return Order.fromJson(data);
  }

  // --- Push notification devices (the merchant's own) ---

  /// Tells the server where to push this stall's new orders.
  ///
  /// Called on every app start, not only the first. Firebase rotates a
  /// registration token on reinstall, on app data being cleared, and sometimes
  /// unprompted; a stall whose token has quietly rotated would otherwise just
  /// stop being notified. The server upserts on the token, so repeating this is
  /// free.
  Future<void> registerDevice(String fcmToken, {String platform = 'android'}) async {
    await _request(
      'POST',
      '/vendors/me/devices',
      body: {'fcm_token': fcmToken, 'platform': platform},
    );
  }

  /// Stops pushing to this phone. Called on sign-out, so a device handed to
  /// somebody else does not keep buzzing for the old stall's orders.
  Future<void> unregisterDevice(String fcmToken) async {
    await _request('DELETE', '/vendors/me/devices/$fcmToken');
  }

  // --- Riders (the merchant's own) ---

  Future<List<Rider>> myRiders() async {
    final data = await _request('GET', '/vendors/me/riders') as List;
    return data.map((e) => Rider.fromJson(e as Map<String, dynamic>)).toList();
  }

  /// Adds a rider and returns the one readable copy of their password.
  ///
  /// The server stores only a hash, so this response is the only place the
  /// password ever exists. Show it, and say so.
  Future<RiderCredentials> createRider({
    required String displayName,
    required String phone,
    String? loginId,
  }) async {
    final data = await _request(
      'POST',
      '/vendors/me/riders',
      body: {
        'display_name': displayName,
        'phone': phone,
        if (loginId != null && loginId.isNotEmpty) 'login_id': loginId,
      },
    ) as Map<String, dynamic>;
    return RiderCredentials.fromJson(data);
  }

  Future<Rider> updateRider(
    String riderId, {
    String? displayName,
    String? phone,
    bool? isActive,
  }) async {
    final body = <String, dynamic>{};
    if (displayName != null) body['display_name'] = displayName;
    if (phone != null) body['phone'] = phone;
    if (isActive != null) body['is_active'] = isActive;
    final data =
        await _request('PATCH', '/vendors/me/riders/$riderId', body: body) as Map<String, dynamic>;
    return Rider.fromJson(data);
  }

  /// Issues a new password and returns it. This also signs the rider's current
  /// device out, which is the point when somebody has left.
  Future<RiderCredentials> regenerateRiderPassword(String riderId) async {
    final data = await _request('POST', '/vendors/me/riders/$riderId/password')
        as Map<String, dynamic>;
    return RiderCredentials.fromJson(data);
  }

  // --- The rider app ---

  /// Signs a rider in with the id and password their stall gave them.
  ///
  /// Stores the token without a refresh token, because rider sessions have no
  /// refresh flow: they last the shift, and regenerating the password is what
  /// ends one early.
  Future<RiderSession> riderLogin(String loginId, String password) async {
    final data = await _request(
      'POST',
      '/auth/rider/login',
      body: {'login_id': loginId, 'password': password},
      auth: false,
    ) as Map<String, dynamic>;
    final session = RiderSession.fromJson(data);
    await authStorage.saveAccessTokenOnly(session.accessToken);
    return session;
  }

  Future<Rider> riderMe() async {
    final data = await _request('GET', '/rider/me') as Map<String, dynamic>;
    return Rider.fromJson(data);
  }

  /// The orders this rider has been given, newest first. Polled while on shift.
  Future<List<Order>> riderOrders() async {
    final data = await _request('GET', '/rider/orders') as List;
    return data.map((e) => Order.fromJson(e as Map<String, dynamic>)).toList();
  }

  /// A rider marking an order picked up or delivered. Nothing else is accepted.
  ///
  /// [deliveryCode] is the four digits the customer reads out, and is required
  /// to complete a delivery. The rider app never receives it - it is typed in
  /// from what the customer says, which is what makes it proof of handover.
  Future<Order> riderUpdateOrderStatus(
    String orderId,
    OrderStatus status, {
    String? deliveryCode,
  }) async {
    final data = await _request(
      'PATCH',
      '/rider/orders/$orderId/status',
      body: {
        'status': status.wire,
        if (deliveryCode != null) 'delivery_code': deliveryCode,
      },
    ) as Map<String, dynamic>;
    return Order.fromJson(data);
  }

  /// Tells the server where to notify this rider about new deliveries.
  Future<void> registerRiderDevice(String fcmToken, {String platform = 'android'}) async {
    await _request(
      'POST',
      '/rider/devices',
      body: {'fcm_token': fcmToken, 'platform': platform},
    );
  }

  Future<void> unregisterRiderDevice(String fcmToken) async {
    await _request('DELETE', '/rider/devices/$fcmToken');
  }

  Future<Order> updateOrderStatus(String orderId, OrderStatus status) async {
    final data = await _request(
      'PATCH',
      '/vendors/me/orders/$orderId/status',
      body: {'status': status.wire},
    ) as Map<String, dynamic>;
    return Order.fromJson(data);
  }

  /// Ends this device's session on the server, then forgets it locally.
  ///
  /// Clearing local storage alone used to be the whole of "log out", which left
  /// the refresh token usable by anything that had a copy of it for another
  /// thirty days.
  Future<void> logout() async {
    final refresh = authStorage.refreshToken;
    await authStorage.clear();
    if (refresh == null) return;
    try {
      await _client.post(
        _uri('/auth/logout'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({'refresh_token': refresh}),
      );
    } catch (_) {
      // Offline: local state is already gone and the session expires on its
      // own, so failing the sign-out here would be worse than letting it pass.
    }
  }

  /// WebSocket URL for a vendor's live incoming-order queue.
  Future<Uri> vendorSocketUrl(String vendorId) => _wsUri('/ws/vendor/$vendorId');

  /// Builds a socket URL authorised by a single-use ticket.
  ///
  /// A WebSocket handshake carries no headers we can set, so the credential has
  /// to ride in the query string - and query strings end up in access logs,
  /// proxy logs and browser history. The access token therefore never goes
  /// there. It is spent once, over a normal authenticated request, on a ticket
  /// that is valid for 30 seconds and destroyed the moment the socket redeems
  /// it, so a copy found in a log later is worthless.
  Future<Uri> _wsUri(String path) async {
    final data = await _request('POST', '/realtime/ticket') as Map<String, dynamic>;
    final httpUri = _uri(path, {'ticket': data['ticket']});
    final scheme = httpUri.scheme == 'https' ? 'wss' : 'ws';
    return httpUri.replace(scheme: scheme);
  }
}
