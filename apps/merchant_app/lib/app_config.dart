/// Backend base URL, including the `/api` namespace.
///
/// The API is served under /api so it can't collide with the customer web
/// app's client-side routes, which live on the same origin. Every path in
/// ApiClient is appended to this, so the prefix belongs here rather than in
/// each request.
///
/// The default is the live deployment, not localhost, and that is deliberate.
/// This value is a compile-time constant baked into the APK, so a release build
/// that forgets the flag is not a build that fails - it is a build that installs,
/// runs, and silently reaches nothing. Defaulting to localhost meant the quiet
/// failure was the easy mistake; defaulting to production means the worst a
/// forgotten flag does is point at the right server.
///
/// Working against a local backend is the case that now needs the flag:
///   flutter run --dart-define=API_BASE_URL=http://10.0.2.2:8000/api
/// (10.0.2.2 is how the Android emulator reaches the host's localhost; a real
/// device needs your machine's LAN address, and Android blocks cleartext HTTP
/// outside debug builds.)
///
/// scripts/build_apks.sh requires API_BASE_URL explicitly regardless, so a
/// release build never depends on this default being right.
class AppConfig {
  static const apiBaseUrl = String.fromEnvironment(
    'API_BASE_URL',
    defaultValue: 'https://www.hungrybirds.food/api',
  );

  /// Which build this is, as pubspec spells it - "1.4.1+9".
  ///
  /// Passed in by the build scripts, which already read it from pubspec.yaml to
  /// name the APK, so it cannot drift from the real version and there is no
  /// second place to remember to bump.
  ///
  /// Shown in the app because not knowing cost a whole round of debugging: a
  /// fix shipped, was tested against the previous APK, and reported as still
  /// broken. The build number is the one fact that makes a bug report mean
  /// something, and nobody should have to remember it.
  static const version = String.fromEnvironment(
    'APP_VERSION',
    // A build run straight from `flutter run` has no flag and is not a release.
    defaultValue: 'dev build',
  );
}
