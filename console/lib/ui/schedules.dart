import 'package:flutter/material.dart';

import '../models.dart';
import '../state.dart';
import 'common.dart';

final _hhmm = RegExp(r'^([01]\d|2[0-3]):[0-5]\d$');

class SchedulesScreen extends StatelessWidget {
  const SchedulesScreen({super.key, required this.state});

  final ConsoleState state;

  @override
  Widget build(BuildContext context) {
    final rules = state.rules!;
    final status = state.status!;
    final canEdit = state.canEdit;
    final hasLists = rules.lists.isNotEmpty;

    return ListView(
      padding: const EdgeInsets.all(24),
      children: [
        ScreenTitle(
          'Schedules',
          subtitle:
              'Each schedule blocks one list on chosen devices at chosen times. A block always wins, '
              'except for the Allowed list.',
          actions: [
            OutlinedButton.icon(
              onPressed: canEdit && hasLists ? () => _blockNow(context) : null,
              icon: const Icon(Icons.timer_outlined),
              label: const Text('Block now…'),
            ),
            FilledButton.icon(
              onPressed: canEdit && hasLists ? () => _addWeekly(context) : null,
              icon: const Icon(Icons.add),
              label: const Text('Weekly schedule'),
            ),
          ],
        ),
        if (!canEdit) ReadOnlyNotice(pending: status.isPending),
        if (!hasLists) const Padding(padding: EdgeInsets.only(bottom: 16), child: Text('Make a block list first.')),
        if (rules.schedules.isEmpty)
          const Text('No schedules yet.')
        else
          Card(
            child: Column(
              children: [
                for (final s in rules.schedules)
                  ListTile(
                    leading: Icon(s.isWeekly ? Icons.repeat : Icons.timer_outlined),
                    title: Row(
                      children: [
                        Text(s.list),
                        if (status.activeSchedules.contains(s.id)) ...[
                          const SizedBox(width: 8),
                          const Chip(label: Text('active now'), visualDensity: VisualDensity.compact),
                        ],
                      ],
                    ),
                    subtitle: Text('${s.when()} · ${s.target()}'),
                    trailing: IconButton(
                      tooltip: 'Remove schedule',
                      icon: const Icon(Icons.delete_outline),
                      onPressed: canEdit ? () => _remove(context, s) : null,
                    ),
                  ),
              ],
            ),
          ),
      ],
    );
  }

  Future<void> _remove(BuildContext context, Schedule s) async {
    final ok = await confirm(
      context,
      title: 'Remove this schedule?',
      body:
          '${s.list}: ${s.when()} on ${s.target()}. If it is blocking now, the block ends once the change is published.',
      action: 'Remove',
    );
    if (ok && context.mounted) {
      await act(context, () => state.edit((api) => api.removeSchedule(s.id)));
    }
  }

  Future<void> _addWeekly(BuildContext context) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (_) => _WeeklyDialog(state: state),
    );
    if (ok == true && context.mounted) {
      ScaffoldMessenger.of(context)
          .showSnackBar(const SnackBar(content: Text('Schedule added. Lock or publish to send it to the devices.')));
    }
  }

  Future<void> _blockNow(BuildContext context) async {
    await showDialog<bool>(
      context: context,
      builder: (_) => _BlockNowDialog(state: state),
    );
  }
}

class _WeeklyDialog extends StatefulWidget {
  const _WeeklyDialog({required this.state});

  final ConsoleState state;

  @override
  State<_WeeklyDialog> createState() => _WeeklyDialogState();
}

class _WeeklyDialogState extends State<_WeeklyDialog> {
  final _form = GlobalKey<FormState>();
  late String _list = (widget.state.rules!.lists.keys.toList()..sort()).first;
  List<String> _devices = const ['all'];
  final Set<String> _days = {'mon', 'tue', 'wed', 'thu', 'fri'};
  final _from = TextEditingController(text: '08:00');
  final _to = TextEditingController(text: '15:00');
  late final _tz = TextEditingController(text: widget.state.timeZone);
  bool _busy = false;

  @override
  void dispose() {
    _from.dispose();
    _to.dispose();
    _tz.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (!_form.currentState!.validate() || _days.isEmpty) return;
    setState(() => _busy = true);
    final state = widget.state;
    final ok = await act(
      context,
      () => state.edit(
        (api) => api.addWeekly(
          list: _list,
          devices: _devices,
          days: [
            for (final d in weekDays)
              if (_days.contains(d)) d,
          ],
          from: _from.text.trim(),
          to: _to.text.trim(),
          tz: _tz.text.trim(),
        ),
      ),
    );
    if (!mounted) return;
    setState(() => _busy = false);
    if (ok) {
      state.timeZone = _tz.text.trim();
      Navigator.pop(context, true);
    }
  }

  String? _time(String? v) => _hhmm.hasMatch((v ?? '').trim()) ? null : 'HH:MM, 24-hour';

