import 'package:audioplayers/audioplayers.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:merchant_app/services/new_order_alert.dart';
import 'package:merchant_app/services/ring_player.dart';

/// The alarm's behaviour around starting and stopping.
///
/// These exist because "it sometimes doesn't work properly" was a real race and
/// not a flaky device. Starting takes several awaits, and a merchant tapping
/// "Got it" inside that window is the normal case, not an edge one - they are
/// watching for the order. The old code lost the stop, left a ring nothing
/// would turn off, and did it only when the tap was fast enough, which is why
/// it looked intermittent.
class FakeRingPlayer implements RingPlayer {
  FakeRingPlayer(this.log, {this.failOnPlay = false, this.delay = Duration.zero});

  final List<String> log;
  final bool failOnPlay;

  /// Stands in for the platform taking a moment, which is the whole window the
  /// race lives in.
  final Duration delay;

  AudioContext? context;
  bool playing = false;
  bool disposed = false;

  @override
  Future<void> prepare(AudioContext? ctx) async {
    context = ctx;
    if (delay > Duration.zero) await Future<void>.delayed(delay);
    log.add('prepare');
  }

  @override
  Future<void> play(String asset) async {
    if (delay > Duration.zero) await Future<void>.delayed(delay);
    if (failOnPlay) {
      log.add('play-failed');
      throw Exception('no audio output');
    }
    playing = true;
    log.add('play');
  }

  @override
  Future<void> stop() async {
    playing = false;
    log.add('stop');
  }

  @override
  Future<void> dispose() async {
    disposed = true;
    log.add('dispose');
  }
}

void main() {
  test('a plain start rings, and reports the route it used', () async {
    final log = <String>[];
    late FakeRingPlayer made;
    final alert = NewOrderAlert(newPlayer: () => made = FakeRingPlayer(log));

    await alert.start();

    expect(alert.isRinging, isTrue);
    expect(made.playing, isTrue);
    expect(alert.lastRoute, 'ringtone volume');
    expect(alert.lastProblem, isNull);
    await alert.stop();
  });

  test('it asks for a ringtone, not a media sound', () async {
    // The point of the change: exclusive focus is what an incoming call takes,
    // so music on the counter phone stops rather than ducking under it.
    final log = <String>[];
    late FakeRingPlayer made;
    final alert = NewOrderAlert(newPlayer: () => made = FakeRingPlayer(log));

    await alert.start();

    final android = made.context!.android;
    expect(android.audioFocus, AndroidAudioFocus.gainTransientExclusive);
    expect(android.contentType, AndroidContentType.sonification);
    // Alarm rather than notificationRingtone on purpose: a true ringtone usage
    // follows the ringer, and a stall phone on silent is how this was inaudible
    // in the first place.
    expect(android.usageType, AndroidUsageType.alarm);
    await alert.stop();
  });

  test('stopping it stops the player', () async {
    final log = <String>[];
    late FakeRingPlayer made;
    final alert = NewOrderAlert(newPlayer: () => made = FakeRingPlayer(log));

    await alert.start();
    await alert.stop();

    expect(alert.isRinging, isFalse);
    expect(made.playing, isFalse);
    expect(made.disposed, isTrue);
  });

  test('a stop during a slow start does not leave a ring behind', () async {
    // **The intermittent bug.** stop() used to find _player still null, decide
    // there was nothing to stop, and return - and the play would land a moment
    // later with nothing holding a reference to turn it off.
    final log = <String>[];
    final players = <FakeRingPlayer>[];
    final alert = NewOrderAlert(
      newPlayer: () {
        final p = FakeRingPlayer(log, delay: const Duration(milliseconds: 40));
        players.add(p);
        return p;
      },
    );

    final starting = alert.start();
    await Future<void>.delayed(const Duration(milliseconds: 10));
    await alert.stop();
    await starting;

    expect(alert.isRinging, isFalse, reason: 'it was stopped before it started');
    expect(players, hasLength(1));
    expect(players.single.playing, isFalse, reason: 'the late player must be shut');
    expect(players.single.disposed, isTrue, reason: 'and thrown away, not leaked');
  });

  test('a stop mid-start does not fall through to the fallback player',
      () async {
    // Falling through would start a second player after the user had already
    // dismissed the order - the same bug wearing a different hat.
    final log = <String>[];
    final players = <FakeRingPlayer>[];
    final alert = NewOrderAlert(
      newPlayer: () {
        final p = FakeRingPlayer(log, delay: const Duration(milliseconds: 40));
        players.add(p);
        return p;
      },
    );

    final starting = alert.start();
    await Future<void>.delayed(const Duration(milliseconds: 10));
    await alert.stop();
    await starting;

    expect(players, hasLength(1), reason: 'exactly one player was ever made');
  });

  test('a start that fails falls back to an ordinary player', () async {
    final log = <String>[];
    final players = <FakeRingPlayer>[];
    var first = true;
    final alert = NewOrderAlert(
      newPlayer: () {
        final p = FakeRingPlayer(log, failOnPlay: first);
        first = false;
        players.add(p);
        return p;
      },
    );

    await alert.start();

    expect(players, hasLength(2));
    expect(alert.isRinging, isTrue);
    expect(alert.lastRoute, 'normal media volume');
    // The ringtone attempt is disposed rather than leaked.
    expect(players.first.disposed, isTrue);
    expect(players.last.context, isNull, reason: 'the fallback uses defaults');
    await alert.stop();
  });

  test('both routes failing is reported, and nothing is left running', () async {
    final log = <String>[];
    final players = <FakeRingPlayer>[];
    final alert = NewOrderAlert(
      newPlayer: () {
        final p = FakeRingPlayer(log, failOnPlay: true);
        players.add(p);
        return p;
      },
    );

    await alert.start();

    expect(alert.isRinging, isFalse);
    expect(alert.lastProblem, contains('no audio output'));
    expect(players.every((p) => p.disposed), isTrue);
    await alert.stop();
  });

  test('starting twice in a row only makes one player', () async {
    // _apply and a reload can both land on the same order within a second.
    final log = <String>[];
    final players = <FakeRingPlayer>[];
    final alert = NewOrderAlert(
      newPlayer: () {
        final p = FakeRingPlayer(log, delay: const Duration(milliseconds: 20));
        players.add(p);
        return p;
      },
    );

    await Future.wait([alert.start(), alert.start()]);

    expect(players, hasLength(1));
    await alert.stop();
  });

  test('stop, then start again, rings properly', () async {
    // A second order after the first was acknowledged. The generation counter
    // must not leave the new start thinking it has been superseded.
    final log = <String>[];
    final players = <FakeRingPlayer>[];
    final alert = NewOrderAlert(
      newPlayer: () {
        final p = FakeRingPlayer(log);
        players.add(p);
        return p;
      },
    );

    await alert.start();
    await alert.stop();
    await alert.start();

    expect(alert.isRinging, isTrue);
    expect(players.last.playing, isTrue);
    await alert.stop();
  });
}
