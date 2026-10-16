import 'package:flutter/material.dart';

import '../models.dart';
import '../state.dart';
import 'auth.dart';
import 'block_lists.dart';
import 'common.dart';
import 'dashboard.dart';
import 'other_screens.dart';
import 'schedules.dart';

class ConsoleApp extends StatelessWidget {
  const ConsoleApp({super.key, required this.state});

  final ConsoleState state;

  @override
  Widget build(BuildContext context) {
    ThemeData theme(Brightness b) => ThemeData(
      colorScheme: ColorScheme.fromSeed(seedColor: const Color(0xFF3D5A80), brightness: b),
      useMaterial3: true,
    );
    return MaterialApp(
      title: 'Fortress Console',
      debugShowCheckedModeBanner: false,
      theme: theme(Brightness.light),
      darkTheme: theme(Brightness.dark),
      home: ListenableBuilder(
        listenable: state,
        builder: (context, _) => _Root(state: state),
      ),
    );
  }
}

class _Root extends StatelessWidget {
  const _Root({required this.state});

  final ConsoleState state;

  @override
  Widget build(BuildContext context) {
    final s = state.status;
    if (!state.loaded) return const Scaffold(body: Center(child: CircularProgressIndicator()));
    if (s == null) return CoreDownScreen(state: state);
    if (!s.setUp) return SetupScreen(state: state);
    if (state.rules == null) return const Scaffold(body: Center(child: CircularProgressIndicator()));
    return Shell(state: state);
  }
}

class CoreDownScreen extends StatelessWidget {
  const CoreDownScreen({super.key, required this.state});

  final ConsoleState state;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 480),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(Icons.power_off_outlined, size: 48, color: Theme.of(context).colorScheme.outline),
              const SizedBox(height: 16),
              Text('Fortress Core is not running', style: Theme.of(context).textTheme.headlineSmall),
              const SizedBox(height: 8),
              const Text(
                'The Console talks to Core on this PC. Start it with "fortress serve". '
                'The devices keep enforcing their last rules in the meantime.',
                textAlign: TextAlign.center,
              ),
              const SizedBox(height: 24),
              FilledButton(onPressed: state.refresh, child: const Text('Try again')),
            ],
          ),
        ),
      ),
    );
  }
}

class _Dest {
  const _Dest(this.label, this.icon, this.selectedIcon);

  final String label;
  final IconData icon;
  final IconData selectedIcon;
}

const _dests = [
  _Dest('Dashboard', Icons.space_dashboard_outlined, Icons.space_dashboard),
  _Dest('Block lists', Icons.list_alt_outlined, Icons.list_alt),
  _Dest('Schedules', Icons.calendar_month_outlined, Icons.calendar_month),
  _Dest('Allowed', Icons.verified_outlined, Icons.verified),
  _Dest('Devices', Icons.devices_outlined, Icons.devices),
  _Dest('Activity', Icons.history, Icons.history),
  _Dest('Settings', Icons.settings_outlined, Icons.settings),
];

class Shell extends StatefulWidget {
  const Shell({super.key, required this.state});

  final ConsoleState state;

  @override
  State<Shell> createState() => _ShellState();
}

class _ShellState extends State<Shell> {
  int _index = 0;

