import 'package:flutter/material.dart';
import 'package:hb_shared/hb_shared.dart';
import 'package:provider/provider.dart';

import 'app_config.dart';
import 'screens/apply_screen.dart';
import 'screens/dashboard_screen.dart';
import 'screens/pending_approval_screen.dart';
import 'state/merchant_state.dart';

void main() {
  final authStorage = AuthStorage();
  final api = ApiClient(baseUrl: AppConfig.apiBaseUrl, authStorage: authStorage);

  runApp(
    MultiProvider(
      providers: [
        Provider<ApiClient>.value(value: api),
        ChangeNotifierProvider(create: (_) => MerchantState(api)..bootstrap()),
      ],
      child: const MerchantApp(),
    ),
  );
}

class MerchantApp extends StatelessWidget {
  const MerchantApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Hungry Birds Partner',
      debugShowCheckedModeBanner: false,
      theme: AppTheme.light(),
      home: const MerchantGate(),
    );
  }
}

class MerchantGate extends StatelessWidget {
  const MerchantGate({super.key});

  @override
  Widget build(BuildContext context) {
    final merchant = context.watch<MerchantState>();
    return switch (merchant.stage) {
      MerchantStage.loading => const SplashScreen(),
      MerchantStage.loggedOut => HbLoginScreen(
          api: context.read<ApiClient>(),
          logo: Icons.storefront,
          // Stall owners sign in on the vendor routes, which take any email
          // address - a stall is a business, and its address need not be an
          // institute one. Customers still need @bitmesra.ac.in.
          vendor: true,
          headline: 'Run your stall on Hungry Birds',
          subtitle: "Sign in with any email address. We'll send you a 6-digit code.",
          onVerified: merchant.onAuthenticated,
        ),
      MerchantStage.needsApplication => const ApplyScreen(),
      MerchantStage.awaitingApproval => const PendingApprovalScreen(),
      MerchantStage.ready => const DashboardScreen(),
    };
  }
}
