import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../api/api_client.dart';
import '../api/api_exception.dart';
import '../theme/app_theme.dart';

enum _LoginStep { email, otp }

/// Stall owners' email-code sign-in.
///
/// Any email address: a stall is a business and its address need not be an
/// institute one. Customers are institute-only and sign in on the web app, which
/// has its own client - nothing in Flutter signs a customer in. This screen used
/// to switch between the two, and the customer half went with the retired
/// customer app.
///
/// Both steps live in one screen (rather than a pushed route) so the caller's
/// auth gate can swap this widget out the moment [onVerified] completes,
/// without a stale login route left on top of the navigator.
class HbLoginScreen extends StatefulWidget {
  final ApiClient api;
  final String headline;
  final String subtitle;
  final IconData logo;
  final Future<void> Function(AuthResult result) onVerified;

  const HbLoginScreen({
    super.key,
    required this.api,
    required this.headline,
    required this.subtitle,
    required this.onVerified,
    this.logo = Icons.flutter_dash,
  });

  @override
  State<HbLoginScreen> createState() => _HbLoginScreenState();
}

class _HbLoginScreenState extends State<HbLoginScreen> {
  final _emailController = TextEditingController();
  final _codeController = TextEditingController();
  final _formKey = GlobalKey<FormState>();

  _LoginStep _step = _LoginStep.email;
  bool _busy = false;
  String? _error;

  @override
  void dispose() {
    _emailController.dispose();
    _codeController.dispose();
    super.dispose();
  }

  String get _email => _emailController.text.trim();

  Future<void> _sendCode() async {
    if (!_formKey.currentState!.validate()) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final result = await widget.api.requestVendorOtp(_email);
      if (!mounted) return;
      setState(() {
        _step = _LoginStep.otp;
        // Populated only when the backend runs with OTP_DEBUG_ECHO (local dev
        // without a Resend key), so you can log in without checking email.
        if (result.debugCode != null) _codeController.text = result.debugCode!;
      });
    } on ApiException catch (e) {
      setState(() => _error = e.message);
    } catch (_) {
      setState(() => _error = "Couldn't reach the server. Check your connection.");
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _verify() async {
    final code = _codeController.text.trim();
    if (code.length != 6) {
      setState(() => _error = 'Enter the 6-digit code');
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final result = await widget.api.verifyVendorOtp(_email, code);
      await widget.onVerified(result);
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
              child: _step == _LoginStep.email ? _buildEmailStep() : _buildOtpStep(),
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildEmailStep() {
    return Form(
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
              child: Icon(widget.logo, color: Colors.white, size: 36),
            ),
          ),
          const SizedBox(height: 24),
          Text(
            widget.headline,
            style: const TextStyle(fontSize: 26, fontWeight: FontWeight.w800, height: 1.2),
          ),
          const SizedBox(height: 8),
          Text(
            widget.subtitle,
            style: const TextStyle(color: AppTheme.textSecondary, fontSize: 15),
          ),
          const SizedBox(height: 28),
          TextFormField(
            controller: _emailController,
            keyboardType: TextInputType.emailAddress,
            autocorrect: false,
            decoration: const InputDecoration(
              labelText: 'Email',
              hintText: 'you@example.com',
              prefixIcon: Icon(Icons.mail_outline),
            ),
            validator: (value) {
              final email = value?.trim().toLowerCase() ?? '';
              if (email.isEmpty) return 'Enter your email';
              if (!email.contains('@')) return 'Enter a valid email address';
              return null;
            },
            onFieldSubmitted: (_) => _sendCode(),
          ),
          if (_error != null) ...[
            const SizedBox(height: 12),
            Text(_error!, style: const TextStyle(color: AppTheme.primaryRed, fontSize: 13)),
          ],
          const SizedBox(height: 20),
          ElevatedButton(
            onPressed: _busy ? null : _sendCode,
            child: _busy ? const _ButtonSpinner() : const Text('Send code'),
          ),
        ],
      ),
    );
  }

  Widget _buildOtpStep() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Align(
          alignment: Alignment.centerLeft,
          child: IconButton(
            onPressed: _busy
                ? null
                : () => setState(() {
                      _step = _LoginStep.email;
                      _error = null;
                    }),
            icon: const Icon(Icons.arrow_back),
          ),
        ),
        const SizedBox(height: 8),
        const Text('Enter the code', style: TextStyle(fontSize: 26, fontWeight: FontWeight.w800)),
        const SizedBox(height: 8),
        Text(
          'Sent to $_email',
          style: const TextStyle(color: AppTheme.textSecondary, fontSize: 15),
        ),
        const SizedBox(height: 28),
        TextField(
          controller: _codeController,
          keyboardType: TextInputType.number,
          maxLength: 6,
          autofocus: true,
          textAlign: TextAlign.center,
          inputFormatters: [FilteringTextInputFormatter.digitsOnly],
          style: const TextStyle(fontSize: 28, fontWeight: FontWeight.w700, letterSpacing: 12),
          decoration: const InputDecoration(counterText: '', hintText: '000000'),
          onSubmitted: (_) => _verify(),
        ),
        if (_error != null) ...[
          const SizedBox(height: 8),
          Text(_error!, style: const TextStyle(color: AppTheme.primaryRed, fontSize: 13)),
        ],
        const SizedBox(height: 20),
        ElevatedButton(
          onPressed: _busy ? null : _verify,
          child: _busy ? const _ButtonSpinner() : const Text('Verify & continue'),
        ),
        const SizedBox(height: 12),
        TextButton(
          onPressed: _busy ? null : _sendCode,
          child: const Text('Resend code'),
        ),
      ],
    );
  }
}

class _ButtonSpinner extends StatelessWidget {
  const _ButtonSpinner();

  @override
  Widget build(BuildContext context) => const SizedBox(
        height: 20,
        width: 20,
        child: CircularProgressIndicator(color: Colors.white, strokeWidth: 2.5),
      );
}
