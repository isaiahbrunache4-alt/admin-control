// Allowed, Devices, Activity and Settings (Spec 01 §5).

import 'package:flutter/material.dart';

import '../models.dart';
import '../state.dart';
import 'auth.dart';
import 'common.dart';
import 'dashboard.dart';

class AllowedScreen extends StatelessWidget {
  const AllowedScreen({super.key, required this.state});

  final ConsoleState state;

  @override
  Widget build(BuildContext context) {
    final allow = state.rules!.allow;
    final canEdit = state.canEdit;
    return ListView(
      padding: const EdgeInsets.all(24),
      children: [
        const ScreenTitle(
          'Allowed',
          subtitle:
              'Never blocked by any schedule, on any device. Keep developer tools and '
              'the sites they need here so ExVelo and Block Trainer work keeps going.',
        ),
        if (!canEdit) ReadOnlyNotice(pending: state.status!.isPending),
        Section(
          title: 'Always allowed',
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              for (final kind in itemKinds.keys)
                ItemEditor(
                  key: ValueKey('allow-$kind'),
                  kind: kind,
                  items: allow[kind]!,
                  enabled: canEdit,
                  onAdd: (v) => act(context, () => state.edit((api) => api.allow(kind, v))),
                  onRemove: (v) => act(context, () => state.edit((api) => api.disallow(kind, v))),
                ),
            ],
          ),
        ),
      ],
    );
  }
}

// ---- Devices

final _deviceId = RegExp(r'^[a-z0-9][a-z0-9-]{0,31}$');

String suggestDeviceId(String name) {
  final s = name.toLowerCase().replaceAll(RegExp(r'[^a-z0-9]+'), '-').replaceAll(RegExp(r'^-+|-+$'), '');
  return s.length > 32 ? s.substring(0, 32) : s;
}

class DevicesScreen extends StatelessWidget {
  const DevicesScreen({super.key, required this.state});

  final ConsoleState state;

  @override
  Widget build(BuildContext context) {
    final status = state.status!;
    final canEdit = state.canEdit;
    return ListView(
      padding: const EdgeInsets.all(24),
      children: [
        ScreenTitle(
          'Devices',
          subtitle:
              'Every device Fortress enforces, this PC included. A device shows amber after 24 h '
              'without a check-in and red after 72 h.',
          actions: [
            FilledButton.icon(
              onPressed: canEdit ? () => _add(context) : null,
              icon: const Icon(Icons.add),
              label: const Text('Add device'),
            ),
          ],
        ),
        if (!canEdit) ReadOnlyNotice(pending: status.isPending),
        if (status.devices.isEmpty)
          const Text('No devices yet.')
        else
          Card(
            child: Column(
              children: [
                for (final d in status.devices)
                  ListTile(
                    leading: Icon(
                      d.platform == 'windows' ? Icons.computer : Icons.smartphone,
                      color: deviceColor(context, d.status),
                    ),
                    title: Text(d.name),
                    subtitle: Text(
                      '${d.id} · ${d.platform == 'windows' ? 'Windows' : 'Android'} · ${deviceStatusText(d)}',
                    ),
                    trailing: TextButton(
                      onPressed: canEdit ? () => _remove(context, d) : null,
                      child: const Text('Remove'),
                    ),
                  ),
              ],
            ),
          ),
        const SizedBox(height: 16),
        Text(
          'Adding a device here reserves its place. Each device is then enrolled with its Agent, '
          'which arrives in a later phase.',
          style: TextStyle(color: Theme.of(context).colorScheme.onSurfaceVariant),
        ),
      ],
    );
  }

  Future<void> _add(BuildContext context) async {
    await showDialog<void>(
      context: context,
      builder: (_) => _AddDeviceDialog(state: state),
    );
  }

  Future<void> _remove(BuildContext context, Device d) async {
    final ok = await confirm(
      context,
      title: 'Remove ${d.name}?',
      body:
          'Fortress sends this device a signed release and its Agent stops enforcing. '
          'Schedules that only target it are removed. Its id "${d.id}" cannot be used again.',
      action: 'Remove device',
    );
    if (ok && context.mounted) {
      await act(context, () => state.edit((api) => api.removeDevice(d.id)), done: '${d.name} released.');
    }
  }
}

class _AddDeviceDialog extends StatefulWidget {
  const _AddDeviceDialog({required this.state});

  final ConsoleState state;

  @override
  State<_AddDeviceDialog> createState() => _AddDeviceDialogState();
}

class _AddDeviceDialogState extends State<_AddDeviceDialog> {
  final _form = GlobalKey<FormState>();
  final _name = TextEditingController();
  final _id = TextEditingController();
  bool _idEdited = false;
  String _platform = 'android';

