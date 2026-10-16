import 'package:flutter/material.dart';

import '../api.dart';
import '../models.dart';

/// Human wording for whatever an action threw.
String errorText(Object e) {
  if (e is ApiError) {
    if (e.isTooSoon && e.retryAfter != null) {
      return e.kind == 'too_soon' && e.message.startsWith('locked until')
          ? 'Fortress is locked until ${shortDateTime(e.retryAfter!)}. Only the recovery code works before then.'
          : 'Too many wrong attempts. Try again at ${clockTime(e.retryAfter!)}.';
    }
    if (e.isLocked) return 'Fortress is locked. Unlock to make changes.';
    final m = e.message;
    return m.isEmpty ? m : m[0].toUpperCase() + m.substring(1);
  }
  if (e is CoreUnreachable) return 'Fortress Core is not answering. Is it running?';
  return '$e';
}

/// Run an action and report a failure (or [done]) in a snack bar. True on success.
Future<bool> act(BuildContext context, Future<void> Function() action, {String? done}) async {
  final messenger = ScaffoldMessenger.of(context);
  try {
    await action();
    if (done != null) messenger.showSnackBar(SnackBar(content: Text(done)));
    return true;
  } on ApiError catch (e) {
    messenger.showSnackBar(SnackBar(content: Text(errorText(e))));
  } on CoreUnreachable catch (e) {
    messenger.showSnackBar(SnackBar(content: Text(errorText(e))));
  }
  return false;
}

class Section extends StatelessWidget {
  const Section({super.key, required this.title, required this.child, this.trailing});

  final String title;
  final Widget child;
  final Widget? trailing;

  @override
  Widget build(BuildContext context) {
    return Card(
      margin: const EdgeInsets.only(bottom: 16),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(child: Text(title, style: Theme.of(context).textTheme.titleMedium)),
                ?trailing,
              ],
            ),
            const SizedBox(height: 12),
            child,
          ],
        ),
      ),
    );
  }
}

class ScreenTitle extends StatelessWidget {
  const ScreenTitle(this.title, {super.key, this.subtitle, this.actions = const []});

  final String title;
  final String? subtitle;
  final List<Widget> actions;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    return Padding(
      padding: const EdgeInsets.only(bottom: 16),
      child: Row(
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(title, style: t.headlineSmall),
                if (subtitle != null)
                  Padding(
                    padding: const EdgeInsets.only(top: 4),
                    child: Text(
                      subtitle!,
                      style: t.bodyMedium?.copyWith(color: Theme.of(context).colorScheme.onSurfaceVariant),
                    ),
                  ),
              ],
            ),
          ),
          for (final a in actions) Padding(padding: const EdgeInsets.only(left: 8), child: a),
        ],
      ),
    );
  }
}

/// Shown on every screen while changes are not allowed.
class ReadOnlyNotice extends StatelessWidget {
  const ReadOnlyNotice({super.key, required this.pending});

  final bool pending;

  @override
  Widget build(BuildContext context) {
    final c = Theme.of(context).colorScheme;
    return Container(
      width: double.infinity,
      margin: const EdgeInsets.only(bottom: 16),
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      decoration: BoxDecoration(color: c.surfaceContainerHighest, borderRadius: BorderRadius.circular(8)),
      child: Row(
        children: [
          Icon(Icons.visibility_outlined, size: 18, color: c.onSurfaceVariant),
          const SizedBox(width: 8),
          Text(
            pending ? 'Read-only until the unlock delay ends.' : 'Read-only. Unlock to make changes.',
            style: TextStyle(color: c.onSurfaceVariant),
          ),
        ],
      ),
    );
  }
}

/// Chips for a set of items, with an add box. Used for block lists and the allowed list.
class ItemEditor extends StatefulWidget {
  const ItemEditor({
    super.key,
    required this.kind,
    required this.items,
    required this.enabled,
    required this.onAdd,
    required this.onRemove,
  });

  final String kind;
  final List<String> items;
  final bool enabled;
  final Future<bool> Function(String item) onAdd;
  final Future<bool> Function(String item) onRemove;

  @override
  State<ItemEditor> createState() => _ItemEditorState();
}

class _ItemEditorState extends State<ItemEditor> {
  final _text = TextEditingController();

  @override
  void dispose() {
    _text.dispose();
    super.dispose();
  }

  Future<void> _add() async {
    final v = _text.text.trim();
    if (v.isEmpty) return;
    if (await widget.onAdd(v)) _text.clear();
  }

  @override
  Widget build(BuildContext context) {
    final label = itemKinds[widget.kind]!;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(label, style: Theme.of(context).textTheme.labelLarge),
        const SizedBox(height: 8),
        if (widget.items.isEmpty)
          Text('None', style: TextStyle(color: Theme.of(context).colorScheme.onSurfaceVariant))
        else
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              for (final item in widget.items)
                InputChip(
                  label: Text(item),
                  onDeleted: widget.enabled ? () => widget.onRemove(item) : null,
                  deleteButtonTooltipMessage: 'Remove $item',
                ),
            ],
          ),
        if (widget.enabled) ...[
          const SizedBox(height: 8),
          Row(
            children: [
              Expanded(
                child: TextField(
                  key: ValueKey('add-${widget.kind}'),
                  controller: _text,
                  decoration: InputDecoration(
                    isDense: true,
                    border: const OutlineInputBorder(),
                    hintText: itemHints[widget.kind],
                    labelText: 'Add to $label',
                  ),
                  onSubmitted: (_) => _add(),
                ),
              ),
              const SizedBox(width: 8),
              IconButton.filledTonal(onPressed: _add, icon: const Icon(Icons.add), tooltip: 'Add'),
            ],
          ),
        ],
        const SizedBox(height: 16),
      ],
    );
  }
}

/// "All devices" or a chosen set.
class DevicePicker extends StatelessWidget {
  const DevicePicker({super.key, required this.devices, required this.selected, required this.onChanged});

  final List<Device> devices;
  final List<String> selected;
  final ValueChanged<List<String>> onChanged;

  @override
  Widget build(BuildContext context) {
    final all = selected.contains('all');
    return Wrap(
      spacing: 8,
      runSpacing: 8,
      children: [
        FilterChip(label: const Text('All devices'), selected: all, onSelected: (_) => onChanged(const ['all'])),
        for (final d in devices)
          FilterChip(
            label: Text(d.name),
            selected: !all && selected.contains(d.id),
            onSelected: (on) {
              final next = {...selected.where((x) => x != 'all')};
              on ? next.add(d.id) : next.remove(d.id);
              onChanged(next.isEmpty ? const ['all'] : next.toList());
            },
          ),
      ],
    );
  }
}

Future<bool> confirm(
  BuildContext context, {
  required String title,
  required String body,
  required String action,
}) async {
  final ok = await showDialog<bool>(
    context: context,
    builder: (c) => AlertDialog(
      title: Text(title),
      content: Text(body),
      actions: [
        TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Cancel')),
        FilledButton(onPressed: () => Navigator.pop(c, true), child: Text(action)),
      ],
    ),
  );
  return ok == true;
}
