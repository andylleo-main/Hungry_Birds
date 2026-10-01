import 'package:flutter/material.dart';
import 'package:hb_shared/hb_shared.dart';
import 'package:provider/provider.dart';

import '../../state/auth_state.dart';
import '../../widgets/contact_details_sheet.dart';

class ProfileScreen extends StatelessWidget {
  const ProfileScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final auth = context.watch<AuthState>();
    final user = auth.currentUser;

    return Scaffold(
      appBar: AppBar(title: const Text('Profile')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Card(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Row(
                children: [
                  CircleAvatar(
                    radius: 26,
                    backgroundColor: AppTheme.primaryRed.withValues(alpha: 0.12),
                    child: Text(
                      (user?.email.characters.first ?? '?').toUpperCase(),
                      style: const TextStyle(
                        color: AppTheme.primaryRed,
                        fontWeight: FontWeight.w800,
                        fontSize: 20,
                      ),
                    ),
                  ),
                  const SizedBox(width: 14),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          user?.fullName ?? 'Campus foodie',
                          style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w700),
                        ),
                        const SizedBox(height: 2),
                        Text(
                          user?.email ?? '',
                          style: const TextStyle(color: AppTheme.textSecondary, fontSize: 13),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 16),
          Card(
            child: ListTile(
              leading: const Icon(Icons.phone_outlined, color: AppTheme.textSecondary),
              title: Text(
                user != null && user.hasPhone
                    ? '+91 ${formatPhoneForDisplay(user.phone!)}'
                    : 'Add a phone number',
                style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w600),
              ),
              subtitle: Text(
                user != null && user.hasPhone
                    ? 'Stalls call this number when your order is ready'
                    : 'Required before you can place an order',
                style: const TextStyle(fontSize: 12, color: AppTheme.textSecondary),
              ),
              trailing: const Icon(Icons.edit_outlined, size: 18),
              onTap: () => showContactDetailsSheet(
                context,
                title: 'Contact details',
                subtitle: 'Stalls use this to reach you about your order.',
              ),
            ),
          ),
          const SizedBox(height: 16),
          const Card(
            child: Padding(
              padding: EdgeInsets.all(16),
              child: Row(
                children: [
                  Icon(Icons.payments_outlined, color: AppTheme.textSecondary),
                  SizedBox(width: 12),
                  Expanded(
                    child: Text(
                      'Orders are paid online before the stall sees them. If a stall cannot '
                      'make your order, you are refunded automatically.',
                      style: TextStyle(fontSize: 13, color: AppTheme.textSecondary),
                    ),
                  ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 24),
          OutlinedButton.icon(
            onPressed: () => context.read<AuthState>().logout(),
            icon: const Icon(Icons.logout, size: 18),
            label: const Text('Log out'),
          ),
        ],
      ),
    );
  }
}
