import 'package:flutter/material.dart';
import 'package:hb_shared/hb_shared.dart';
import 'package:provider/provider.dart';

import '../state/merchant_state.dart';

/// Email and password, with the email code as the way back in.
///
/// Password first because this is opened at the start of a shift, often with one
/// hand, and waiting on an inbox to read a six-digit code is a poor way to begin
/// service. The code route is still here, one tap away, and doubles as the whole
/// of "forgot password" - sign in with a code, set a new one. There are no reset
/// links in this system and this screen is why none are needed.
///
/// Its own screen rather than an extra mode on the shared HbLoginScreen, the
/// same way the rider app has its own: that widget implements the code flow and
/// has already had one mode deleted from it.
class MerchantLoginScreen extends StatefulWidget {
  const MerchantLoginScreen({super.key, required this.onUseEmailCode});

  /// Switches to the email-code screen, for a first sign-in or a forgotten
  /// password.
  final VoidCallback onUseEmailCode;

  @override
  State<MerchantLoginScreen> createState() => _MerchantLoginScreenState();
}

class _MerchantLoginScreenState extends State<MerchantLoginScreen> {
  final _email = TextEditingController();
  final _password = TextEditingController();
  final _formKey = GlobalKey<FormState>();

  bool _busy = false;
  bool _showPassword = false;
  String? _error;

  @override
  void dispose() {
    _email.dispose();
    _password.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (!(_formKey.currentState?.validate() ?? false)) return;

    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await context
          .read<MerchantState>()
          .loginWithPassword(_email.text.trim(), _password.text);
      // No navigation: the gate in main.dart swaps this screen out the moment
      // the stage changes, so there is no stale login route left on top.
    } on ApiException catch (e) {
      if (mounted) setState(() => _error = e.message);
    } catch (_) {
      if (mounted) {
        setState(() => _error = "Couldn't reach the server. Check your connection.");
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(24),
            child: Form(
              key: _formKey,
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  const Icon(Icons.storefront, size: 56, color: AppTheme.primaryRed),
                  const SizedBox(height: 16),
                  const Text(
                    'Run your stall on Hungry Birds',
                    textAlign: TextAlign.center,
                    style: TextStyle(fontSize: 22, fontWeight: FontWeight.w800),
                  ),
                  const SizedBox(height: 6),
                  const Text(
                    'Sign in with the email and password you set up.',
                    textAlign: TextAlign.center,
                    style: TextStyle(color: AppTheme.textSecondary, fontSize: 14),
                  ),
                  const SizedBox(height: 28),

                  TextFormField(
                    controller: _email,
                    keyboardType: TextInputType.emailAddress,
                    // A phone keyboard capitalises the first letter by default,
                    // which would turn every first attempt into a failure.
                    textCapitalization: TextCapitalization.none,
                    autocorrect: false,
                    decoration: const InputDecoration(
                      labelText: 'Email',
                      prefixIcon: Icon(Icons.mail_outline),
                    ),
                    validator: (v) =>
                        (v ?? '').contains('@') ? null : 'Enter your email address',
                  ),
                  const SizedBox(height: 14),

                  TextFormField(
                    controller: _password,
                    obscureText: !_showPassword,
                    textCapitalization: TextCapitalization.none,
                    autocorrect: false,
                    onFieldSubmitted: (_) => _submit(),
                    decoration: InputDecoration(
                      labelText: 'Password',
                      prefixIcon: const Icon(Icons.lock_outline),
                      // Somebody who cannot see what they typed just retries
                      // until the rate limiter locks them out.
                      suffixIcon: IconButton(
                        onPressed: () => setState(() => _showPassword = !_showPassword),
                        icon: Icon(
                          _showPassword ? Icons.visibility_off : Icons.visibility,
                        ),
                      ),
                    ),
                    validator: (v) => (v ?? '').isEmpty ? 'Enter your password' : null,
                  ),

                  if (_error != null) ...[
                    const SizedBox(height: 14),
                    Text(
                      _error!,
                      style: const TextStyle(color: AppTheme.primaryRed, fontSize: 13),
                    ),
                  ],

                  const SizedBox(height: 22),
                  SizedBox(
                    height: 50,
                    child: ElevatedButton(
                      onPressed: _busy ? null : _submit,
                      child: Text(_busy ? 'Signing in…' : 'Sign in'),
                    ),
                  ),

                  const SizedBox(height: 10),
                  TextButton(
                    onPressed: _busy ? null : widget.onUseEmailCode,
                    child: const Text('Forgot it, or first time? Sign in with an email code'),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}