  @override
  void dispose() {
    _name.dispose();
    _id.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (!_form.currentState!.validate()) return;
    final ok = await act(
      context,
      () => widget.state.edit((api) => api.addDevice(_id.text.trim(), _name.text.trim(), _platform)),
    );
    if (ok && mounted) Navigator.pop(context);
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Add device'),
      content: SizedBox(
        width: 420,
        child: Form(
          key: _form,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextFormField(
                key: const ValueKey('device-name'),
                controller: _name,
                autofocus: true,
                decoration: const InputDecoration(
                  labelText: 'Name',
                  hintText: 'Lenovo Idea Tab',
                  border: OutlineInputBorder(),
                ),
                validator: (v) => (v ?? '').trim().isEmpty ? 'Give it a name' : null,
                onChanged: (v) {
                  if (!_idEdited) _id.text = suggestDeviceId(v);
                },
              ),
              const SizedBox(height: 12),
              TextFormField(
                key: const ValueKey('device-id'),
                controller: _id,
                decoration: const InputDecoration(
                  labelText: 'Id',
                  helperText: 'Used in schedules. Cannot be changed later.',
                  border: OutlineInputBorder(),
                ),
                validator: (v) {
                  final s = (v ?? '').trim();
                  if (s == 'all') return '"all" is reserved';
                  return _deviceId.hasMatch(s) ? null : 'Lower-case letters, digits and -, up to 32';
                },
                onChanged: (_) => _idEdited = true,
              ),
              const SizedBox(height: 12),
              DropdownButtonFormField<String>(
                isExpanded: true,
                initialValue: _platform,
                decoration: const InputDecoration(labelText: 'Platform', border: OutlineInputBorder()),
                items: const [
                  DropdownMenuItem(value: 'android', child: Text('Android (Pixel, tablet)')),
                  DropdownMenuItem(value: 'windows', child: Text('Windows (this PC)')),
                ],
                onChanged: (v) => setState(() => _platform = v!),
              ),
            ],
          ),
        ),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.pop(context), child: const Text('Cancel')),
        FilledButton(onPressed: _submit, child: const Text('Add')),
      ],
    );
  }
}

// ---- Activity

class ActivityScreen extends StatelessWidget {
  const ActivityScreen({super.key, required this.state});

  final ConsoleState state;

  static IconData _icon(String kind) => switch (kind) {
    'unlock' => Icons.lock_open,
    'lock' => Icons.lock,
    'publish' => Icons.send,
    'edit' => Icons.edit,
    'wrong_password' => Icons.warning_amber,
    'device_added' => Icons.add_to_queue,
    'password_changed' || 'password_reset' => Icons.key,
    'setting' => Icons.tune,
    _ => Icons.circle_outlined,
  };

  static String _label(String kind) => switch (kind) {
    'wrong_password' => 'Wrong password',
    'device_added' => 'Device added',
    'password_changed' => 'Password changed',
    'password_reset' => 'Password reset',
    _ => kind[0].toUpperCase() + kind.substring(1).replaceAll('_', ' '),
  };

  @override
  Widget build(BuildContext context) {
    final entries = state.activity;
    return ListView(
      padding: const EdgeInsets.all(24),
      children: [
        const ScreenTitle('Activity', subtitle: 'Most recent first.'),
        Card(
          child: Column(
            children: [
              for (final a in entries)
                ListTile(
                  dense: true,
                  leading: Icon(
                    _icon(a.kind),
                    color: a.kind == 'wrong_password' ? Theme.of(context).colorScheme.error : null,
                  ),
                  title: Text(_label(a.kind)),
                  subtitle: a.detail.isEmpty ? null : Text(a.detail),
                  trailing: Text(shortDateTime(a.at)),
                ),
            ],
          ),
        ),
      ],
    );
  }
}

// ---- Settings

