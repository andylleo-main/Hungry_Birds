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
/// Routing it through [AndroidUsageType.alarm] puts it on the volume a phone
/// reserves for things that must wake somebody, which is what a new order is to
/// a stall during service. The cost is real and deliberate: this now makes
/// noise on a silenced phone. A stall that wants quiet has a Closed switch, and
/// that is the right control for it.
///
/// Everything here swallows its own failures. A device with no audio output, a
/// codec that will not open, an asset that failed to bundle - none of them
/// should stop a merchant seeing the order.
class NewOrderAlert {
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

  AudioPlayer? _player;

  bool get isRinging => _player != null;

  Future<void> start() async {
    if (_player != null) return;
    AudioPlayer? player;
    try {
      player = AudioPlayer();
      _player = player;
      await player.setAudioContext(_asAnAlarm);
      // Full volume explicitly. A player that inherited a lowered volume from
      // somewhere else would be the same failure as the media stream was:
      // working perfectly and inaudible.
      await player.setVolume(1);
      // Loops until stop(). A single chime is missable across a counter during
      // service, which is the only moment this matters.
      await player.setReleaseMode(ReleaseMode.loop);
      await player.play(AssetSource('sounds/new_order.wav'));
    } catch (e) {
      debugPrint('new order alert: could not play ($e)');
      _player = null;
      // Disposed rather than dropped. A failed start used to leak the player,
      // and each one holds a native player and a platform channel - so a run of
      // failures piled them up behind an app that looked merely quiet.
      try {
        await player?.dispose();
      } catch (_) {
        // Already gone, or never got far enough to exist.
      }
    }

    // Haptics as well as sound, because this is the part that still works on a
    // phone set to silent.
    try {
      await HapticFeedback.heavyImpact();
    } catch (_) {
      // A device with haptics off. Nothing to do and nothing worth logging.
    }
  }

  Future<void> stop() async {
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
}
