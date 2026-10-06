import 'package:audioplayers/audioplayers.dart';

/// The four things the alarm needs a sound player to do.
///
/// A seam over audioplayers, for the same reason printer_transport.dart is one
/// over the Bluetooth plugin: there is no audio device where this is written, so
/// without it the only way to check the alarm's logic is to ship it and ask. The
/// start/stop race this exists to pin was intermittent on a real phone and
/// invisible in review.
abstract class RingPlayer {
  /// Audio attributes, volume and looping, before anything is played.
  Future<void> prepare(AudioContext? context);

  Future<void> play(String asset);

  Future<void> stop();

  Future<void> dispose();
}

/// The real one.
class AudioplayersRingPlayer implements RingPlayer {
  AudioplayersRingPlayer() : _player = AudioPlayer();

  final AudioPlayer _player;

  @override
  Future<void> prepare(AudioContext? context) async {
    if (context != null) await _player.setAudioContext(context);
    // Full volume explicitly. A player that inherited a lowered volume from
    // somewhere else would be the same failure the media stream was: working
    // perfectly and inaudible.
    await _player.setVolume(1);
    // Loops until stop(). The wav is one ring-ring-pause cadence, so looping it
    // is a phone that keeps ringing rather than a sound that happens once.
    await _player.setReleaseMode(ReleaseMode.loop);
  }

  @override
  Future<void> play(String asset) => _player.play(AssetSource(asset));

  @override
  Future<void> stop() => _player.stop();

  @override
  Future<void> dispose() => _player.dispose();
}
