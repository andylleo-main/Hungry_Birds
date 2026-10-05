import 'package:flutter/material.dart';
import 'package:hb_shared/hb_shared.dart';
import 'package:provider/provider.dart';

import 'app_config.dart';
import 'screens/apply_screen.dart';
import 'screens/dashboard_screen.dart';
import 'screens/merchant_login_screen.dart';
import 'screens/pending_approval_screen.dart';
import 'screens/set_password_screen.dart';
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

class MerchantGate extends StatefulWidget {
  const MerchantGate({super.key});

  @override
  State<MerchantGate> createState() => _MerchantGateState();
}

class _MerchantGateState extends State<MerchantGate> {
  /// Which of the two sign-in screens the signed-out stage is showing.
  ///
  /// Held here rather than pushed as a route so the gate can still swap the
  /// whole screen out the instant the stage changes, which is the reason the
  /// shared login screen is a widget and not a route in the first place. It
  /// resets on sign-out, so the next person starts at the password screen.
  bool _useEmailCode = false;

  @override
  Widget build(BuildContext context) {
    final merchant = context.watch<MerchantState>();

    if (merchant.stage != MerchantStage.loggedOut && _useEmailCode) {
      // Signed in since. Reset so signing out later lands on the password screen
      // rather than wherever the last person finished.
      _useEmailCode = false;
    }

    return switch (merchant.stage) {
      MerchantStage.loading => const SplashScreen(),
      MerchantStage.loggedOut => _useEmailCode
          ? HbLoginScreen(
              api: context.read<ApiClient>(),
              logo: Icons.storefront,
              headline: 'Run your stall on Hungry Birds',
              subtitle: "Sign in with any email address. We'll send you a 6-digit code.",
              onVerified: merchant.onAuthenticated,
            )
          : MerchantLoginScreen(
              onUseEmailCode: () => setState(() => _useEmailCode = true),
            ),
      // Before needsApplication on purpose: a new stall picks a password first,
      // so tomorrow does not start with waiting for an email.
      MerchantStage.needsPassword => const SetPasswordScreen(),
      MerchantStage.needsApplication => const ApplyScreen(),
      MerchantStage.awaitingApproval => const PendingApprovalScreen(),
      MerchantStage.ready => const DashboardScreen(),
    };
  }
}
