import 'package:cached_network_image/cached_network_image.dart';
import 'package:flutter/material.dart';
import 'package:hb_shared/hb_shared.dart';
import 'package:image_picker/image_picker.dart';
import 'package:provider/provider.dart';

import '../services/cloudinary_uploader.dart';

class ItemEditorScreen extends StatefulWidget {
  final MenuItem? item;
  final List<MenuCategory> categories;

  const ItemEditorScreen({super.key, this.item, required this.categories});

  @override
  State<ItemEditorScreen> createState() => _ItemEditorScreenState();
}

class _ItemEditorScreenState extends State<ItemEditorScreen> {
  final _formKey = GlobalKey<FormState>();
  late final TextEditingController _nameController;
  late final TextEditingController _descriptionController;
  late final TextEditingController _priceController;
  late final TextEditingController _prepController;

  String? _categoryId;
  String? _imageUrl;
  bool _saving = false;
  bool _uploading = false;
  String? _error;

  bool get _isEditing => widget.item != null;

  /// Sizes this dish already has. Edited in place through its own section, so
  /// this is kept in state rather than read off widget.item each build.
  late List<MenuVariant> _variants;

  bool get _hasVariants => _variants.isNotEmpty;

  @override
  void initState() {
    super.initState();
    final item = widget.item;
    _nameController = TextEditingController(text: item?.name ?? '');
    _descriptionController = TextEditingController(text: item?.description ?? '');
    _priceController = TextEditingController(text: item?.price.toStringAsFixed(0) ?? '');
    _prepController = TextEditingController(text: item?.prepMinutes?.toString() ?? '');
    _categoryId = item?.categoryId;
    _imageUrl = item?.imageUrl;
    _variants = List.of(item?.variants ?? const []);
  }

  @override
  void dispose() {
    _nameController.dispose();
    _descriptionController.dispose();
    _priceController.dispose();
    _prepController.dispose();
    super.dispose();
  }

