import 'package:flutter/material.dart';
import 'package:hb_shared/hb_shared.dart';
import 'package:provider/provider.dart';

import '../state/merchant_state.dart';

/// Choosing a password, after an email-code sign-in.
///
/// Shown as a gate for a stall that has none, and pushed from the Stall tab to
/// change one. The two cases differ only in whether there is a way out, which is
/// [canCancel].
///
/// Setting a password signs every other device out, including an old phone. That
/// is the point rather than a side effect - a password change that left the lost
/// handset signed in would achieve nothing - so the screen says so plainly
/// instead of letting it be a surprise.
class SetPasswordScreen extends StatefulWidget {
  const SetPasswordScreen({super.key, this.canCancel = false});

  /// False for the first-time gate: there is nowhere to go back to.
  final bool canCancel;

  @override
  State<SetPasswordScreen> createState() => _SetPasswordScreenState();
}

class _SetPasswordScreenState extends State<SetPasswordScreen> {
  final _password = TextEditingController();
  final _confirm = TextEditingController();
  final _formKey = GlobalKey<FormState>();

  bool _busy = false;
  bool _showPassword = false;
  String? _error;

  @override
  void dispose() {
    _password.dispose();
    _confirm.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (!(_formKey.currentState?.validate() ?? false)) return;

    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await context.read<MerchantState>().setPassword(_password.text);
      if (!mounted) return;
      if (widget.canCancel) {
        Navigator.of(context).pop();
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Password changed. Other devices were signed out.')),
        );
      }
      // Otherwise the gate in main.dart swaps this screen out by itself.
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
      appBar: widget.canCancel ? AppBar(title: const Text('Change password')) : null,
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
                  if (!widget.canCancel) ...[
                    const Icon(Icons.lock_outline, size: 52, color: AppTheme.primaryRed),
                    const SizedBox(height: 16),
                    const Text(
                      'Pick a password',
                      textAlign: TextAlign.center,
                      style: TextStyle(fontSize: 22, fontWeight: FontWeight.w800),
                    ),
                    const SizedBox(height: 6),
                    const Text(
                      'So you can sign in tomorrow without waiting for a code. '
                      'Forget it and you can always get back in with an email code.',
                      textAlign: TextAlign.center,
                      style: TextStyle(color: AppTheme.textSecondary, fontSize: 14),
                    ),
                    const SizedBox(height: 28),
                  ],

                  TextFormField(
                    controller: _password,
                    obscureText: !_showPassword,
                    textCapitalization: TextCapitalization.none,
                    autocorrect: false,
                    decoration: InputDecoration(
                      labelText: 'New password',
                      helperText: 'At least 8 characters',
                      prefixIcon: const Icon(Icons.lock_outline),
                      suffixIcon: IconButton(
                        onPressed: () => setState(() => _showPassword = !_showPassword),
                        icon: Icon(_showPassword ? Icons.visibility_off : Icons.visibility),
                      ),
                    ),
                    validator: (v) =>
                        (v ?? '').length >= 8 ? null : 'Use at least 8 characters',
                  ),
                  const SizedBox(height: 14),

                  TextFormField(
                    controller: _confirm,
                    obscureText: !_showPassword,
                    textCapitalization: TextCapitalization.none,
                    autocorrect: false,
                    onFieldSubmitted: (_) => _submit(),
                    decoration: const InputDecoration(
                      labelText: 'Type it again',
                      prefixIcon: Icon(Icons.lock_outline),
                    ),
                    // Checked here rather than left to a failed sign-in
                    // tomorrow, which is when a typo would otherwise surface.
                    validator: (v) =>
                        v == _password.text ? null : 'These two do not match',
                  ),

                  if (_error != null) ...[
                    const SizedBox(height: 14),
                    Text(
                      _error!,
                      style: const TextStyle(color: AppTheme.primaryRed, fontSize: 13),
                    ),
                  ],

                  const SizedBox(height: 10),
                  const Text(
                    'Any other phone signed in to this stall will be signed out.',
                    style: TextStyle(color: AppTheme.textSecondary, fontSize: 12),
                  ),

                  const SizedBox(height: 18),
                  SizedBox(
                    height: 50,
                    child: ElevatedButton(
                      onPressed: _busy ? null : _submit,
                      child: Text(_busy ? 'Saving…' : 'Save password'),
                    ),
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
