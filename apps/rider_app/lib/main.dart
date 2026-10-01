import 'package:flutter/material.dart';
import 'package:hb_shared/hb_shared.dart';
import 'package:provider/provider.dart';

import 'app_config.dart';
import 'screens/deliveries_screen.dart';
import 'screens/rider_login_screen.dart';
import 'state/rider_state.dart';

void main() {
  final api = ApiClient(baseUrl: AppConfig.apiBaseUrl, authStorage: AuthStorage());
  runApp(
    MultiProvider(
      providers: [
        Provider<ApiClient>.value(value: api),
        ChangeNotifierProvider(create: (_) => RiderState(api)..bootstrap()),
      ],
      child: const HungryBirdsRiderApp(),
    ),
  );
}

class HungryBirdsRiderApp extends StatelessWidget {
  const HungryBirdsRiderApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Hungry Birds Rider',
      debugShowCheckedModeBanner: false,
      theme: AppTheme.light(),
      home: const RiderGate(),
    );
  }
}

/// Picks the root screen from where the rider is.
///
/// The gate swaps the whole screen rather than pushing a route, so a sign-out -
/// including the involuntary one when a stall regenerates the password - cannot
/// leave a stale deliveries screen on top of the navigator.
class RiderGate extends StatelessWidget {
  const RiderGate({super.key});

  @override
  Widget build(BuildContext context) {
    return switch (context.watch<RiderState>().stage) {
      RiderStage.loading => const SplashScreen(),
      RiderStage.loggedOut => const RiderLoginScreen(),
      RiderStage.ready => const DeliveriesScreen(),
    };
  }
}