  Future<void> _pickImage() async {
    final picked = await ImagePicker().pickImage(source: ImageSource.gallery, maxWidth: 1200);
    if (picked == null || !mounted) return;

    setState(() => _uploading = true);
    try {
      final bytes = await picked.readAsBytes();
      if (!mounted) return;
      final url = await CloudinaryUploader(context.read<ApiClient>())
          .upload(bytes: bytes, filename: picked.name);
      if (!mounted) return;
      setState(() => _imageUrl = url);
    } on ApiException catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.message)));
    } finally {
      if (mounted) setState(() => _uploading = false);
    }
  }

  /// Take back a price change nobody has decided on yet.
  ///
  /// Here because a merchant who typed 2000 instead of 200 should not have to
  /// wait for a human to reject it before they can fix it.
  Future<void> _withdrawPrice() async {
    try {
      final item = await context.read<ApiClient>().withdrawItemPrice(widget.item!.id);
      if (!mounted) return;
      setState(() {
        _priceController.text = item.price.toStringAsFixed(0);
        _error = null;
      });
      ScaffoldMessenger.of(context)
        ..hideCurrentSnackBar()
        ..showSnackBar(const SnackBar(content: Text('Price change withdrawn')));
    } on ApiException catch (e) {
      if (mounted) setState(() => _error = e.message);
    }
  }

  /// Minutes typed into the prep field, or null for a blank one.
  int? get _prepMinutes => int.tryParse(_prepController.text.trim());

  Future<void> _save() async {
    if (!_formKey.currentState!.validate()) return;
    setState(() {
      _saving = true;
      _error = null;
    });

    final api = context.read<ApiClient>();
    final name = _nameController.text.trim();
    final description = _descriptionController.text.trim();
    // Null for a dish priced by its sizes - the field is not on screen, so
    // there is nothing to read and nothing to send.
    final price = _hasVariants ? null : double.tryParse(_priceController.text.trim());

    try {
      if (_isEditing) {
        await api.updateItem(
          widget.item!.id,
          name: name,
          description: description,
          categoryId: _categoryId,
          imageUrl: _imageUrl,
          // Saved right here with everything else, unlike price. A wrong prep
          // time costs a few minutes of goodwill and the merchant fixes it
          // themselves; a wrong price costs money, which is why only one of the
          // two waits on an admin.
          prepMinutes: _prepMinutes,
          clearPrepMinutes: _prepController.text.trim().isEmpty,
        );

        // Sent separately, and only when it actually moved.
        //
        // Two calls rather than one because they are two decisions: the fields
        // above take effect now, the price waits for an admin. They are not
        // atomic, so a failure here means "saved, but the price change did not
        // go through" - which is explainable, unlike a route whose `price` field
        // silently writes a different column.
        //
        // The diff is belt and braces: the server treats an unchanged price as a
        // no-op anyway, and that is the half that matters, because a merchant
        // phone running an older build cannot be made to stop sending it. This
        // half just means the merchant sees nothing happen rather than
        // "withdrawn" when they save an unrelated edit.
        if (!_hasVariants && price != null && price != widget.item!.price) {
          await api.setItemPrice(widget.item!.id, price);
        }
      } else {
        await api.createItem(
          name: name,
          description: description.isEmpty ? null : description,
          price: price ?? 0,
          categoryId: _categoryId,
          imageUrl: _imageUrl,
          prepMinutes: _prepMinutes,
        );
      }
      if (!mounted) return;
      Navigator.of(context).pop(true);
    } on ApiException catch (e) {
      setState(() => _error = e.message);
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  Future<void> _delete() async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Delete this item?'),
        content: const Text('Students will no longer see it on your menu.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Keep')),
          TextButton(onPressed: () => Navigator.pop(context, true), child: const Text('Delete')),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;

    try {
      await context.read<ApiClient>().deleteItem(widget.item!.id);
      if (!mounted) return;
      Navigator.of(context).pop(true);
    } on ApiException catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.message)));
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text(_isEditing ? 'Edit item' : 'New item'),
        actions: [
          if (_isEditing)
            IconButton(onPressed: _delete, icon: const Icon(Icons.delete_outline)),
        ],
      ),
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(16),
          child: Form(
            key: _formKey,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                _ImagePickerBox(
                  imageUrl: _imageUrl,
                  uploading: _uploading,
                  onTap: _uploading ? null : _pickImage,
                ),
                const SizedBox(height: 16),
                TextFormField(
                  controller: _nameController,
                  decoration: const InputDecoration(labelText: 'Item name'),
                  validator: (v) => (v?.trim().isEmpty ?? true) ? 'Enter an item name' : null,
                ),
                const SizedBox(height: 14),
                // Hidden once the dish has sizes, because the dish's own price
                // is ignored then - every order is priced by the size chosen.
                // Leaving an editable field that changes nothing is worse than
                // having no field at all.
                if (!_hasVariants) ...[
                  TextFormField(
                    controller: _priceController,
                    keyboardType: const TextInputType.numberWithOptions(decimal: true),
                    decoration: const InputDecoration(labelText: 'Price (₹)', prefixText: '₹ '),
                    validator: (v) {
                      final parsed = double.tryParse(v?.trim() ?? '');
                      if (parsed == null) return 'Enter a valid price';
                      if (parsed <= 0) return 'Price must be more than zero';
                      return null;
                    },
                  ),
                  if (_isEditing && widget.item!.priceAwaitingApproval)
                    Padding(
                      padding: const EdgeInsets.only(top: 8),
                      child: _PendingPriceNotice(
                        current: widget.item!.price,
                        proposed: widget.item!.pendingPrice!,
                        onWithdraw: _withdrawPrice,
                      ),
                    )
                  else if (_isEditing)
                    const Padding(
                      padding: EdgeInsets.only(top: 6),
                      child: Text(
                        'A new price has to be approved before students see it. '
                        'Yours keeps selling at the old one until then.',
                        style: TextStyle(fontSize: 12, color: AppTheme.textSecondary),
                      ),
                    ),
                  const SizedBox(height: 14),
                ],

                // Outside the !_hasVariants block on purpose: a dish priced by
                // its sizes still takes one amount of time to cook. Sizes change
                // what it costs, not how long the pan is on.
                TextFormField(
                  controller: _prepController,
                  keyboardType: TextInputType.number,
                  decoration: const InputDecoration(
                    labelText: 'Usually takes (minutes)',
                    suffixText: 'min',
                    helperText: 'Optional. Students see this on your menu.',
                  ),
                  validator: (v) {
                    final text = v?.trim() ?? '';
                    // Blank is a real answer - it means "I would rather not
                    // say", and the menu then shows nothing instead of a guess.
                    if (text.isEmpty) return null;
                    final parsed = int.tryParse(text);
                    if (parsed == null) return 'Whole minutes only';
                    if (parsed < 1) return 'At least a minute';
                    if (parsed > 240) return 'Four hours is the most';
                    return null;
                  },
                ),
                const Padding(
                  padding: EdgeInsets.only(top: 6),
                  child: Text(
                    'Saves straight away - no approval needed, unlike the price.',
                    style: TextStyle(fontSize: 12, color: AppTheme.textSecondary),
                  ),
                ),
                const SizedBox(height: 14),

                if (_isEditing) ...[
                  _SizesSection(
                    itemId: widget.item!.id,
                    variants: _variants,
                    onChanged: (next) => setState(() => _variants = next),
                  ),
                  const SizedBox(height: 14),
                ],
                DropdownButtonFormField<String?>(
                  initialValue: _categoryId,
                  decoration: const InputDecoration(labelText: 'Section'),
                  items: [
                    const DropdownMenuItem<String?>(value: null, child: Text('Uncategorised')),
                    for (final category in widget.categories)
                      DropdownMenuItem<String?>(value: category.id, child: Text(category.name)),
                  ],
                  onChanged: (value) => setState(() => _categoryId = value),
                ),
                const SizedBox(height: 14),
                TextFormField(
                  controller: _descriptionController,
                  maxLines: 3,
                  decoration: const InputDecoration(
                    labelText: 'Description (optional)',
                    hintText: 'e.g. 6 pcs, served with chutney',
                  ),
                ),
                if (_error != null) ...[
                  const SizedBox(height: 12),
                  Text(_error!, style: const TextStyle(color: AppTheme.primaryRed, fontSize: 13)),
                ],
                const SizedBox(height: 24),
                ElevatedButton(
                  onPressed: _saving ? null : _save,
                  child: _saving
                      ? const SizedBox(
                          height: 20,
                          width: 20,
                          child: CircularProgressIndicator(color: Colors.white, strokeWidth: 2.5),
                        )
                      : Text(_isEditing ? 'Save changes' : 'Add to menu'),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _ImagePickerBox extends StatelessWidget {
  final String? imageUrl;
  final bool uploading;
  final VoidCallback? onTap;

  const _ImagePickerBox({required this.imageUrl, required this.uploading, this.onTap});

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(14),
      child: Container(
        height: 170,
        decoration: BoxDecoration(
          color: AppTheme.divider,
          borderRadius: BorderRadius.circular(14),
        ),
        clipBehavior: Clip.antiAlias,
        child: uploading
            ? const Center(child: CircularProgressIndicator(color: AppTheme.primaryRed))
            : imageUrl == null
                ? const Center(
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Icon(Icons.add_a_photo_outlined, color: AppTheme.textSecondary),
                        SizedBox(height: 8),
                        Text(
                          'Add a photo',
                          style: TextStyle(color: AppTheme.textSecondary, fontSize: 13),
                        ),
                      ],
                    ),
                  )
                : CachedNetworkImage(imageUrl: imageUrl!, fit: BoxFit.cover, width: double.infinity),
      ),
    );
  }
}