  @override
  Widget build(BuildContext context) {
    final rules = widget.state.rules!;
    final from = _from.text.trim(), to = _to.text.trim();
    final overnight = _hhmm.hasMatch(from) && _hhmm.hasMatch(to) && from.compareTo(to) > 0;
    return AlertDialog(
      title: const Text('Weekly schedule'),
      content: SizedBox(
        width: 520,
        child: Form(
          key: _form,
          child: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                DropdownButtonFormField<String>(
                  isExpanded: true,
                  initialValue: _list,
                  decoration: const InputDecoration(labelText: 'Block list', border: OutlineInputBorder()),
                  items: [
                    for (final n in rules.lists.keys.toList()..sort()) DropdownMenuItem(value: n, child: Text(n)),
                  ],
                  onChanged: (v) => setState(() => _list = v!),
                ),
                const SizedBox(height: 16),
                const Text('Devices'),
                const SizedBox(height: 8),
                DevicePicker(
                  devices: widget.state.status!.devices,
                  selected: _devices,
                  onChanged: (v) => setState(() => _devices = v),
                ),
                const SizedBox(height: 16),
                const Text('Days'),
                const SizedBox(height: 8),
                Wrap(
                  spacing: 8,
                  children: [
                    for (final d in weekDays)
                      FilterChip(
                        label: Text(d[0].toUpperCase() + d.substring(1)),
                        selected: _days.contains(d),
                        onSelected: (on) => setState(() => on ? _days.add(d) : _days.remove(d)),
                      ),
                  ],
                ),
                if (_days.isEmpty)
                  Padding(
                    padding: const EdgeInsets.only(top: 8),
                    child: Text('Pick at least one day', style: TextStyle(color: Theme.of(context).colorScheme.error)),
                  ),
                const SizedBox(height: 16),
                Row(
                  children: [
                    Expanded(
                      child: TextFormField(
                        key: const ValueKey('weekly-from'),
                        controller: _from,
                        decoration: const InputDecoration(
                          labelText: 'From',
                          hintText: '08:00',
                          border: OutlineInputBorder(),
                        ),
                        validator: _time,
                        onChanged: (_) => setState(() {}),
                      ),
                    ),
                    const SizedBox(width: 12),
                    Expanded(
                      child: TextFormField(
                        key: const ValueKey('weekly-to'),
                        controller: _to,
                        decoration: const InputDecoration(
                          labelText: 'To',
                          hintText: '15:00',
                          border: OutlineInputBorder(),
                        ),
                        validator: _time,
                        onChanged: (_) => setState(() {}),
                      ),
                    ),
                  ],
                ),
                Padding(
                  padding: const EdgeInsets.only(top: 8),
                  child: Text(
                    from == to
                        ? 'Same start and end: blocks the whole of each chosen day.'
                        : overnight
                        ? 'Overnight: starts on each chosen day and ends the next morning.'
                        : 'Ends at "To" on the same day.',
                    style: TextStyle(color: Theme.of(context).colorScheme.onSurfaceVariant),
                  ),
                ),
                const SizedBox(height: 16),
                TextFormField(
                  controller: _tz,
                  decoration: const InputDecoration(
                    labelText: 'Time zone',
                    hintText: 'America/New_York',
                    border: OutlineInputBorder(),
                  ),
                  validator: (v) => (v ?? '').trim().contains('/') || (v ?? '').trim() == 'UTC'
                      ? null
                      : 'An IANA time zone, e.g. America/New_York',
                ),
              ],
            ),
          ),
        ),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.pop(context), child: const Text('Cancel')),
        FilledButton(onPressed: _busy ? null : _submit, child: const Text('Add schedule')),
      ],
    );
  }
}

class _BlockNowDialog extends StatefulWidget {
  const _BlockNowDialog({required this.state});

  final ConsoleState state;

  @override
  State<_BlockNowDialog> createState() => _BlockNowDialogState();
}

class _BlockNowDialogState extends State<_BlockNowDialog> {
  late String _list = (widget.state.rules!.lists.keys.toList()..sort()).first;
  List<String> _devices = const ['all'];
  double _hours = 2;
  bool _busy = false;

  static const _choices = [0.5, 1.0, 2.0, 3.0, 4.0, 8.0, 12.0, 24.0];

  String _label(double h) => h < 1 ? '${(h * 60).round()} minutes' : '${h.toStringAsFixed(0)} hour${h == 1 ? '' : 's'}';

  Future<void> _submit() async {
    setState(() => _busy = true);
    final ok = await act(
      context,
      () => widget.state.edit((api) => api.blockNow(_list, _hours, _devices)),
      done: 'Blocking $_list for ${_label(_hours)} once published.',
    );
    if (!mounted) return;
    setState(() => _busy = false);
    if (ok) Navigator.pop(context, true);
  }

  @override
  Widget build(BuildContext context) {
    final rules = widget.state.rules!;
    return AlertDialog(
      title: const Text('Block now'),
      content: SizedBox(
        width: 460,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            DropdownButtonFormField<String>(
              isExpanded: true,
              initialValue: _list,
              decoration: const InputDecoration(labelText: 'Block list', border: OutlineInputBorder()),
              items: [for (final n in rules.lists.keys.toList()..sort()) DropdownMenuItem(value: n, child: Text(n))],
              onChanged: (v) => setState(() => _list = v!),
            ),
            const SizedBox(height: 16),
            DropdownButtonFormField<double>(
              isExpanded: true,
              initialValue: _hours,
              decoration: const InputDecoration(labelText: 'For', border: OutlineInputBorder()),
              items: [for (final h in _choices) DropdownMenuItem(value: h, child: Text(_label(h)))],
              onChanged: (v) => setState(() => _hours = v!),
            ),
            const SizedBox(height: 16),
            const Text('Devices'),
            const SizedBox(height: 8),
            DevicePicker(
              devices: widget.state.status!.devices,
              selected: _devices,
              onChanged: (v) => setState(() => _devices = v),
            ),
          ],
        ),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.pop(context), child: const Text('Cancel')),
        FilledButton(onPressed: _busy ? null : _submit, child: const Text('Block')),
      ],
    );
  }
}
