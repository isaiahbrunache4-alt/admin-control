// What the Console knows about Core, kept fresh by polling, and every action it takes.

import 'dart:async';

import 'package:flutter/foundation.dart';

import 'api.dart';
import 'models.dart';

class ConsoleState extends ChangeNotifier {
  ConsoleState(this.api, {this.pollEvery = const Duration(seconds: 5)});

  final FortressApi api;

  /// How often to re-read Core. Null turns polling off (tests).
  final Duration? pollEvery;
  Timer? _timer;

  Status? status;
  Rules? rules;
  List<ActivityEntry> activity = const [];

  /// False when the last request could not reach Core at all.
  bool reachable = true;
  bool loaded = false;

  /// Last-used time zone for new schedules. Core checks it; the default is assumed.
  String timeZone = 'America/New_York';

  /// Changes are allowed only while unlocked, and only with this Console's session token.
  bool get canEdit => status?.isUnlocked == true && api.token != null;

  Future<void> start() async {
    await refresh();
    if (pollEvery != null) {
      _timer = Timer.periodic(pollEvery!, (_) => refresh());
    }
  }

  Future<void> refresh() async {
    try {
      final s = Status.fromJson(await api.status());
      if (s.setUp) {
        rules = Rules.fromJson(await api.rules());
        activity = [for (final a in await api.activity()) ActivityEntry.fromJson(a as Map<String, dynamic>)];
      }
      _setStatus(s);
      reachable = true;
    } on CoreUnreachable {
      reachable = false;
    } on ApiError {
      // Leave what we have on screen; the next poll tries again.
    }
    loaded = true;
    notifyListeners();
  }

  void _setStatus(Status s) {
    status = s;
    if (s.isLocked) api.token = null;
  }

  /// Take in a response that carries the status, and the rules if it has them.
  void _apply(Json r) {
    _setStatus(Status.fromJson({'set_up': true, ...r}));
    if (r['rules'] is Map<String, dynamic>) {
      rules = Rules.fromJson(r['rules'] as Map<String, dynamic>);
    }
    reachable = true;
    notifyListeners();
  }

  // ---- setup, lock, unlock

  Future<String> setup(String password) async {
    final code = await api.setup(password);
    await refresh();
    return code;
  }

  Future<void> unlock(String password) async => _apply(await api.unlock(password));

  Future<void> lock() async {
    try {
      _apply(await api.lock());
    } on ApiError {
      await refresh();
    }
  }

  Future<void> recover(String code, String newPassword) async => _apply(await api.recover(code, newPassword));

  /// Run a change. A 423 means the unlock ended under us; re-read so the screen drops
  /// to read-only, then let the caller show the message.
  Future<void> edit(Future<Json> Function(FortressApi api) change) async {
    try {
      _apply(await change(api));
    } on ApiError catch (e) {
      if (e.isLocked) await refresh();
      rethrow;
    }
    unawaited(_refreshActivity());
  }

  /// A one-time enrolment code for a device's Agent.
  Future<Enrolment> startEnrolment(String deviceId) async {
    try {
      final e = Enrolment.fromJson(await api.startEnrolment(deviceId));
      unawaited(_refreshActivity());
      return e;
    } on ApiError catch (e) {
      if (e.isLocked) await refresh();
      rethrow;
    }
  }

  Future<void> _refreshActivity() async {
    try {
      activity = [for (final a in await api.activity()) ActivityEntry.fromJson(a as Map<String, dynamic>)];
      notifyListeners();
    } on Exception {
      // Polling will catch up.
    }
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }
}