/// Says a price is with the admin, and what students are paying meanwhile.
///
/// The second half is the part worth saying out loud: a merchant who changes a
/// price and sees nothing happen will assume it failed, when in fact the dish is
/// still selling perfectly well at the old number.
class _PendingPriceNotice extends StatelessWidget {
  const _PendingPriceNotice({
    required this.current,
    required this.proposed,
    required this.onWithdraw,
  });

  final double current;
  final double proposed;
  final Future<void> Function() onWithdraw;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.fromLTRB(12, 10, 12, 10),
      decoration: BoxDecoration(
        color: AppTheme.warning.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(8),
        border: const Border(left: BorderSide(color: AppTheme.warning, width: 4)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Icon(Icons.hourglass_top, size: 16, color: AppTheme.warning),
              const SizedBox(width: 6),
              Expanded(
                child: Text(
                  '₹${proposed.toStringAsFixed(0)} is waiting for approval',
                  style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w700),
                ),
              ),
            ],
          ),
          const SizedBox(height: 2),
          Text(
            'Students are still paying ₹${current.toStringAsFixed(0)}.',
            style: const TextStyle(fontSize: 12, color: AppTheme.textSecondary),
          ),
          Align(
            alignment: Alignment.centerLeft,
            child: TextButton(
              onPressed: onWithdraw,
              style: TextButton.styleFrom(padding: EdgeInsets.zero),
              child: const Text('Cancel this change'),
            ),
          ),
        ],
      ),
    );
  }
}

