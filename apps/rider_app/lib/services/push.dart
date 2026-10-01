import 'dart:async';

import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
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
  StreamSubscription<RemoteMessage>? _foreground;
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

      _foreground ??= FirebaseMessaging.onMessage.listen(_alert, onError: (_) {});
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
    await _foreground?.cancel();
    _foreground = null;
    if (token == null) return;
    try {
      await _api.unregisterRiderDevice(token);
    } catch (e) {
      debugPrint('push: could not unregister this device ($e)');
    }
  }

  /// Make some noise for a message that arrives while the app is open.
  ///
  /// Android draws a notification itself only when the app is backgrounded or
  /// closed. In the foreground it hands the message to us and shows nothing, so
  /// without this the one case that stays completely silent is a rider with the
  /// app open in a pocket - which is most of a shift.
  ///
  /// Deliberately a buzz and a system tone rather than a drawn notification.
  /// Drawing one needs flutter_local_notifications, which brings core-library
  /// desugaring with it, and nothing here can be compiled or tested on the
  /// machine this was written on. The delivery list behind it is already kept
  /// current by the twelve-second poll, so the alert is the only thing missing -
  /// not the data.
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
