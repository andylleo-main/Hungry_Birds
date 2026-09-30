import 'package:flutter/material.dart';
import 'package:hb_shared/hb_shared.dart';
import 'package:provider/provider.dart';

import 'item_editor_screen.dart';

class MenuTab extends StatefulWidget {
  const MenuTab({super.key});

  @override
  State<MenuTab> createState() => _MenuTabState();
}

class _MenuTabState extends State<MenuTab> {
  List<MenuCategory> _categories = [];
  List<MenuItem> _items = [];
  bool _loading = true;
  Object? _error;

  /// Items with a change in flight, so their row can show it and a second tap
  /// cannot race the first.
  final _busyItems = <String>{};

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() => _loading = true);
    try {
      final api = context.read<ApiClient>();
      final categories = await api.myCategories();
      final items = await api.myItems();
      if (!mounted) return;
      setState(() {
        _categories = categories;
        _items = items;
        _error = null;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() => _error = e);
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  void _say(String message) {
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(content: Text(message)));
  }

  /// Runs an API call, reports failure in words, and returns whether it worked.
  Future<bool> _attempt(Future<void> Function() action, {String? onSuccess}) async {
    try {
      await action();
      if (mounted && onSuccess != null) _say(onSuccess);
      return true;
    } on ApiException catch (e) {
      if (mounted) _say(e.message);
    } catch (_) {
      if (mounted) _say("Couldn't reach the server. Check your connection.");
    }
    return false;
  }

  Future<String?> _askForName({required String title, String? initial, String? hint}) async {
    final controller = TextEditingController(text: initial ?? '');
    try {
      return await showDialog<String>(
        context: context,
        builder: (context) => AlertDialog(
          title: Text(title),
          content: TextField(
            controller: controller,
            autofocus: true,
            maxLength: 255,
            textCapitalization: TextCapitalization.words,
            decoration: InputDecoration(hintText: hint),
            onSubmitted: (value) => Navigator.pop(context, value.trim()),
          ),
          actions: [
            TextButton(onPressed: () => Navigator.pop(context), child: const Text('Cancel')),
            TextButton(
              onPressed: () => Navigator.pop(context, controller.text.trim()),
              child: const Text('Save'),
            ),
          ],
        ),
      );
    } finally {
      // Disposed on every path, cancel included.
      controller.dispose();
    }
  }

  Future<bool> _confirm({
    required String title,
    required String message,
    String confirmLabel = 'Delete',
  }) async {
    final answer = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text(title),
        content: Text(message),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Cancel')),
          TextButton(
            onPressed: () => Navigator.pop(context, true),
            child: Text(confirmLabel, style: const TextStyle(color: AppTheme.primaryRed)),
          ),
        ],
      ),
    );
    return answer == true;
  }

  // --- sections -------------------------------------------------------------

  Future<void> _addCategory() async {
    final name = await _askForName(
      title: 'New section',
      hint: 'e.g. Momos, Beverages',
    );
    if (name == null || name.isEmpty || !mounted) return;

    final api = context.read<ApiClient>();
    if (await _attempt(
      () => api.createCategory(name: name, sortOrder: _categories.length),
      onSuccess: 'Section added.',
    )) {
      await _load();
    }
  }

  Future<void> _renameCategory(MenuCategory category) async {
    final name = await _askForName(title: 'Rename section', initial: category.name);
    if (name == null || name.isEmpty || name == category.name || !mounted) return;

    final api = context.read<ApiClient>();
    if (await _attempt(() => api.updateCategory(category.id, name: name))) {
      await _load();
    }
  }

  Future<void> _deleteCategory(MenuCategory category) async {
    final inSection = _items.where((i) => i.categoryId == category.id).length;
    if (!await _confirm(
      title: 'Delete "${category.name}"?',
      // Said plainly, because the answer decides whether they lose a dish.
      message: inSection == 0
          ? 'This section is empty, so nothing else is affected.'
          : '$inSection ${inSection == 1 ? 'item stays' : 'items stay'} on your menu and '
              'move to Uncategorised. Nothing is deleted.',
    )) {
      return;
    }
    if (!mounted) return;

    final api = context.read<ApiClient>();
    if (await _attempt(() => api.deleteCategory(category.id), onSuccess: 'Section deleted.')) {
      await _load();
    }
  }

  // --- items ----------------------------------------------------------------

  Future<void> _openEditor({MenuItem? item}) async {
    final changed = await Navigator.of(context).push<bool>(
      MaterialPageRoute(
        builder: (_) => ItemEditorScreen(item: item, categories: _categories),
      ),
    );
    if (changed == true) await _load();
  }

  /// Flips one item's availability, and only that item.
  ///
  /// The old version refetched the whole menu for a single switch, which made
  /// every flip jump the list and take a visible pause. The endpoint returns
  /// the updated item, so the row is replaced in place instead.
  Future<void> _toggleAvailability(MenuItem item) async {
    if (_busyItems.contains(item.id)) return;
    setState(() => _busyItems.add(item.id));

    final api = context.read<ApiClient>();
    try {
      final updated = await api.updateItem(item.id, isAvailable: !item.isAvailable);
      if (!mounted) return;
      setState(() {
        final index = _items.indexWhere((i) => i.id == updated.id);
        if (index != -1) _items[index] = updated;
      });
    } on ApiException catch (e) {
      if (mounted) _say(e.message);
    } catch (_) {
      if (mounted) _say("Couldn't reach the server. Check your connection.");
    } finally {
      if (mounted) setState(() => _busyItems.remove(item.id));
    }
  }

  Future<void> _deleteItem(MenuItem item) async {
    if (!await _confirm(
      title: 'Delete "${item.name}"?',
      message: 'It disappears from your menu for good. If you are only out of it '
          'for today, switch it to unavailable instead.',
    )) {
      return;
    }
    if (!mounted) return;

    final api = context.read<ApiClient>();
    if (await _attempt(() => api.deleteItem(item.id), onSuccess: '"${item.name}" deleted.')) {
      if (mounted) setState(() => _items.removeWhere((i) => i.id == item.id));
    }
  }

  // --- build ----------------------------------------------------------------

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Menu'),
        actions: [
          IconButton(
            onPressed: _addCategory,
            icon: const Icon(Icons.create_new_folder_outlined),
            tooltip: 'Add section',
          ),
        ],
      ),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: () => _openEditor(),
        backgroundColor: AppTheme.primaryRed,
        foregroundColor: Colors.white,
        icon: const Icon(Icons.add),
        label: const Text('Add item'),
      ),
      body: _buildBody(),
    );
  }

  Widget _buildBody() {
    if (_loading) {
      return const Center(child: CircularProgressIndicator(color: AppTheme.primaryRed));
    }
    if (_error != null) {
      return ErrorRetry(message: _error.toString(), onRetry: _load);
    }
    if (_items.isEmpty && _categories.isEmpty) {
      return const EmptyState(
        icon: Icons.restaurant_menu,
        title: 'No menu items yet',
        message: 'Add your first dish so students can order it.',
      );
    }

    final uncategorised = _items.where((i) => i.categoryId == null).toList();

    return RefreshIndicator(
      color: AppTheme.primaryRed,
      onRefresh: _load,
      child: ListView(
        padding: const EdgeInsets.fromLTRB(16, 8, 16, 90),
        children: [
          // Sections are listed even when empty, so a section that was just
          // created is visibly there and can be renamed or removed. The old
          // version hid them, which made adding one look like it had failed.
          for (final category in _categories)
            ..._section(
              title: category.name,
              items: _items.where((i) => i.categoryId == category.id).toList(),
              category: category,
            ),
          if (uncategorised.isNotEmpty)
            ..._section(title: 'Uncategorised', items: uncategorised),
        ],
      ),
    );
  }

  List<Widget> _section({
    required String title,
    required List<MenuItem> items,
    MenuCategory? category,
  }) {
    return [
      Padding(
        padding: const EdgeInsets.fromLTRB(0, 12, 0, 8),
        child: Row(
          children: [
            Expanded(
              child: Text(title, style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w800)),
            ),
            Text(
              '${items.length} ${items.length == 1 ? 'item' : 'items'}',
              style: const TextStyle(fontSize: 13, color: AppTheme.textSecondary),
            ),
            if (category != null)
              PopupMenuButton<String>(
                tooltip: 'Section options',
                icon: const Icon(Icons.more_vert, size: 20),
                onSelected: (choice) {
                  if (choice == 'rename') _renameCategory(category);
                  if (choice == 'delete') _deleteCategory(category);
                },
                itemBuilder: (_) => const [
                  PopupMenuItem(value: 'rename', child: Text('Rename section')),
                  PopupMenuItem(value: 'delete', child: Text('Delete section')),
                ],
              ),
          ],
        ),
      ),
      if (items.isEmpty)
        const Padding(
          padding: EdgeInsets.only(bottom: 10),
          child: Text(
            'Nothing here yet. Use "Add item" and pick this section.',
            style: TextStyle(fontSize: 13, color: AppTheme.textSecondary),
          ),
        ),
      for (final item in items) ...[
        _itemTile(item),
        const SizedBox(height: 10),
      ],
    ];
  }

  Widget _itemTile(MenuItem item) {
    final busy = _busyItems.contains(item.id);
    return Card(
      child: ListTile(
        contentPadding: const EdgeInsets.fromLTRB(14, 4, 4, 4),
        title: Text(
          item.name,
          style: TextStyle(
            fontWeight: FontWeight.w700,
            // A dish that is switched off is still on the menu but cannot be
            // ordered, so it reads as muted rather than missing.
            color: item.isAvailable ? null : AppTheme.textSecondary,
          ),
        ),
        subtitle: Text(
          item.isAvailable
              ? '₹${item.price.toStringAsFixed(0)}'
              : '₹${item.price.toStringAsFixed(0)} · unavailable',
          style: const TextStyle(fontSize: 13),
        ),
        trailing: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            if (busy)
              const Padding(
                padding: EdgeInsets.symmetric(horizontal: 14),
                child: SizedBox(
                  width: 18,
                  height: 18,
                  child: CircularProgressIndicator(strokeWidth: 2, color: AppTheme.primaryRed),
                ),
              )
            else
              Switch(
                value: item.isAvailable,
                activeThumbColor: AppTheme.success,
                onChanged: (_) => _toggleAvailability(item),
              ),
            PopupMenuButton<String>(
              tooltip: 'Item options',
              icon: const Icon(Icons.more_vert, size: 20),
              onSelected: (choice) {
                if (choice == 'edit') _openEditor(item: item);
                if (choice == 'delete') _deleteItem(item);
              },
              itemBuilder: (_) => const [
                PopupMenuItem(value: 'edit', child: Text('Edit item')),
                PopupMenuItem(value: 'delete', child: Text('Delete item')),
              ],
            ),
          ],
        ),
      ),
    );
  }
}
