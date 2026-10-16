import 'package:flutter/material.dart';

import '../models.dart';
import '../state.dart';
import 'common.dart';

final _listName = RegExp(r'^[a-z0-9][a-z0-9_-]{0,39}$');

class BlockListsScreen extends StatefulWidget {
  const BlockListsScreen({super.key, required this.state});

  final ConsoleState state;

  @override
  State<BlockListsScreen> createState() => _BlockListsScreenState();
}

class _BlockListsScreenState extends State<BlockListsScreen> {
  String? _selected;

  ConsoleState get state => widget.state;

  Future<void> _newList() async {
    final name = await showDialog<String>(context: context, builder: (_) => const _NewListDialog());
    if (name == null || !mounted) return;
    if (await act(context, () => state.edit((api) => api.addList(name)))) {
      setState(() => _selected = name);
    }
  }

  Future<void> _deleteList(String name) async {
    final ok = await confirm(
      context,
      title: 'Delete "$name"?',
      body: 'The list and everything in it will be removed.',
      action: 'Delete',
    );
    if (!ok || !mounted) return;
    if (await act(context, () => state.edit((api) => api.removeList(name)))) {
      setState(() => _selected = null);
    }
  }

  @override
  Widget build(BuildContext context) {
    final rules = state.rules!;
    final names = rules.lists.keys.toList()..sort();
    final selected = names.contains(_selected) ? _selected : (names.isEmpty ? null : names.first);
    final canEdit = state.canEdit;

    return Padding(
      padding: const EdgeInsets.all(24),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          ScreenTitle(
            'Block lists',
            subtitle: 'Named lists of websites and apps. Schedules decide when and where each list blocks.',
            actions: [
              FilledButton.icon(
                onPressed: canEdit ? _newList : null,
                icon: const Icon(Icons.add),
                label: const Text('New list'),
              ),
            ],
          ),
          if (!canEdit) ReadOnlyNotice(pending: state.status!.isPending),
          Expanded(
            child: names.isEmpty
                ? const Center(child: Text('No block lists yet.'))
                : Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      SizedBox(
                        width: 220,
                        child: Card(
                          child: ListView(
                            children: [
                              for (final n in names)
                                ListTile(
                                  title: Text(n),
                                  subtitle: Text(_count(rules.lists[n]!)),
                                  selected: n == selected,
                                  onTap: () => setState(() => _selected = n),
                                ),
                            ],
                          ),
                        ),
                      ),
                      const SizedBox(width: 16),
                      Expanded(
                        child: _ListDetail(state: state, name: selected!, onDelete: _deleteList),
                      ),
                    ],
                  ),
          ),
        ],
      ),
    );
  }

  static String _count(Map<String, List<String>> items) {
    final n = items.values.fold<int>(0, (a, b) => a + b.length);
    return '$n item${n == 1 ? '' : 's'}';
  }
}

class _ListDetail extends StatelessWidget {
  const _ListDetail({required this.state, required this.name, required this.onDelete});

  final ConsoleState state;
  final String name;
  final void Function(String) onDelete;

  @override
  Widget build(BuildContext context) {
    final rules = state.rules!;
    final items = rules.lists[name]!;
    final usedBy = [
      for (final s in rules.schedules)
        if (s.list == name) s.id,
    ];
    final canEdit = state.canEdit;
    return ListView(
      children: [
        Section(
          title: name,
          trailing: TextButton.icon(
            onPressed: canEdit && usedBy.isEmpty ? () => onDelete(name) : null,
            icon: const Icon(Icons.delete_outline),
            label: const Text('Delete list'),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                usedBy.isEmpty
                    ? 'Not used by any schedule yet.'
                    : 'Used by ${usedBy.length} schedule${usedBy.length == 1 ? '' : 's'}.',
                style: TextStyle(color: Theme.of(context).colorScheme.onSurfaceVariant),
              ),
              const SizedBox(height: 16),
              for (final kind in itemKinds.keys)
                ItemEditor(
                  key: ValueKey('$name-$kind'),
                  kind: kind,
                  items: items[kind]!,
                  enabled: canEdit,
                  onAdd: (v) => act(context, () => state.edit((api) => api.addItem(name, kind, v))),
                  onRemove: (v) => act(context, () => state.edit((api) => api.removeItem(name, kind, v))),
                ),
            ],
          ),
        ),
      ],
    );
  }
}

class _NewListDialog extends StatefulWidget {
  const _NewListDialog();

  @override
  State<_NewListDialog> createState() => _NewListDialogState();
}

class _NewListDialogState extends State<_NewListDialog> {
  final _form = GlobalKey<FormState>();
  final _name = TextEditingController();

  @override
  void dispose() {
    _name.dispose();
    super.dispose();
  }

  void _submit() {
    if (_form.currentState!.validate()) Navigator.pop(context, _name.text.trim());
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('New block list'),
      content: Form(
        key: _form,
        child: TextFormField(
          key: const ValueKey('new-list-name'),
          controller: _name,
          autofocus: true,
          decoration: const InputDecoration(
            labelText: 'Name',
            hintText: 'social, games, video',
            border: OutlineInputBorder(),
          ),
          validator: (v) =>
              _listName.hasMatch((v ?? '').trim()) ? null : 'Lower-case letters, digits, - or _, up to 40',
          onFieldSubmitted: (_) => _submit(),
        ),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.pop(context), child: const Text('Cancel')),
        FilledButton(onPressed: _submit, child: const Text('Create')),
      ],
    );
  }
}
