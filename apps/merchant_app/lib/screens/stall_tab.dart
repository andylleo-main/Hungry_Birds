import 'package:flutter/material.dart';
import 'package:hb_shared/hb_shared.dart';
import 'package:image_picker/image_picker.dart';
import 'package:provider/provider.dart';

import '../services/cloudinary_uploader.dart';
import '../services/printer.dart';
import '../state/merchant_state.dart';
import 'fulfilment_screen.dart';
import 'printer_screen.dart';
import 'set_password_screen.dart';

class StallTab extends StatefulWidget {
  const StallTab({super.key});

  @override
  State<StallTab> createState() => _StallTabState();
}

class _StallTabState extends State<StallTab> {
  bool _uploadingCover = false;

  Future<void> _editDetails() async {
    final merchant = context.read<MerchantState>();
    final nameController = TextEditingController(text: merchant.vendor?.stallName ?? '');
    final descriptionController = TextEditingController(text: merchant.vendor?.description ?? '');

    try {
      final saved = await showDialog<bool>(
        context: context,
        builder: (context) => AlertDialog(
          title: const Text('Stall details'),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextField(
                controller: nameController,
                autofocus: true,
                textCapitalization: TextCapitalization.words,
                decoration: const InputDecoration(labelText: 'Stall name'),
              ),
              const SizedBox(height: 12),
              TextField(
                controller: descriptionController,
                maxLines: 2,
                maxLength: 2000,
                decoration: const InputDecoration(labelText: 'Description'),
              ),
            ],
          ),
          actions: [
            TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Cancel')),
            TextButton(onPressed: () => Navigator.pop(context, true), child: const Text('Save')),
          ],
        ),
      );

      if (saved != true || !mounted) return;

      final name = nameController.text.trim();
      if (name.isEmpty) {
        // Caught here rather than sent on: the server rejects a blank name
        // with a 422, and "String should have at least 1 character" is not
        // something to show a stall owner.
        _say('Give your stall a name.');
        return;
      }

