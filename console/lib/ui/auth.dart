// First-run setup, the unlock dialog and recovery (Spec 01 §6). The password is only
// ever typed here, in the Console on the PC.

import 'package:flutter/material.dart';

import '../api.dart';
import '../state.dart';
import 'common.dart';

const minPasswordLength = 8;

class SetupScreen extends StatefulWidget {
  const SetupScreen({super.key, required this.state});

  final ConsoleState state;

  @override
  State<SetupScreen> createState() => _SetupScreenState();
}

class _SetupScreenState extends State<SetupScreen> {
  final _form = GlobalKey<FormState>();
  final _pw = TextEditingController();
  final _again = TextEditingController();
  bool _busy = false;
  String? _error;

  @override
  void dispose() {
    _pw.dispose();
    _again.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (!_form.currentState!.validate()) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final code = await widget.state.api.setup(_pw.text);
      if (!mounted) return;
      await showDialog<void>(
        context: context,
        barrierDismissible: false,
        builder: (_) => RecoveryCodeDialog(code: code),
      );
      await widget.state.refresh();
    } on ApiError catch (e) {
      setState(() => _error = errorText(e));
    } on CoreUnreachable catch (e) {
      setState(() => _error = errorText(e));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    return Scaffold(
      body: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 480),
          child: Form(
            key: _form,
            child: ListView(
              shrinkWrap: true,
              padding: const EdgeInsets.all(24),
              children: [
                Text('Set up Fortress', style: t.headlineMedium),
                const SizedBox(height: 12),
                const Text(
                  'Choose the one password that unlocks changes on every device. '
                  'For the strongest self-control, let a trusted person choose it and keep it.',
                ),
                const SizedBox(height: 24),
                TextFormField(
                  key: const ValueKey('setup-password'),
                  controller: _pw,
                  obscureText: true,
                  autofocus: true,
                  decoration: const InputDecoration(labelText: 'Password', border: OutlineInputBorder()),
                  validator: (v) =>
                      (v ?? '').length < minPasswordLength ? 'At least $minPasswordLength characters' : null,
                ),
                const SizedBox(height: 12),
                TextFormField(
                  key: const ValueKey('setup-again'),
                  controller: _again,
                  obscureText: true,
                  decoration: const InputDecoration(labelText: 'Password again', border: OutlineInputBorder()),
                  validator: (v) => v != _pw.text ? 'The passwords differ' : null,
                  onFieldSubmitted: (_) => _submit(),
                ),
                if (_error != null) ...[
                  const SizedBox(height: 12),
                  Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
                ],
                const SizedBox(height: 24),
                FilledButton(onPressed: _busy ? null : _submit, child: Text(_busy ? 'Setting up…' : 'Set up Fortress')),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class RecoveryCodeDialog extends StatefulWidget {
  const RecoveryCodeDialog({super.key, required this.code});

  final String code;

  @override
  State<RecoveryCodeDialog> createState() => _RecoveryCodeDialogState();
}

class _RecoveryCodeDialogState extends State<RecoveryCodeDialog> {
  bool _kept = false;

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Your recovery code'),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            'This is shown only once. It resets the password if it is lost, and it '
            'works even while "Locked until" is set. Print it or write it down and keep it '
            'somewhere safe, away from this PC.',
          ),
          const SizedBox(height: 16),
          SelectableText(
            widget.code,
            style: Theme.of(context).textTheme.titleLarge?.copyWith(fontFamily: 'monospace', letterSpacing: 1.5),
          ),
          const SizedBox(height: 16),
          CheckboxListTile(
            contentPadding: EdgeInsets.zero,
            value: _kept,
            onChanged: (v) => setState(() => _kept = v ?? false),
            title: const Text('I have written it down'),
          ),
        ],
      ),
      actions: [FilledButton(onPressed: _kept ? () => Navigator.pop(context) : null, child: const Text('Continue'))],
    );
  }
}

/// Returns true once unlocked (or the unlock delay has started).
Future<bool> showUnlockDialog(BuildContext context, ConsoleState state) async {
  final result = await showDialog<String>(
    context: context,
    builder: (_) => _UnlockDialog(state: state),
  );
  if (result == 'recover' && context.mounted) await showRecoverDialog(context, state);
  return result == 'unlocked';
}

