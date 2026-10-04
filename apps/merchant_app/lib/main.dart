import 'package:flutter/material.dart';
import 'package:hb_shared/hb_shared.dart';
import 'package:provider/provider.dart';

import 'app_config.dart';
import 'screens/apply_screen.dart';
import 'screens/dashboard_screen.dart';
import 'screens/pending_approval_screen.dart';
import 'services/printer.dart';
import 'state/merchant_state.dart';

Future<void> main() async {
  // SharedPreferences needs the binding up before it can be touched, and the
  // printer settings are read below.
  WidgetsFlutterBinding.ensureInitialized();

  final authStorage = AuthStorage();
  final api = ApiClient(baseUrl: AppConfig.apiBaseUrl, authStorage: authStorage);

  // Loaded here rather than lazily in the orders screen: the first time a
  // merchant taps Print is during a rush, and a race between that tap and a
  // disk read would read as "no printer chosen" on a stall that chose one
  // weeks ago.
  final printer = PrinterService();
  await printer.load();

  runApp(
    MultiProvider(
      providers: [
        Provider<ApiClient>.value(value: api),
        ChangeNotifierProvider<PrinterService>.value(value: printer),
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
