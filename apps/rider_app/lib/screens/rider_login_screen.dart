import 'package:flutter/material.dart';
import 'package:hb_shared/hb_shared.dart';
import 'package:provider/provider.dart';

import '../state/rider_state.dart';

/// Sign-in with the id and password the stall handed over.
///
/// Not the shared email-code screen the other two apps use: riders have no email
/// in this system and no inbox to check mid-shift. Their stall creates the
/// account and reads them the credentials.
class RiderLoginScreen extends StatefulWidget {
  const RiderLoginScreen({super.key});

  @override
  State<RiderLoginScreen> createState() => _RiderLoginScreenState();
}

class _RiderLoginScreenState extends State<RiderLoginScreen> {
  final _loginController = TextEditingController();
  final _passwordController = TextEditingController();
  final _formKey = GlobalKey<FormState>();

  bool _busy = false;
  bool _showPassword = false;
  String? _error;

  @override
  void dispose() {
    _loginController.dispose();
    _passwordController.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (!_formKey.currentState!.validate()) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await context.read<RiderState>().login(
            _loginController.text.trim(),
            _passwordController.text.trim(),
          );
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
            padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 32),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 420),
              child: Form(
                key: _formKey,
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Align(
                      alignment: Alignment.centerLeft,
                      child: Container(
                        width: 64,
                        height: 64,
                        decoration: BoxDecoration(
                          color: AppTheme.primaryRed,
                          borderRadius: BorderRadius.circular(18),
                        ),
                        child: const Icon(Icons.pedal_bike, color: Colors.white, size: 36),
                      ),
                    ),
                    const SizedBox(height: 24),
                    const Text(
                      'Hungry Birds Rider',
                      style: TextStyle(fontSize: 26, fontWeight: FontWeight.w800, height: 1.2),
                    ),
                    const SizedBox(height: 8),
                    const Text(
                      'Sign in with the login id and password your stall gave you.',
                      style: TextStyle(color: AppTheme.textSecondary, fontSize: 15),
                    ),
                    const SizedBox(height: 28),
                    TextFormField(
                      controller: _loginController,
                      autofocus: true,
                      autocorrect: false,
                      // Login ids are lowercase on the server, and a phone
                      // keyboard capitalises the first letter by default - which
                      // would turn every first attempt into a failure.
                      textCapitalization: TextCapitalization.none,
                      decoration: const InputDecoration(
                        labelText: 'Login id',
                        hintText: 'e.g. ravi-4821',
                        prefixIcon: Icon(Icons.badge_outlined),
                      ),
                      validator: (v) =>
                          (v == null || v.trim().isEmpty) ? 'Enter your login id' : null,
                      onFieldSubmitted: (_) => _submit(),
                    ),
                    const SizedBox(height: 14),
                    TextFormField(
                      controller: _passwordController,
                      obscureText: !_showPassword,
                      autocorrect: false,
                      textCapitalization: TextCapitalization.none,
                      decoration: InputDecoration(
                        labelText: 'Password',
                        hintText: 'e.g. swift-mango-4218',
                        prefixIcon: const Icon(Icons.lock_outline),
                        // Worth having: these passwords are three words and a
                        // number, typed one-handed, and a rider who cannot see
                        // what they typed just retries until they are locked out.
                        suffixIcon: IconButton(
                          onPressed: () => setState(() => _showPassword = !_showPassword),
                          icon: Icon(
                            _showPassword ? Icons.visibility_off_outlined : Icons.visibility_outlined,
                          ),
                        ),
                      ),
                      validator: (v) =>
                          (v == null || v.trim().isEmpty) ? 'Enter your password' : null,
                      onFieldSubmitted: (_) => _submit(),
                    ),
                    if (_error != null) ...[
                      const SizedBox(height: 12),
                      Text(
                        _error!,
                        style: const TextStyle(color: AppTheme.primaryRed, fontSize: 13),
                      ),
                    ],
                    const SizedBox(height: 20),
                    ElevatedButton(
                      onPressed: _busy ? null : _submit,
                      child: _busy
                          ? const SizedBox(
                              height: 18,
                              width: 18,
                              child: CircularProgressIndicator(
                                color: Colors.white,
                                strokeWidth: 2.4,
                              ),
                            )
                          : const Text('Sign in'),
                    ),
                    const SizedBox(height: 16),
                    const Text(
                      "Forgotten it? Ask your stall to make a new one - they can do "
                      'that from their app at any time.',
                      style: TextStyle(color: AppTheme.textSecondary, fontSize: 13),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}
