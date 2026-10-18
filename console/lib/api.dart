// Client for Fortress Core's localhost API (core/fortress_core/api.py).
//
// Reading needs nothing. Every change sends the session token that unlock() returns;
// Core forgets it on lock or auto-relock, after which changes answer 423 Locked.

import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;

const defaultCoreUrl = 'http://127.0.0.1:47800/api/v1/';

/// Core refused the request. [kind] is Core's error code, e.g. `wrong_password`.
class ApiError implements Exception {
  ApiError(this.status, this.kind, this.message, {this.retryAfter});

  final int status;
  final String kind;
  final String message;
  final DateTime? retryAfter;

  bool get isLocked => status == 423;
  bool get isTooSoon => status == 429;

  @override
  String toString() => message;
}

/// Core is not answering: not running, or still starting.
class CoreUnreachable implements Exception {
  CoreUnreachable(this.cause);
  final Object cause;

  @override
  String toString() => 'Fortress Core is not answering';
}

typedef Json = Map<String, dynamic>;

class FortressApi {
  FortressApi({http.Client? client, Uri? base, this.timeout = const Duration(seconds: 15)})
    : _client = client ?? http.Client(),
      base = base ?? Uri.parse(defaultCoreUrl);

  final http.Client _client;
  final Uri base;
  final Duration timeout;

  /// The session token from the last successful unlock, if any.
  String? token;

  // ---- reading

  Future<Json> status() async => await _send('GET', 'status') as Json;
  Future<Json> rules() async => await _send('GET', 'rules') as Json;
  Future<List<dynamic>> activity({int limit = 100}) async =>
      await _send('GET', 'activity?limit=$limit') as List<dynamic>;
  Future<Json> bundle() async => await _send('GET', 'bundle') as Json;

  // ---- setup, lock, unlock

  /// First run. Returns the recovery code, which Core shows only this once.
  Future<String> setup(String password) async =>
      (await _post('setup', {'password': password}))['recovery_code'] as String;

  Future<Json> unlock(String password) async {
    final r = await _post('unlock', {'password': password});
    token = r['token'] as String;
    return r;
  }

  Future<Json> lock() async {
    try {
      return await _post('lock');
    } finally {
      token = null;
    }
  }

  Future<Json> recover(String code, String newPassword) async {
    token = null;
    return _post('recover', {'code': code, 'new_password': newPassword});
  }

  // ---- editing

  Future<Json> addList(String name) => _post('lists', {'name': name});
  Future<Json> removeList(String name) => _send('DELETE', 'lists/${_seg(name)}').then(_json);

  Future<Json> addItem(String list, String kind, String item) =>
      _post('lists/${_seg(list)}/items', {'kind': kind, 'item': item});
  Future<Json> removeItem(String list, String kind, String item) =>
      _post('lists/${_seg(list)}/items/remove', {'kind': kind, 'item': item});

  Future<Json> allow(String kind, String item) => _post('allow', {'kind': kind, 'item': item});
  Future<Json> disallow(String kind, String item) => _post('allow/remove', {'kind': kind, 'item': item});

  Future<Json> addWeekly({
    required String list,
    required List<String> devices,
    required List<String> days,
    required String from,
    required String to,
    required String tz,
  }) => _post('schedules', {'list': list, 'devices': devices, 'days': days, 'from': from, 'to': to, 'tz': tz});

  Future<Json> blockNow(String list, double hours, List<String> devices) =>
      _post('block-now', {'list': list, 'hours': hours, 'devices': devices});

  Future<Json> removeSchedule(String id) => _send('DELETE', 'schedules/${_seg(id)}').then(_json);

  Future<Json> addDevice(String id, String name, String platform) =>
      _post('devices', {'id': id, 'name': name, 'platform': platform});
  Future<Json> removeDevice(String id) => _send('DELETE', 'devices/${_seg(id)}').then(_json);

  /// A one-time code for the device's Agent to enrol with. Needs the unlock.
  Future<Json> startEnrolment(String id) => _post('devices/${_seg(id)}/enrolment');

  Future<Json> publish() => _post('publish');

  Future<Json> settings({int? unlockDelayMinutes, int? relockMinutes}) =>
      _post('settings', {'unlock_delay_minutes': ?unlockDelayMinutes, 'relock_minutes': ?relockMinutes});

  Future<Json> lockUntil(DateTime until) async {
    try {
      return await _post('lock-until', {'until': until.toUtc().toIso8601String()});
    } finally {
      token = null;
    }
  }

  Future<Json> changePassword(String current, String newPassword) =>
      _post('password', {'current': current, 'new': newPassword});

  // ---- plumbing

  static String _seg(String s) => Uri.encodeComponent(s);
  static Json _json(Object? v) => v as Json;

  Future<Json> _post(String path, [Json? body]) async => await _send('POST', path, body ?? const {}) as Json;

  Future<Object?> _send(String method, String path, [Json? body]) async {
    final req = http.Request(method, base.resolve(path));
    if (token != null) req.headers['Authorization'] = 'Bearer $token';
    if (body != null) {
      req.headers['Content-Type'] = 'application/json';
      req.body = jsonEncode(body);
    }
    final http.Response res;
    try {
      res = await http.Response.fromStream(await _client.send(req).timeout(timeout));
    } on http.ClientException catch (e) {
      throw CoreUnreachable(e);
    } on TimeoutException catch (e) {
      throw CoreUnreachable(e);
    }
    final Object? decoded = res.body.isEmpty ? null : jsonDecode(utf8.decode(res.bodyBytes));
    if (res.statusCode >= 200 && res.statusCode < 300) return decoded;
    throw _error(res.statusCode, decoded);
  }

  static ApiError _error(int status, Object? body) {
    if (body is Map && body['error'] is String) {
      final retry = body['retry_after'];
      return ApiError(
        status,
        body['error'] as String,
        '${body['message']}',
        retryAfter: retry is String ? DateTime.tryParse(retry) : null,
      );
    }
    // FastAPI's own validation errors: {"detail": [{"msg": ...}, ...]}
    if (body is Map && body['detail'] is List && (body['detail'] as List).isNotEmpty) {
      final first = (body['detail'] as List).first;
      return ApiError(status, 'invalid', first is Map ? '${first['msg']}' : '$first');
    }
    return ApiError(status, 'http_$status', 'Core answered $status');
  }

  void close() => _client.close();
}