  @override
  Widget build(BuildContext context) {
    final state = widget.state;
    final screen = switch (_index) {
      0 => DashboardScreen(state: state),
      1 => BlockListsScreen(state: state),
      2 => SchedulesScreen(state: state),
      3 => AllowedScreen(state: state),
      4 => DevicesScreen(state: state),
      5 => ActivityScreen(state: state),
      _ => SettingsScreen(key: ValueKey(state.status!.version), state: state),
    };
    return Scaffold(
      body: Column(
        children: [
          LockBar(state: state),
          if (!state.reachable)
            MaterialBanner(
              content: const Text('Lost contact with Fortress Core. Showing the last known state.'),
              actions: [TextButton(onPressed: state.refresh, child: const Text('Retry'))],
            ),
          Expanded(
            child: Row(
              children: [
                NavigationRail(
                  selectedIndex: _index,
                  labelType: NavigationRailLabelType.all,
                  onDestinationSelected: (i) => setState(() => _index = i),
                  destinations: [
                    for (final d in _dests)
                      NavigationRailDestination(
                        icon: Icon(d.icon),
                        selectedIcon: Icon(d.selectedIcon),
                        label: Text(d.label),
                      ),
                  ],
                ),
                const VerticalDivider(width: 1),
                Expanded(child: screen),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

/// The lock state, large, at the top of every screen (Spec 01 §5), and the only way
/// in or out of it.
class LockBar extends StatelessWidget {
  const LockBar({super.key, required this.state});

  final ConsoleState state;

  @override
  Widget build(BuildContext context) {
    final s = state.status!;
    final c = Theme.of(context).colorScheme;
    final t = Theme.of(context).textTheme;
    final mine = state.api.token != null;

    final (Color bg, Color fg, IconData icon, String title, String detail) = switch (s.state) {
      'unlocked' when mine => (
        c.tertiaryContainer,
        c.onTertiaryContainer,
        Icons.lock_open,
        'Unlocked',
        'Changes allowed. Blocks stay in force. Locks again after ${s.relockMinutes} min idle.',
      ),
      'unlocked' => (
        c.secondaryContainer,
        c.onSecondaryContainer,
        Icons.lock_open,
        'Unlocked elsewhere',
        'Another Console session holds the unlock. Unlock here to take it over.',
      ),
      'pending' => (
        c.secondaryContainer,
        c.onSecondaryContainer,
        Icons.hourglass_top,
        'Unlocking at ${clockTime(s.unlocksAt!)}',
        'The unlock delay is running. Cancel it if you changed your mind.',
      ),
      _ => (
        c.surfaceContainerHighest,
        c.onSurface,
        Icons.lock,
        'Locked',
        s.lockedUntil != null
            ? 'Locked until ${shortDateTime(s.lockedUntil!)}. Read-only.'
            : 'Read-only. The password unlocks changes.',
      ),
    };

    final actions = <Widget>[
      if (s.isUnlocked && mine && s.unpublishedChanges)
        OutlinedButton.icon(
          onPressed: () => act(context, () => state.edit((api) => api.publish()), done: 'Published to all devices.'),
          icon: const Icon(Icons.send),
          label: const Text('Publish now'),
        ),
      if (s.isLocked || !mine)
        FilledButton.icon(
          key: const ValueKey('unlock-button'),
          onPressed: () => showUnlockDialog(context, state),
          icon: const Icon(Icons.lock_open),
          label: const Text('Unlock'),
        )
      else
        FilledButton.icon(
          key: const ValueKey('lock-button'),
          onPressed: () => act(
            context,
            state.lock,
            done: s.unpublishedChanges ? 'Locked. Changes published to all devices.' : 'Locked.',
          ),
          icon: Icon(s.isPending ? Icons.close : Icons.lock),
          label: Text(s.isPending ? 'Cancel unlock' : (s.unpublishedChanges ? 'Lock and publish' : 'Lock')),
        ),
    ];

    return Material(
      color: bg,
      child: SafeArea(
        bottom: false,
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 16),
          child: Row(
            children: [
              Icon(icon, size: 36, color: fg),
              const SizedBox(width: 16),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      title,
                      key: const ValueKey('lock-state'),
                      style: t.headlineSmall?.copyWith(color: fg),
                    ),
                    Text(detail, style: t.bodyMedium?.copyWith(color: fg)),
                  ],
                ),
              ),
              for (final a in actions) Padding(padding: const EdgeInsets.only(left: 12), child: a),
            ],
          ),
        ),
      ),
    );
  }
}
