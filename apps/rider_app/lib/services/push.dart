import 'dart:async';

import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter/foundation.dart';
import 'package:hb_shared/hb_shared.dart';

/// Registers this phone to be told when a stall assigns it a delivery.
///
/// Push is a convenience, never a dependency: the app polls the rider's
/// deliveries every twelve seconds while it is open, so a rider watching the
/// screen sees an assignment either way. This is for the phone in a pocket.
/// Everything here is best-effort and swallows its own failures - a rider whose
/// notifications are broken still has a working app.
class PushService {
  PushService(this._api);

  final ApiClient _api;

  String? _token;
  StreamSubscription<String>? _refreshes;
  bool _started = false;

  /// True once Firebase is up and a token has been handed to the server.
  bool get isRegistered => _token != null;

  /// Call after sign-in, when there is a rider session to attach the token to.
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
      // silently.
      final settings = await FirebaseMessaging.instance.requestPermission();
      if (settings.authorizationStatus == AuthorizationStatus.denied) {
        debugPrint('push: notifications denied by the user');
        return;
      }

      final token = await FirebaseMessaging.instance.getToken();
      if (token != null) await _register(token);

      // Firebase rotates a token on reinstall, on app data being cleared, and
      // occasionally on its own. Without this a rider simply stops being told
      // about assignments one day, with nothing on screen to suggest why.
      _refreshes ??=
          FirebaseMessaging.instance.onTokenRefresh.listen(_register, onError: (_) {});
    } catch (e) {
      // A missing google-services.json, a device with no Play Services, a
      // network blip at startup. None of them should cost the rider their
      // delivery list.
      debugPrint('push: not available ($e)');
    }
  }

  Future<void> _register(String token) async {
    try {
      await _api.registerRiderDevice(token);
      _token = token;
    } on ApiException catch (e) {
      debugPrint('push: the server refused this device (${e.message})');
    } catch (e) {
      debugPrint('push: could not register this device ($e)');
    }
  }

  /// Call before signing out, so a phone handed to the next rider on shift stops
  /// buzzing for deliveries that are no longer theirs.
  ///
  /// Awaited by the caller while the rider's token still works - unregistering
  /// is an authenticated call. If it fails the server prunes this device the
  /// first time Firebase reports the token dead.
  Future<void> stop() async {
    final token = _token;
    _token = null;
    await _refreshes?.cancel();
    _refreshes = null;
    if (token == null) return;
    try {
      await _api.unregisterRiderDevice(token);
    } catch (e) {
      debugPrint('push: could not unregister this device ($e)');
    }
  }
}
