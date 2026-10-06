import 'dart:async';

import 'package:audioplayers/audioplayers.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';

import 'ring_player.dart';

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
  NewOrderAlert({RingPlayer Function()? newPlayer})
      : _newPlayer = newPlayer ?? AudioplayersRingPlayer.new;

  /// How a player is made. Injectable so the start/stop race below can be
  /// exercised in a test, which is the only way it was ever going to be.
  final RingPlayer Function() _newPlayer;

  static const _sound = 'sounds/new_order.wav';

  /// What the chime plays as: a ringing phone, not a sound an app made.
  ///
  /// `gainTransientExclusive` is the ringtone part. It is what an incoming call
  /// asks for - everything else shuts up entirely rather than ducking under it -
  /// so a stall playing music on the counter phone gets silence and a ring,
  /// which is the whole point. `mayDuck`, which this used before, let the music
  /// keep going quietly underneath.
  ///
  /// `sonification` says this is functional rather than content, so it is not
  /// routed off to a paired speaker somebody left in a bag.
  ///
  /// The usage stays `alarm` rather than `notificationRingtone`, and that is
  /// deliberate. A true ringtone usage follows the ringer, which means silent
  /// mode silences it - and that was the original bug: a stall phone is on
  /// silent and the order arrives unheard. Alarm keeps it audible whatever the
  /// phone is set to. So: a ringtone's behaviour, on a volume that cannot be
  /// switched off by accident.
  static final AudioContext _likeARingingPhone = AudioContext(
    android: const AudioContextAndroid(
      isSpeakerphoneOn: false,
      stayAwake: true,
      contentType: AndroidContentType.sonification,
      usageType: AndroidUsageType.alarm,
      audioFocus: AndroidAudioFocus.gainTransientExclusive,
    ),
  );

  /// The buzz cadence, matched to the sound: two pulses, then a pause.
  ///
  /// Two together is what makes it read as a ring rather than a notification,
  /// and it lines up with the two tone bursts in the wav so the phone and the
  /// speaker are doing the same thing.
  ///
  /// This is also the half that does not depend on a codec, a volume setting or
  /// an audio focus request working. If the sound fails on some device nobody
  /// here can test, a phone on a steel counter still makes itself known.
  static const _ringEvery = Duration(seconds: 2);
  static const _betweenPulses = Duration(milliseconds: 420);

  RingPlayer? _player;
  Timer? _buzz;
  bool _starting = false;

  /// Bumped by every start and every stop, to settle the race between them.
  ///
  /// **This is the "sometimes it doesn't work properly".** Starting takes
  /// several awaits - set the context, set the volume, set the loop, play - and
  /// a merchant can tap "Got it" inside that window, which is exactly what
  /// somebody does when they are watching for the order. stop() would then find
  /// _player still null, conclude there was nothing to stop, and return; the
  /// play would land a moment later and set _player, leaving a ring nothing was
  /// going to turn off. The other order of events lost the sound entirely.
  ///
  /// Either way it depended on how fast the tap was, which is why it was
  /// intermittent. A start now checks it still owns the latest generation
  /// before keeping its player, and throws it away if it does not.
  int _generation = 0;

  /// What went wrong last time, in the platform's own words. Null if it played.
  String? lastProblem;

  /// Which route the sound took - the ringtone attributes, or the fallback.
  String? lastRoute;

  bool get isRinging => _player != null;

  Future<void> start() async {
    if (_player != null || _starting) return;
    _starting = true;
    final mine = ++_generation;
    lastProblem = null;
    lastRoute = null;

    // Buzzing starts first and does not depend on any of the below working.
    _startBuzzing();

    try {
      // Ringtone attributes first, because that is what was asked for and what
      // a stall phone has turned up. If the device refuses that usage, fall
      // back to an ordinary player rather than staying silent: quieter than
      // intended beats nothing, and the self-test says which one you got.
      if (await _tryPlay(_likeARingingPhone, 'ringtone volume', mine)) return;
      await _tryPlay(null, 'normal media volume', mine);
    } finally {
      _starting = false;
    }
  }

  Future<bool> _tryPlay(AudioContext? context, String route, int mine) async {
    RingPlayer? player;
    try {
      player = _newPlayer();
      await player.prepare(context);
      await player.play(_sound);

      if (mine != _generation) {
        // Stopped while this was starting. Keeping the player here is what left
        // a ring with nothing to turn it off.
        await player.stop();
        await player.dispose();
        return true; // handled: do not fall through to the other route
      }

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
    unawaited(_ringPulse());
    _buzz = Timer.periodic(_ringEvery, (_) => unawaited(_ringPulse()));
  }

  /// Two pulses close together, like a phone ringing.
  Future<void> _ringPulse() async {
    await _buzzOnce();
    await Future<void>.delayed(_betweenPulses);
    // Checked again: a two-part buzz must not outlive the order being seen.
    if (_buzz != null) await _buzzOnce();
  }

  Future<void> _buzzOnce() async {
    try {
      await HapticFeedback.heavyImpact();
    } catch (_) {
      // A device with haptics off. Nothing to do and nothing worth logging.
    }
  }

  Future<void> stop() async {
    // Invalidates any start still in flight, so its player is thrown away
    // instead of becoming a ring nobody can stop.
    _generation++;
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
