import 'package:audioplayers/audioplayers.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';

/// The noise a new order makes until somebody looks at it.
///
/// Deliberately on the ordinary media stream rather than the alarm stream, so a
/// phone set to silent stays silent. That is a product decision with a real cost
/// - a stall that leaves the phone face-down on silent hears nothing - and it is
/// why the popup that goes with this is full-screen and high-contrast rather
/// than a toast. The sound is the half that can be switched off; the dialog is
/// the half that cannot.
///
/// Everything here swallows its own failures. A device with no audio output, a
/// codec that will not open, an asset that failed to bundle - none of them
/// should stop a merchant seeing the order.
class NewOrderAlert {
  AudioPlayer? _player;

  bool get isRinging => _player != null;

  Future<void> start() async {
    if (_player != null) return;
    try {
      final player = AudioPlayer();
      _player = player;
      // Loops until stop(). A single chime is missable across a counter during
      // service, which is the only moment this matters.
      await player.setReleaseMode(ReleaseMode.loop);
      await player.play(AssetSource('sounds/new_order.wav'));
    } catch (e) {
      debugPrint('new order alert: could not play ($e)');
      _player = null;
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