      await merchant.updateProfile(
        stallName: name,
        description: descriptionController.text.trim(),
      );
      if (mounted) _say('Stall details saved.');
    } on ApiException catch (e) {
      if (mounted) _say(e.message);
    } finally {
      // Every controller made in this method is disposed here, including on
      // the cancel and error paths.
      nameController.dispose();
      descriptionController.dispose();
    }
  }

  /// A one-line summary for the stall tab, so a merchant can see what they are
  /// accepting without opening the settings screen.
  String _servingSummary(Vendor? vendor) {
    final modes = [
      if (vendor?.dineInEnabled ?? true) 'Dine in',
      if (vendor?.deliveryEnabled ?? true) 'Delivery',
    ];
    return modes.isEmpty ? 'Not accepting orders' : modes.join(' · ');
  }

  void _say(String message) {
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(content: Text(message)));
  }

  /// Opens or closes the stall, and says so if it fails.
  ///
  /// This is the control a vendor reaches for when they run out of food or
  /// shut for the evening, so a failure that leaves the switch looking flipped
  /// while the stall is still taking orders is the worst outcome available.
  Future<void> _setOpen(bool value) async {
    try {
      await context.read<MerchantState>().setOpen(value);
      if (mounted) _say(value ? "You're open - students can order now." : "You're closed.");
    } on ApiException catch (e) {
      if (mounted) _say(e.message);
    } catch (_) {
      if (mounted) _say("Couldn't reach the server. Check your connection and try again.");
    }
  }

  Future<void> _changeCover() async {
    final picked = await ImagePicker().pickImage(source: ImageSource.gallery, maxWidth: 1600);
    if (picked == null || !mounted) return;

    setState(() => _uploadingCover = true);
    try {
      final bytes = await picked.readAsBytes();
      if (!mounted) return;
      final url = await CloudinaryUploader(context.read<ApiClient>())
          .upload(bytes: bytes, filename: picked.name);
      if (!mounted) return;
      await context.read<MerchantState>().updateProfile(coverImageUrl: url);
      if (mounted) _say('Cover photo updated.');
    } on ApiException catch (e) {
      if (mounted) _say(e.message);
    } catch (_) {
      if (mounted) _say("Couldn't upload that photo. Try again.");
    } finally {
      if (mounted) setState(() => _uploadingCover = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final merchant = context.watch<MerchantState>();
    final vendor = merchant.vendor;

    return Scaffold(
      appBar: AppBar(title: const Text('Your stall')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Card(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    vendor?.stallName ?? '',
                    style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w800),
                  ),
                  if (vendor?.description != null && vendor!.description!.isNotEmpty) ...[
                    const SizedBox(height: 6),
                    Text(
                      vendor.description!,
                      style: const TextStyle(color: AppTheme.textSecondary, fontSize: 14),
                    ),
                  ],
                  const SizedBox(height: 14),
                  Row(
                    children: [
                      OutlinedButton.icon(
                        onPressed: _editDetails,
                        icon: const Icon(Icons.edit_outlined, size: 18),
                        label: const Text('Edit'),
                      ),
                      const SizedBox(width: 10),
                      OutlinedButton.icon(
                        onPressed: _uploadingCover ? null : _changeCover,
                        icon: const Icon(Icons.image_outlined, size: 18),
                        label: Text(_uploadingCover ? 'Uploading…' : 'Cover photo'),
                      ),
                    ],
                  ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 16),
          Card(
            child: SwitchListTile(
              value: vendor?.isOpen ?? false,
              activeThumbColor: AppTheme.success,
              contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 6),
              secondary: Icon(
                (vendor?.isOpen ?? false) ? Icons.storefront : Icons.storefront_outlined,
                color: (vendor?.isOpen ?? false) ? AppTheme.success : AppTheme.textSecondary,
              ),
              title: const Text(
                'Accepting orders',
                style: TextStyle(fontWeight: FontWeight.w700),
              ),
              subtitle: Text(
                merchant.savingOpenState
                    ? 'Saving…'
                    : (vendor?.isOpen ?? false)
                        ? 'Students can order from you right now'
                        : 'Your stall shows as closed',
                style: const TextStyle(fontSize: 13),
              ),
              // Disabled mid-save so a double tap cannot queue two opposite
              // changes and leave the stall in whichever one happens to land
              // second.
              onChanged: merchant.savingOpenState ? null : (value) => _setOpen(value),
            ),
          ),
          const SizedBox(height: 16),
          Card(
            child: ListTile(
              leading: const Icon(Icons.delivery_dining_outlined),
              title: const Text('How you serve', style: TextStyle(fontWeight: FontWeight.w700)),
              subtitle: Text(
                _servingSummary(vendor),
                style: const TextStyle(fontSize: 13),
              ),
              trailing: const Icon(Icons.chevron_right),
              onTap: () => Navigator.of(context).push(
                MaterialPageRoute(builder: (_) => const FulfilmentScreen()),
              ),
            ),
          ),
          const SizedBox(height: 16),
          Card(
            child: ListTile(
              leading: const Icon(Icons.print_outlined),
              title: const Text('Ticket printer', style: TextStyle(fontWeight: FontWeight.w700)),
              subtitle: Text(
                context.watch<PrinterService>().savedName ?? 'Not set up',
                style: const TextStyle(fontSize: 13),
              ),
              trailing: const Icon(Icons.chevron_right),
              onTap: () => Navigator.of(context).push(
                MaterialPageRoute(builder: (_) => const PrinterScreen()),
              ),
            ),
          ),
          const SizedBox(height: 16),
          const Card(
            child: Padding(
              padding: EdgeInsets.all(16),
              child: Row(
                children: [
                  Icon(Icons.lock_outline, color: AppTheme.textSecondary),
                  SizedBox(width: 12),
                  Expanded(
                    child: Text(
                      'Most orders are paid online before you see them. A delivery can be paid '
                      'at the door instead - the card says which, and your rider collects. '
                      'Rejecting an order refunds it automatically.',
                      style: TextStyle(fontSize: 13, color: AppTheme.textSecondary),
                    ),
                  ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 16),
          Card(
            child: ListTile(
              leading: const Icon(Icons.lock_outline),
              title: const Text('Change password', style: TextStyle(fontWeight: FontWeight.w700)),
              subtitle: const Text(
                'Signs every other phone out of this stall',
                style: TextStyle(fontSize: 13),
              ),
              trailing: const Icon(Icons.chevron_right),
              onTap: () => Navigator.of(context).push(
                MaterialPageRoute(builder: (_) => const SetPasswordScreen(canCancel: true)),
              ),
            ),
          ),
          const SizedBox(height: 24),
          OutlinedButton.icon(
            onPressed: () => context.read<MerchantState>().logout(),
            icon: const Icon(Icons.logout, size: 18),
            label: const Text('Log out'),
          ),
        ],
      ),
    );
  }
}