class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key, required this.state});

  final ConsoleState state;

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  late final _delay = TextEditingController(text: '${widget.state.status!.unlockDelayMinutes}');
  late final _relock = TextEditingController(text: '${widget.state.status!.relockMinutes}');

  ConsoleState get state => widget.state;

  @override
  void dispose() {
    _delay.dispose();
    _relock.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    final delay = int.tryParse(_delay.text.trim());
    final relock = int.tryParse(_relock.text.trim());
    if (delay == null || relock == null) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Enter whole minutes.')));
      return;
    }
    await act(
      context,
      () => state.edit((api) => api.settings(unlockDelayMinutes: delay, relockMinutes: relock)),
      done: 'Saved.',
    );
  }

  Future<void> _lockUntil() async {
    final now = DateTime.now();
    final day = await showDatePicker(
      context: context,
      firstDate: now,
      lastDate: now.add(const Duration(days: 365)),
      initialDate: now.add(const Duration(days: 1)),
      helpText: 'Locked until which day?',
    );
    if (day == null || !mounted) return;
    final time = await showTimePicker(context: context, initialTime: const TimeOfDay(hour: 8, minute: 0));
    if (time == null || !mounted) return;
    final until = DateTime(day.year, day.month, day.day, time.hour, time.minute);
    if (!until.isAfter(DateTime.now())) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Pick a time in the future.')));
      return;
    }
    final ok = await confirm(
      context,
      title: 'Lock until ${shortDateTime(until)}?',
      body:
          'Fortress locks now, and the password will not unlock it before then. '
          'Only the recovery code can. This cannot be undone from the Console.',
      action: 'Lock until then',
    );
    if (ok && mounted) {
      await act(context, () => state.edit((api) => api.lockUntil(until)));
    }
  }

  @override
  Widget build(BuildContext context) {
    final canEdit = state.canEdit;
    final s = state.status!;
    return ListView(
      padding: const EdgeInsets.all(24),
      children: [
        const ScreenTitle('Settings'),
        if (!canEdit) ReadOnlyNotice(pending: s.isPending),
        Section(
          title: 'Self-control',
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  SizedBox(
                    width: 220,
                    child: TextField(
                      controller: _delay,
                      enabled: canEdit,
                      keyboardType: TextInputType.number,
                      decoration: const InputDecoration(
                        labelText: 'Unlock delay (minutes)',
                        helperText: '0 = none',
                        border: OutlineInputBorder(),
                      ),
                    ),
                  ),
                  const SizedBox(width: 12),
                  SizedBox(
                    width: 220,
                    child: TextField(
                      controller: _relock,
                      enabled: canEdit,
                      keyboardType: TextInputType.number,
                      decoration: const InputDecoration(
                        labelText: 'Auto-relock (minutes idle)',
                        helperText: '1 to 1440',
                        border: OutlineInputBorder(),
                      ),
                    ),
                  ),
                  const SizedBox(width: 12),
                  FilledButton(onPressed: canEdit ? _save : null, child: const Text('Save')),
                ],
              ),
              const SizedBox(height: 16),
              const Text(
                'After the right password, the unlock delay makes you wait before changes are allowed. '
                'You can cancel while it runs.',
              ),
              const SizedBox(height: 16),
              OutlinedButton.icon(
                onPressed: canEdit ? _lockUntil : null,
                icon: const Icon(Icons.event_busy),
                label: Text(s.lockedUntil == null ? 'Lock until…' : 'Locked until ${shortDateTime(s.lockedUntil!)}'),
              ),
            ],
          ),
        ),
        Section(
          title: 'Password',
          child: Wrap(
            spacing: 12,
            runSpacing: 12,
            children: [
              OutlinedButton(
                onPressed: canEdit
                    ? () => showDialog<void>(
                        context: context,
                        builder: (_) => _ChangePasswordDialog(state: state),
                      )
                    : null,
                child: const Text('Change password'),
              ),
              OutlinedButton(
                onPressed: () => showRecoverDialog(context, state),
                child: const Text('Reset with recovery code'),
              ),
            ],
          ),
        ),
      ],
    );
  }
}

class _ChangePasswordDialog extends StatefulWidget {
  const _ChangePasswordDialog({required this.state});

  final ConsoleState state;

  @override
  State<_ChangePasswordDialog> createState() => _ChangePasswordDialogState();
}

class _ChangePasswordDialogState extends State<_ChangePasswordDialog> {
  final _form = GlobalKey<FormState>();
  final _current = TextEditingController();
  final _new = TextEditingController();
  final _again = TextEditingController();

  @override
  void dispose() {
    _current.dispose();
    _new.dispose();
    _again.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (!_form.currentState!.validate()) return;
    final ok = await act(
      context,
      () => widget.state.edit((api) => api.changePassword(_current.text, _new.text)),
      done: 'Password changed.',
    );
    if (ok && mounted) Navigator.pop(context);
  }

  @override
  Widget build(BuildContext context) {
    InputDecoration d(String label) => InputDecoration(labelText: label, border: const OutlineInputBorder());
    return AlertDialog(
      title: const Text('Change password'),
      content: SizedBox(
        width: 400,
        child: Form(
          key: _form,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextFormField(
                controller: _current,
                obscureText: true,
                autofocus: true,
                decoration: d('Current password'),
              ),
              const SizedBox(height: 12),
              TextFormField(
                controller: _new,
                obscureText: true,
                decoration: d('New password'),
                validator: (v) =>
                    (v ?? '').length < minPasswordLength ? 'At least $minPasswordLength characters' : null,
              ),
              const SizedBox(height: 12),
              TextFormField(
                controller: _again,
                obscureText: true,
                decoration: d('New password again'),
                validator: (v) => v != _new.text ? 'The passwords differ' : null,
              ),
            ],
          ),
        ),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.pop(context), child: const Text('Cancel')),
        FilledButton(onPressed: _submit, child: const Text('Change')),
      ],
    );
  }
}
