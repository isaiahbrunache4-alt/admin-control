import 'package:flutter/material.dart';

import '../models.dart';
import '../state.dart';
import 'common.dart';

Color deviceColor(BuildContext context, String status) => switch (status) {
  'ok' => Colors.green.shade600,
  'amber' => Colors.amber.shade700,
  'red' => Theme.of(context).colorScheme.error,
  _ => Theme.of(context).colorScheme.outline,
};

String deviceStatusText(Device d) => switch (d.status) {
  'never' => 'Never checked in',
  'amber' => 'Quiet for over 24 h · last check-in ${shortDateTime(d.lastSeen!)}',
  'red' => 'Quiet for over 72 h · last check-in ${shortDateTime(d.lastSeen!)}',
  _ => 'Last check-in ${shortDateTime(d.lastSeen!)}',
};

/// What the device's Agent has: enrolled or not, and whether it has the latest rules.
String agentText(Device d, int latest) {
  if (!d.enrolled) return 'Agent not enrolled';
  final held = d.versionHeld;
  if (held == null) return 'Agent enrolled · no check-in yet';
  if (held < latest) return 'Agent has rules v$held of v$latest · gets the rest at its next check-in';
  return 'Agent up to date (rules v$held${d.agentVersion == null ? '' : ', Agent ${d.agentVersion}'})';
}

class DashboardScreen extends StatelessWidget {
  const DashboardScreen({super.key, required this.state});

  final ConsoleState state;

  @override
  Widget build(BuildContext context) {
    final s = state.status!;
    final rules = state.rules;
    return ListView(
      padding: const EdgeInsets.all(24),
      children: [
        const ScreenTitle('Dashboard'),
        Section(
          title: 'Blocks active now',
          child: s.activeSchedules.isEmpty
              ? const Text('Nothing is blocked right now.')
              : Column(
                  children: [for (final id in s.activeSchedules) _ActiveBlock(id: id, schedule: rules?.schedule(id))],
                ),
        ),
        Section(
          title: 'Devices',
          child: s.devices.isEmpty
              ? const Text('No devices yet. Add each device, this PC included, under Devices.')
              : Column(
                  children: [
                    for (final d in s.devices)
                      ListTile(
                        contentPadding: EdgeInsets.zero,
                        leading: Icon(
                          d.platform == 'windows' ? Icons.computer : Icons.smartphone,
                          color: deviceColor(context, d.status),
                        ),
                        title: Text(d.name),
                        subtitle: Text('${deviceStatusText(d)}\n${agentText(d, s.version)}'),
                        isThreeLine: true,
                        trailing: Text(
                          d.activeSchedules.isEmpty
                              ? 'No blocks now'
                              : '${d.activeSchedules.length} block${d.activeSchedules.length == 1 ? '' : 's'} now',
                        ),
                      ),
                  ],
                ),
        ),
        Section(
          title: 'Fortress',
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              _Fact(
                'Published rules',
                'version ${s.version}${s.unpublishedChanges ? ' · unpublished changes waiting' : ''}',
              ),
              _Fact('Signing key', s.keyId),
              _Fact('Unlock delay', s.unlockDelayMinutes == 0 ? 'none' : '${s.unlockDelayMinutes} min'),
              _Fact('Auto-relock', 'after ${s.relockMinutes} min idle'),
              if (s.lockedUntil != null) _Fact('Locked until', shortDateTime(s.lockedUntil!)),
            ],
          ),
        ),
      ],
    );
  }
}

class _ActiveBlock extends StatelessWidget {
  const _ActiveBlock({required this.id, required this.schedule});

  final String id;
  final Schedule? schedule;

  @override
  Widget build(BuildContext context) {
    final s = schedule;
    return ListTile(
      contentPadding: EdgeInsets.zero,
      leading: Icon(s?.isWeekly == false ? Icons.timer_outlined : Icons.block),
      title: Text(s == null ? 'Schedule $id' : s.list),
      subtitle: Text(
        s == null ? 'Removed from the draft; still in force until published' : '${s.when()} · ${s.target()}',
      ),
    );
  }
}

class _Fact extends StatelessWidget {
  const _Fact(this.label, this.value);

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 160,
            child: Text(label, style: TextStyle(color: Theme.of(context).colorScheme.onSurfaceVariant)),
          ),
          Expanded(child: SelectableText(value)),
        ],
      ),
    );
  }
}
