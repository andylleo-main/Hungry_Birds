import 'dart:async';

import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter/foundation.dart';
import 'package:hb_shared/hb_shared.dart';

/// Registers this phone to receive new-order notifications.
///
/// Push is a convenience, never a dependency: orders also arrive on the
/// WebSocket and on every queue fetch. So everything here is best-effort and
/// swallows its own failures - a stall whose notifications are broken still
/// takes orders, and one that cannot start Firebase at all still gets an app
/// that works.
class PushService {
  PushService(this._api);

  final ApiClient _api;

  String? _token;
  StreamSubscription<String>? _refreshes;
  bool _started = false;

  /// True once Firebase is up and a token has been handed to the server.
  bool get isRegistered => _token != null;

  /// Call after sign-in, when there is a vendor to attach the token to.
  ///
  /// Safe to call more than once: the server upserts on the token, and the
  /// listener below is only ever attached once.
  Future<void> start() async {
    try {
      if (!_started) {
        await Firebase.initializeApp();
        _started = true;
      }

      // Android 13+ refuses to show anything without this, and refuses
      // silently. iOS has always required it.
      final settings = await FirebaseMessaging.instance.requestPermission();
      if (settings.authorizationStatus == AuthorizationStatus.denied) {
        debugPrint('push: notifications denied by the user');
        return;
      }

      final token = await FirebaseMessaging.instance.getToken();
      if (token != null) await _register(token);

      // Firebase rotates a token on reinstall, on app data being cleared, and
      // occasionally on its own. Without this the stall simply stops getting
      // notifications one day, with nothing on screen to suggest why.
      _refreshes ??=
          FirebaseMessaging.instance.onTokenRefresh.listen(_register, onError: (_) {});
    } catch (e) {
      // A missing google-services.json, a device with no Play Services, a
      // network blip at startup. None of them should cost the merchant their
      // order queue.
      debugPrint('push: not available ($e)');
    }
  }

  Future<void> _register(String token) async {
    try {
      await _api.registerDevice(token);
      _token = token;
    } on ApiException catch (e) {
      debugPrint('push: the server refused this device (${e.message})');
    } catch (e) {
      debugPrint('push: could not register this device ($e)');
    }
  }

  /// Call before signing out, so this phone stops buzzing for a stall whose
  /// owner has handed the device on.
  ///
  /// Deliberately awaited by the caller before the token is cleared locally: if
  /// it fails, the stall's other devices are unaffected and the server prunes
  /// this one the first time Firebase reports it dead.
  Future<void> stop() async {
    final token = _token;
    _token = null;
    await _refreshes?.cancel();
    _refreshes = null;
    if (token == null) return;
    try {
      await _api.unregisterDevice(token);
    } catch (e) {
      debugPrint('push: could not unregister this device ($e)');
    }
  }
}
