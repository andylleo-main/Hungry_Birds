import 'dart:convert';

import 'package:http/http.dart' as http;

import '../models/order.dart';
import '../models/user.dart';
import '../models/vendor.dart';
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

/// Talks to the Hunger Birds FastAPI backend. Handles JSON encode/decode,
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
      case 'PATCH':
        response = await _client.patch(uri, headers: headers, body: jsonEncode(body ?? {}));
        break;
      case 'DELETE':
        response = await _client.delete(uri, headers: headers);
        break;
      default:
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
      if (decoded is Map && decoded['detail'] != null) {
        message = decoded['detail'].toString();
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
      if (response.statusCode != 200) return false;
      final decoded = jsonDecode(response.body) as Map<String, dynamic>;
      await authStorage.updateAccessToken(decoded['access_token'] as String);
      return true;
    } catch (_) {
      return false;
    }
  }

  // --- Auth ---

  Future<OtpRequestResult> requestOtp(String email) async {
    final data = await _request('POST', '/auth/otp/request', body: {'email': email}, auth: false)
        as Map<String, dynamic>;
    return OtpRequestResult(data['message'] as String, data['debug_code'] as String?);
  }

  Future<AuthResult> verifyOtp(String email, String code) async {
    final data = await _request(
      'POST',
      '/auth/otp/verify',
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

  /// Updates the signed-in user's own profile. Only the fields passed are
  /// changed. The backend normalizes the phone to E.164 and rejects invalid
  /// numbers, so the returned user is the source of truth.
  Future<AppUser> updateMe({String? fullName, String? phone}) async {
    final body = <String, dynamic>{};
    if (fullName != null) body['full_name'] = fullName;
    if (phone != null) body['phone'] = phone;
    final data = await _request('PATCH', '/auth/me', body: body) as Map<String, dynamic>;
    return AppUser.fromJson(data);
  }

  Future<void> logout() => authStorage.clear();

  // --- Vendors ---

  Future<List<Vendor>> listVendors() async {
    final data = await _request('GET', '/vendors') as List;
    return data.map((e) => Vendor.fromJson(e as Map<String, dynamic>)).toList();
  }

  Future<VendorDetail> vendorDetail(String vendorId) async {
    final data = await _request('GET', '/vendors/$vendorId') as Map<String, dynamic>;
    return VendorDetail.fromJson(data);
  }

  Future<Vendor> applyAsVendor({required String stallName, String? description}) async {
    final data = await _request(
      'POST',
      '/vendors/apply',
      body: {'stall_name': stallName, if (description != null) 'description': description},
    ) as Map<String, dynamic>;
    return Vendor.fromJson(data);
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

  Future<MenuItem> updateItem(
    String itemId, {
    String? name,
    String? description,
    double? price,
    String? categoryId,
    String? imageUrl,
    bool? isAvailable,
  }) async {
    final body = <String, dynamic>{};
    if (name != null) body['name'] = name;
    if (description != null) body['description'] = description;
    if (price != null) body['price'] = price;
    if (categoryId != null) body['category_id'] = categoryId;
    if (imageUrl != null) body['image_url'] = imageUrl;
    if (isAvailable != null) body['is_available'] = isAvailable;
    final data = await _request('PATCH', '/vendors/me/items/$itemId', body: body)
        as Map<String, dynamic>;
    return MenuItem.fromJson(data);
  }

  Future<void> deleteItem(String itemId) => _request('DELETE', '/vendors/me/items/$itemId');

  Future<UploadSignature> uploadSignature() async {
    final data = await _request('GET', '/media/signature') as Map<String, dynamic>;
    return UploadSignature.fromJson(data);
  }

  // --- Orders ---

  Future<Order> placeOrder({
    required String vendorId,
    required List<Map<String, dynamic>> items,
    String? note,
  }) async {
    final data = await _request(
      'POST',
      '/orders',
      body: {'vendor_id': vendorId, 'items': items, if (note != null) 'note': note},
    ) as Map<String, dynamic>;
    return Order.fromJson(data);
  }

  Future<List<Order>> myOrders() async {
    final data = await _request('GET', '/orders') as List;
    return data.map((e) => Order.fromJson(e as Map<String, dynamic>)).toList();
  }

  Future<Order> orderDetail(String orderId) async {
    final data = await _request('GET', '/orders/$orderId') as Map<String, dynamic>;
    return Order.fromJson(data);
  }

  Future<Order> cancelOrder(String orderId) async {
    final data = await _request('POST', '/orders/$orderId/cancel') as Map<String, dynamic>;
    return Order.fromJson(data);
  }

  Future<List<Order>> vendorOrders() async {
    final data = await _request('GET', '/vendors/me/orders') as List;
    return data.map((e) => Order.fromJson(e as Map<String, dynamic>)).toList();
  }

  Future<Order> updateOrderStatus(String orderId, OrderStatus status) async {
    final data = await _request(
      'PATCH',
      '/vendors/me/orders/$orderId/status',
      body: {'status': status.name},
    ) as Map<String, dynamic>;
    return Order.fromJson(data);
  }

  /// WebSocket URL for tracking a single order (customer or owning vendor).
  Uri orderSocketUrl(String orderId) => _wsUri('/ws/orders/$orderId');

  /// WebSocket URL for a vendor's live incoming-order queue.
  Uri vendorSocketUrl(String vendorId) => _wsUri('/ws/vendor/$vendorId');

  Uri _wsUri(String path) {
    final httpUri = _uri(path, {'token': authStorage.accessToken ?? ''});
    final scheme = httpUri.scheme == 'https' ? 'wss' : 'ws';
    return httpUri.replace(scheme: scheme);
  }
}
