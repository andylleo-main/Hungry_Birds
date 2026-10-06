import 'dart:async';

import 'package:audioplayers/audioplayers.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';

/// The noise a new order makes until somebody looks at it.
///
/// **On the alarm stream, not the media stream**, and that is a reversal. The
/// original decision was that a phone set to silent should stay silent, with
/// the full-screen dialog as the signal that could not be switched off. In a
/// kitchen that turned out to mean no signal at all: a stall phone sits with
/// its media volume at zero because nobody plays music on it, so the chime
/// played perfectly and was inaudible.
///
/// The cost is real and deliberate: this makes noise on a silenced phone. A
/// stall that wants quiet has a Closed switch, and that is the right control.
///
/// **Failures are recorded, not swallowed.** They used to go to debugPrint,
/// which on a release build goes nowhere - so "the alarm doesn't ring" was a
/// report with no way to act on it, and three guesses were spent on it. What
/// the platform actually said is now kept in [lastProblem] and shown by the
/// self-test on the Stall tab.
class NewOrderAlert {
  static const _sound = 'sounds/new_order.wav';

  /// What the chime plays as.
  ///
  /// `sonification` tells Android this is a functional sound rather than
  /// content, so it is not ducked for a notification or routed to a paired
  /// speaker somebody left in a bag. `gainTransientMayDuck` asks for focus
  /// without stopping whatever else is playing outright.
  static final AudioContext _asAnAlarm = AudioContext(
    android: const AudioContextAndroid(
      isSpeakerphoneOn: false,
      stayAwake: true,
      contentType: AndroidContentType.sonification,
      usageType: AndroidUsageType.alarm,
      audioFocus: AndroidAudioFocus.gainTransientMayDuck,
    ),
  );

  /// How often to buzz while an order is waiting.
  ///
  /// The half that does not depend on a codec, a volume setting or an audio
  /// focus request working. If the sound fails on some device nobody here can
  /// test, a phone on a steel counter still makes itself known.
  static const _buzzEvery = Duration(milliseconds: 1600);

  AudioPlayer? _player;
  Timer? _buzz;
  bool _starting = false;

  /// What went wrong last time, in the platform's own words. Null if it played.
  String? lastProblem;

  /// Which route the sound took - the alarm volume, or the ordinary one.
  String? lastRoute;

  bool get isRinging => _player != null;

  Future<void> start() async {
    if (_player != null || _starting) return;
    _starting = true;
    lastProblem = null;
    lastRoute = null;

    // Buzzing starts first and does not depend on any of the below working.
    _startBuzzing();

    try {
      // The alarm stream first, because that is the volume a stall phone
      // actually has turned up. If the device refuses that usage, fall back to
      // an ordinary player rather than staying silent: quieter than intended
      // beats nothing at all, and the self-test will say which one you got.
      if (await _tryPlay(_asAnAlarm, 'alarm volume')) return;
      await _tryPlay(null, 'normal media volume');
    } finally {
      _starting = false;
    }
  }

  Future<bool> _tryPlay(AudioContext? context, String route) async {
    AudioPlayer? player;
    try {
      player = AudioPlayer();
      if (context != null) await player.setAudioContext(context);
      // Full volume explicitly. A player that inherited a lowered volume from
      // somewhere else would be the same failure as the media stream was:
      // working perfectly and inaudible.
      await player.setVolume(1);
      // Loops until stop(). A single chime is missable across a counter during
      // service, which is the only moment this matters.
      await player.setReleaseMode(ReleaseMode.loop);
      await player.play(AssetSource(_sound));

      // Only now is it ringing. Setting _player before play() succeeded would
      // make isRinging lie, and the self-test is built on it.
      _player = player;
      lastRoute = route;
      return true;
    } catch (e) {
      lastProblem = 'On $route: $e';
      debugPrint('new order alert: $lastProblem');
      // Disposed rather than dropped. Each player holds a native player and a
      // platform channel, so a run of failures would pile them up behind an app
      // that looked merely quiet.
      try {
        await player?.dispose();
      } catch (_) {
        // Already gone, or never got far enough to exist.
      }
      return false;
    }
  }

  void _startBuzzing() {
    _buzz?.cancel();
    unawaited(_buzzOnce());
    _buzz = Timer.periodic(_buzzEvery, (_) => unawaited(_buzzOnce()));
  }

  Future<void> _buzzOnce() async {
    try {
      await HapticFeedback.heavyImpact();
    } catch (_) {
      // A device with haptics off. Nothing to do and nothing worth logging.
    }
  }

  Future<void> stop() async {
    _buzz?.cancel();
    _buzz = null;

    final player = _player;
    _player = null;
    if (player == null) return;
    try {
      await player.stop();
      await player.dispose();
    } catch (e) {
      debugPrint('new order alert: could not stop cleanly ($e)');
    }
  }

  /// Ring for a few seconds and say what happened, in words.
  ///
  /// Exists because the sound cannot be tested from where this is written, and
  /// "it doesn't ring" is otherwise a report with nothing actionable in it.
  /// Never throws: a self-check that can crash tells you less than no check.
  Future<String> selfTest() async {
    await stop();
    try {
      await start();
    } catch (e) {
      return 'It could not even be started: $e';
    }

    final playing = isRinging;
    final route = lastRoute;
    final problem = lastProblem;

    await Future<void>.delayed(const Duration(seconds: 3));
    await stop();

    if (playing) {
      return 'Played at $route for three seconds, and the phone buzzed.\n\n'
          'If you heard nothing, the sound is reaching Android and being '
          'turned down somewhere: check that volume on the phone, and that '
          'Do Not Disturb is off.';
    }
    return 'No sound. The phone buzzed instead.\n\n'
        '${problem ?? 'Android refused it without saying why.'}';
  }

  void dispose() {
    _buzz?.cancel();
    _buzz = null;
    unawaited(stop());
  }
}