/// Add, rename, reprice and remove the sizes a dish comes in.
///
/// Saves each change immediately rather than on the parent form's Save, because
/// these are separate rows on the server and batching them would mean deciding
/// what to do when the third of five fails.
class _SizesSection extends StatefulWidget {
  const _SizesSection({
    required this.itemId,
    required this.variants,
    required this.onChanged,
  });

  final String itemId;
  final List<MenuVariant> variants;
  final ValueChanged<List<MenuVariant>> onChanged;

  @override
  State<_SizesSection> createState() => _SizesSectionState();
}

class _SizesSectionState extends State<_SizesSection> {
  bool _busy = false;

  void _say(String message) {
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(content: Text(message)));
  }

  Future<void> _run(Future<void> Function() work) async {
    setState(() => _busy = true);
    try {
      await work();
    } on ApiException catch (e) {
      _say(e.message);
    } catch (_) {
      _say("Couldn't reach the server. Try again.");
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _add() async {
    final entered = await _askForSize(context, title: 'Add a size');
    if (entered == null) return;
    await _run(() async {
      final created = await context.read<ApiClient>().createVariant(
            widget.itemId,
            name: entered.name,
            price: entered.price,
            sortOrder: widget.variants.length,
          );
      widget.onChanged([...widget.variants, created]);
    });
  }

  Future<void> _editPrice(MenuVariant variant) async {
    final entered = await _askForSize(
      context,
      title: 'Change the price of ${variant.name}',
      initialName: variant.name,
      initialPrice: variant.price,
      nameLocked: true,
    );
    if (entered == null || entered.price == variant.price) return;
    await _run(() async {
      final saved = await context
          .read<ApiClient>()
          .setVariantPrice(widget.itemId, variant.id, entered.price);
      widget.onChanged([
        for (final v in widget.variants) v.id == variant.id ? saved : v,
      ]);
      _say('Sent for approval. ${variant.name} still sells at '
          '₹${variant.price.toStringAsFixed(0)}.');
    });
  }

  Future<void> _toggle(MenuVariant variant) async {
    await _run(() async {
      final saved = await context.read<ApiClient>().updateVariant(
            widget.itemId,
            variant.id,
            isAvailable: !variant.isAvailable,
          );
      widget.onChanged([
        for (final v in widget.variants) v.id == variant.id ? saved : v,
      ]);
    });
  }

  Future<void> _remove(MenuVariant variant) async {
    final go = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text('Remove ${variant.name}?'),
        content: const Text(
          'Orders already placed keep the size they were ordered in. If this is '
          'the last size, the dish goes back to its own price.',
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Keep')),
          TextButton(onPressed: () => Navigator.pop(context, true), child: const Text('Remove')),
        ],
      ),
    );
    if (go != true) return;
    await _run(() async {
      await context.read<ApiClient>().deleteVariant(widget.itemId, variant.id);
      widget.onChanged([for (final v in widget.variants) if (v.id != variant.id) v]);
    });
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            const Text('Sizes', style: TextStyle(fontWeight: FontWeight.w800)),
            const Spacer(),
            TextButton.icon(
              onPressed: _busy ? null : _add,
              icon: const Icon(Icons.add, size: 18),
              label: const Text('Add a size'),
            ),
          ],
        ),
        if (widget.variants.isEmpty)
          const Text(
            'This dish is sold at one price. Add sizes if it comes in more than '
            'one - half and full, say - and students pick when they order.',
            style: TextStyle(fontSize: 12, color: AppTheme.textSecondary),
          )
        else
          for (final variant in widget.variants)
            Card(
              margin: const EdgeInsets.only(bottom: 6),
              child: ListTile(
                dense: true,
                title: Text(
                  variant.name,
                  style: TextStyle(
                    fontWeight: FontWeight.w700,
                    color: variant.isAvailable ? null : AppTheme.textSecondary,
                  ),
                ),
                subtitle: Text(
                  [
                    '₹${variant.price.toStringAsFixed(0)}',
                    if (!variant.isAvailable) 'sold out',
                    if (variant.priceAwaitingApproval)
                      '₹${variant.pendingPrice!.toStringAsFixed(0)} awaiting approval',
                  ].join(' · '),
                  style: const TextStyle(fontSize: 12),
                ),
                trailing: PopupMenuButton<String>(
                  enabled: !_busy,
                  onSelected: (choice) => switch (choice) {
                    'price' => _editPrice(variant),
                    'toggle' => _toggle(variant),
                    _ => _remove(variant),
                  },
                  itemBuilder: (context) => [
                    const PopupMenuItem(value: 'price', child: Text('Change price')),
                    PopupMenuItem(
                      value: 'toggle',
                      child: Text(variant.isAvailable ? 'Mark sold out' : 'Back on'),
                    ),
                    const PopupMenuItem(value: 'remove', child: Text('Remove')),
                  ],
                ),
              ),
            ),
      ],
    );
  }
}

