import 'dart:async';

import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
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
  StreamSubscription<RemoteMessage>? _foreground;
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

      _foreground ??= FirebaseMessaging.onMessage.listen(_alert, onError: (_) {});
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
    await _foreground?.cancel();
    _foreground = null;
    if (token == null) return;
    try {
      await _api.unregisterDevice(token);
    } catch (e) {
      debugPrint('push: could not unregister this device ($e)');
    }
  }

  /// Make some noise for a message that arrives while the app is open.
  ///
  /// Android draws a notification itself only when the app is backgrounded or
  /// closed. In the foreground it hands the message to us and shows nothing, so
  /// without this a phone sitting face-up on the counter with the app open is the
  /// one case that stays completely silent - which is close to the worst case,
  /// because that is exactly how a stall leaves it during service.
  ///
  /// Deliberately a buzz and a system tone rather than a drawn notification.
  /// Drawing one needs flutter_local_notifications, which brings core-library
  /// desugaring with it, and nothing here can be compiled or tested on the
  /// machine this was written on. The order queue list behind it is already live over
  /// the websocket, so the alert is the only thing missing - not the data.
  void _alert(RemoteMessage message) {
    debugPrint('push: foreground message ${message.data['type'] ?? '?'}');
    // Both are best-effort: a device with haptics switched off, or in silent
    // mode, simply does nothing here, and that must not throw.
    try {
      HapticFeedback.heavyImpact();
      SystemSound.play(SystemSoundType.alert);
    } catch (e) {
      debugPrint('push: could not alert ($e)');
    }
  }
}
