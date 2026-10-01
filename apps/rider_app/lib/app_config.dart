/// Backend base URL, including the `/api` namespace.
///
/// The API is served under /api so it can't collide with the customer web
/// app's client-side routes, which live on the same origin. Every path in
/// ApiClient is appended to this, so the prefix belongs here rather than in
/// each request.
///
/// Override at build/run time with:
///   flutter run --dart-define=API_BASE_URL=https://your-app.up.railway.app/api
class AppConfig {
  static const apiBaseUrl = String.fromEnvironment(
    'API_BASE_URL',
    defaultValue: 'http://localhost:8000/api',
  );
}