/// What a size is called and what it costs.
class _SizeEntry {
  const _SizeEntry(this.name, this.price);
  final String name;
  final double price;
}

Future<_SizeEntry?> _askForSize(
  BuildContext context, {
  required String title,
  String? initialName,
  double? initialPrice,
  bool nameLocked = false,
}) async {
  final nameController = TextEditingController(text: initialName ?? '');
  final priceController =
      TextEditingController(text: initialPrice?.toStringAsFixed(0) ?? '');
  final formKey = GlobalKey<FormState>();

  try {
    return await showDialog<_SizeEntry>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text(title),
        content: Form(
          key: formKey,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextFormField(
                controller: nameController,
                enabled: !nameLocked,
                autofocus: !nameLocked,
                decoration: const InputDecoration(labelText: 'Name', hintText: 'Half'),
                validator: (v) =>
                    (v == null || v.trim().isEmpty) ? 'Give the size a name' : null,
              ),
              const SizedBox(height: 10),
              TextFormField(
                controller: priceController,
                autofocus: nameLocked,
                keyboardType: const TextInputType.numberWithOptions(decimal: true),
                decoration: const InputDecoration(labelText: 'Price (₹)', prefixText: '₹ '),
                validator: (v) {
                  final parsed = double.tryParse(v?.trim() ?? '');
                  if (parsed == null) return 'Enter a valid price';
                  if (parsed <= 0) return 'Price must be more than zero';
                  return null;
                },
              ),
            ],
          ),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context), child: const Text('Cancel')),
          TextButton(
            onPressed: () {
              if (!formKey.currentState!.validate()) return;
              Navigator.pop(
                context,
                _SizeEntry(
                  nameController.text.trim(),
                  double.parse(priceController.text.trim()),
                ),
              );
            },
            child: const Text('Save'),
          ),
        ],
      ),
    );
  } finally {
    nameController.dispose();
    priceController.dispose();
  }
}
