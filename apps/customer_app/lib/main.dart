import 'package:flutter/material.dart';
import 'package:hb_shared/hb_shared.dart';
import 'package:provider/provider.dart';

import 'app_config.dart';
import 'screens/home/main_shell.dart';
import 'state/auth_state.dart';
import 'state/cart_state.dart';

void main() {
  final authStorage = AuthStorage();
  final api = ApiClient(baseUrl: AppConfig.apiBaseUrl, authStorage: authStorage);

  runApp(
    MultiProvider(
      providers: [
        Provider<ApiClient>.value(value: api),
        ChangeNotifierProvider(create: (_) => AuthState(api)..bootstrap()),
        ChangeNotifierProvider(create: (_) => CartState()),
      ],
      child: const HungryBirdsApp(),
    ),
  );
}

class HungryBirdsApp extends StatelessWidget {
  const HungryBirdsApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Hungry Birds',
      debugShowCheckedModeBanner: false,
      theme: AppTheme.light(),
      home: const AuthGate(),
    );
  }
}

class AuthGate extends StatelessWidget {
  const AuthGate({super.key});

  @override
  Widget build(BuildContext context) {
    final auth = context.watch<AuthState>();
    return switch (auth.status) {
      AuthStatus.unknown => const SplashScreen(),
      AuthStatus.loggedOut => HbLoginScreen(
          api: context.read<ApiClient>(),
          headline: 'Order from your campus stalls',
          subtitle: "Sign in with your BIT Mesra email. We'll send you a 6-digit code.",
          onVerified: auth.applyAuthResult,
        ),
      AuthStatus.loggedIn => const MainShell(),
    };
  }
}
