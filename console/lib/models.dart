// Typed views of what Core sends. Formats: docs/rules_format.md and core/fortress_core/api.py.

const itemKinds = <String, String>{
  'domains': 'Websites',
  'android_packages': 'Android apps',
  'windows_programs': 'Windows programs',
};

const itemHints = <String, String>{
  'domains': 'tiktok.com or *.reddit.com',
  'android_packages': 'com.zhiliaoapp.musically',
  'windows_programs': 'steam.exe',
};

const weekDays = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'];

DateTime? _time(Object? v) => v is String ? DateTime.tryParse(v) : null;
List<String> _strings(Object? v) => [for (final x in (v as List? ?? const [])) '$x'];

class Status {
  Status({
    required this.setUp,
    required this.state,
    this.unlocksAt,
    this.now,
    this.version = 0,
    this.keyId = '',
    this.unpublishedChanges = false,
    this.lockedUntil,
    this.unlockDelayMinutes = 0,
    this.relockMinutes = 15,
    this.devices = const [],
    this.activeSchedules = const [],
  });

  factory Status.fromJson(Map<String, dynamic> j) => Status(
    setUp: j['set_up'] == true,
    state: j['state'] as String? ?? 'locked',
    unlocksAt: _time(j['unlocks_at']),
    now: _time(j['now']),
    version: j['version'] as int? ?? 0,
    keyId: j['key_id'] as String? ?? '',
    unpublishedChanges: j['unpublished_changes'] == true,
    lockedUntil: _time(j['locked_until']),
    unlockDelayMinutes: j['unlock_delay_minutes'] as int? ?? 0,
    relockMinutes: j['relock_minutes'] as int? ?? 15,
    devices: [for (final d in (j['devices'] as List? ?? const [])) Device.fromJson(d as Map<String, dynamic>)],
    activeSchedules: _strings(j['active_schedules']),
  );

  final bool setUp;
  final String state; // locked | pending | unlocked
  final DateTime? unlocksAt;
  final DateTime? now;
  final int version;
  final String keyId;
  final bool unpublishedChanges;
  final DateTime? lockedUntil;
  final int unlockDelayMinutes;
  final int relockMinutes;
  final List<Device> devices;
  final List<String> activeSchedules;

  bool get isLocked => state == 'locked';
  bool get isPending => state == 'pending';
  bool get isUnlocked => state == 'unlocked';
}

class Device {
  Device({
    required this.id,
    required this.name,
    required this.platform,
    this.lastSeen,
    this.status = 'never',
    this.activeSchedules = const [],
  });

  factory Device.fromJson(Map<String, dynamic> j) => Device(
    id: j['id'] as String,
    name: j['name'] as String,
    platform: j['platform'] as String,
    lastSeen: _time(j['last_seen']),
    status: j['status'] as String? ?? 'never',
    activeSchedules: _strings(j['active_schedules']),
  );

  final String id;
  final String name;
  final String platform; // android | windows
  final DateTime? lastSeen;
  final String status; // ok | amber | red | never
  final List<String> activeSchedules;
}

class Rules {
  Rules({required this.lists, required this.schedules, required this.allow});

  factory Rules.fromJson(Map<String, dynamic> j) => Rules(
    lists: {
      for (final e in (j['lists'] as Map<String, dynamic>? ?? const {}).entries)
        e.key: {for (final k in itemKinds.keys) k: _strings((e.value as Map)[k])},
    },
    schedules: [for (final s in (j['schedules'] as List? ?? const [])) Schedule.fromJson(s as Map<String, dynamic>)],
    allow: {for (final k in itemKinds.keys) k: _strings((j['allow'] as Map? ?? const {})[k])},
  );

  /// list name → item kind → items
  final Map<String, Map<String, List<String>>> lists;
  final List<Schedule> schedules;

  /// item kind → always-allowed items
  final Map<String, List<String>> allow;

  Schedule? schedule(String id) {
    for (final s in schedules) {
      if (s.id == id) return s;
    }
    return null;
  }
}

class Schedule {
  Schedule({
    required this.id,
    required this.list,
    required this.devices,
    required this.kind,
    this.days = const [],
    this.from,
    this.to,
    this.tz,
    this.start,
    this.end,
  });

  factory Schedule.fromJson(Map<String, dynamic> j) => Schedule(
    id: j['id'] as String,
    list: j['list'] as String,
    devices: _strings(j['devices']),
    kind: j['kind'] as String,
    days: _strings(j['days']),
    from: j['from'] as String?,
    to: j['to'] as String?,
    tz: j['tz'] as String?,
    start: _time(j['start']),
    end: _time(j['end']),
  );

  final String id;
  final String list;
  final List<String> devices;
  final String kind; // weekly | once
  final List<String> days;
  final String? from;
  final String? to;
  final String? tz;
  final DateTime? start;
  final DateTime? end;

  bool get isWeekly => kind == 'weekly';

  /// "Mon–Fri 08:00–15:00" or "until Mon 14:30".
  String when() {
    if (!isWeekly) {
      return '${shortDateTime(start!)} → ${shortDateTime(end!)}';
    }
    final window = from == to ? 'all day' : '$from–$to${_overnight ? ' (overnight)' : ''}';
    return '${describeDays(days)} $window, $tz';
  }

  bool get _overnight => from != null && to != null && from!.compareTo(to!) > 0;

  String target() => devices.contains('all') ? 'all devices' : devices.join(', ');
}

String describeDays(List<String> days) {
  final idx = [for (final d in days) weekDays.indexOf(d)]..sort();
  if (idx.length == 7) return 'Every day';
  final key = idx.join(',');
  if (key == '0,1,2,3,4') return 'Mon–Fri';
  if (key == '5,6') return 'Weekends';
  return idx.map((i) => _cap(weekDays[i])).join(', ');
}

String _cap(String s) => s[0].toUpperCase() + s.substring(1);

String two(int n) => n.toString().padLeft(2, '0');

/// Local time, e.g. "Mon 19 Oct 14:30".
String shortDateTime(DateTime t) {
  final l = t.toLocal();
  const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  return '${_cap(weekDays[l.weekday - 1])} ${l.day} ${months[l.month - 1]} ${two(l.hour)}:${two(l.minute)}';
}

String clockTime(DateTime t) {
  final l = t.toLocal();
  return '${two(l.hour)}:${two(l.minute)}:${two(l.second)}';
}

class ActivityEntry {
  ActivityEntry(this.at, this.kind, this.detail);

  factory ActivityEntry.fromJson(Map<String, dynamic> j) =>
      ActivityEntry(DateTime.parse(j['at'] as String), j['kind'] as String, j['detail'] as String? ?? '');

  final DateTime at;
  final String kind;
  final String detail;
}