class _UnlockDialog extends StatefulWidget {
  const _UnlockDialog({required this.state});

  final ConsoleState state;

  @override
  State<_UnlockDialog> createState() => _UnlockDialogState();
}

class _UnlockDialogState extends State<_UnlockDialog> {
  final _pw = TextEditingController();
  bool _busy = false;
  String? _error;

  @override
  void dispose() {
    _pw.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (_pw.text.isEmpty || _busy) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await widget.state.unlock(_pw.text);
      if (mounted) Navigator.pop(context, 'unlocked');
    } on ApiError catch (e) {
      _pw.clear();
      setState(() => _error = errorText(e));
    } on CoreUnreachable catch (e) {
      setState(() => _error = errorText(e));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Unlock Fortress'),
      content: SizedBox(
        width: 380,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            TextField(
              key: const ValueKey('unlock-password'),
              controller: _pw,
              obscureText: true,
              autofocus: true,
              enabled: !_busy,
              decoration: const InputDecoration(labelText: 'Password', border: OutlineInputBorder()),
              onSubmitted: (_) => _submit(),
            ),
            if (_error != null) ...[
              const SizedBox(height: 12),
              Text(
                _error!,
                key: const ValueKey('unlock-error'),
                style: TextStyle(color: Theme.of(context).colorScheme.error),
              ),
            ],
            const SizedBox(height: 8),
            TextButton(
              onPressed: () => Navigator.pop(context, 'recover'),
              child: const Text('Forgot the password? Use the recovery code'),
            ),
          ],
        ),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.pop(context), child: const Text('Cancel')),
        FilledButton(onPressed: _busy ? null : _submit, child: Text(_busy ? 'Checking…' : 'Unlock')),
      ],
    );
  }
}

Future<void> showRecoverDialog(BuildContext context, ConsoleState state) => showDialog<void>(
  context: context,
  builder: (_) => _RecoverDialog(state: state),
);

class _RecoverDialog extends StatefulWidget {
  const _RecoverDialog({required this.state});

  final ConsoleState state;

  @override
  State<_RecoverDialog> createState() => _RecoverDialogState();
}

class _RecoverDialogState extends State<_RecoverDialog> {
  final _form = GlobalKey<FormState>();
  final _code = TextEditingController();
  final _pw = TextEditingController();
  final _again = TextEditingController();
  String? _error;
  bool _busy = false;

  @override
  void dispose() {
    _code.dispose();
    _pw.dispose();
    _again.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (!_form.currentState!.validate()) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    final messenger = ScaffoldMessenger.of(context);
    try {
      await widget.state.recover(_code.text, _pw.text);
      if (!mounted) return;
      Navigator.pop(context);
      messenger.showSnackBar(
        const SnackBar(content: Text('Password reset. Fortress is locked; unlock with the new password.')),
      );
    } on ApiError catch (e) {
      setState(() => _error = errorText(e));
    } on CoreUnreachable catch (e) {
      setState(() => _error = errorText(e));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Reset the password'),
      content: SizedBox(
        width: 420,
        child: Form(
          key: _form,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextFormField(
                controller: _code,
                autofocus: true,
                decoration: const InputDecoration(
                  labelText: 'Recovery code',
                  hintText: 'XXXX-XXXX-XXXX-XXXX-XXXX-XXXX',
                  border: OutlineInputBorder(),
                ),
                validator: (v) => (v ?? '').trim().isEmpty ? 'Enter the recovery code' : null,
              ),
              const SizedBox(height: 12),
              TextFormField(
                controller: _pw,
                obscureText: true,
                decoration: const InputDecoration(labelText: 'New password', border: OutlineInputBorder()),
                validator: (v) =>
                    (v ?? '').length < minPasswordLength ? 'At least $minPasswordLength characters' : null,
              ),
              const SizedBox(height: 12),
              TextFormField(
                controller: _again,
                obscureText: true,
                decoration: const InputDecoration(labelText: 'New password again', border: OutlineInputBorder()),
                validator: (v) => v != _pw.text ? 'The passwords differ' : null,
              ),
              if (_error != null) ...[
                const SizedBox(height: 12),
                Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
              ],
            ],
          ),
        ),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.pop(context), child: const Text('Cancel')),
        FilledButton(onPressed: _busy ? null : _submit, child: const Text('Reset password')),
      ],
    );
  }
}
