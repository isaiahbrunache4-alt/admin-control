// A small in-memory stand-in for Fortress Core, enough for widget tests. The real
// contract is checked against the live Core in core_contract_test.dart.

import 'dart:convert';

import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

class FakeCore {
  FakeCore({this.setUp = true, this.password = 'right password'});

  bool setUp;
  String password;
  bool up = true;
  String state = 'locked';
  String? token;
  int version = 1;
  bool dirty = false;
  int _tokens = 0;
  final lists = <String, Map<String, List<String>>>{};
  final schedules = <Map<String, dynamic>>[];
  final allow = <String, List<String>>{
    'domains': ['github.com'],
    'android_packages': ['com.shotput.app'],
    'windows_programs': <String>[],
  };
  final devices = <Map<String, dynamic>>[];
  final activity = <Map<String, dynamic>>[];
  final calls = <String>[];

  late final client = MockClient(_handle);

  /// Simulate auto-relock on Core's side.
  void relock() {
    if (dirty) _publish();
    state = 'locked';
    token = null;
  }

  Map<String, dynamic> _rules() => {'lists': lists, 'schedules': schedules, 'allow': allow};

  Map<String, dynamic> _status() => !setUp
      ? {'set_up': false, 'state': 'locked'}
      : {
          'set_up': true,
          'state': state,
          'unlocks_at': null,
          'now': '2026-10-19T12:00:00Z',
          'version': version,
          'key_id': 'abcdef0123456789',
          'unpublished_changes': dirty,
          'locked_until': null,
          'unlock_delay_minutes': 0,
          'relock_minutes': 15,
          'devices': devices,
          'active_schedules': <String>[],
        };

  void _publish() {
    version++;
    dirty = false;
    _log('publish', 'version $version');
  }

  void _log(String kind, [String detail = '']) =>
      activity.insert(0, {'at': '2026-10-19T12:00:00Z', 'kind': kind, 'detail': detail});

  http.Response _json(Object body, [int code = 200]) =>
      http.Response(jsonEncode(body), code, headers: {'content-type': 'application/json'});

  http.Response _err(int code, String kind, String message) => _json({'error': kind, 'message': message}, code);

  Future<http.Response> _handle(http.Request req) async {
    if (!up) throw http.ClientException('Connection refused');
    final path = req.url.path.replaceFirst('/api/v1/', '');
    calls.add('${req.method} $path');
    final body = req.body.isEmpty ? <String, dynamic>{} : jsonDecode(req.body) as Map<String, dynamic>;

    if (req.method == 'GET') {
      return switch (path) {
        'status' => _json(_status()),
        'rules' => setUp ? _json(_rules()) : _err(409, 'not_set_up', 'run setup first'),
        'activity' => _json(activity),
        _ => _err(404, 'http_404', 'not found'),
      };
    }
    switch (path) {
      case 'setup':
        setUp = true;
        password = body['password'] as String;
        _publish();
        return _json({'recovery_code': 'ABCD-EFGH-JKMN-PQRS-TUVW-XYZ2'});
      case 'unlock':
        if (body['password'] != password) {
          _log('wrong_password');
          return _err(401, 'wrong_password', 'wrong password');
        }
        state = 'unlocked';
        token = 'token-${++_tokens}';
        return _json({'token': token, ..._status()});
    }

    // Everything else is a change and needs the session token.
    if (state != 'unlocked' || req.headers['Authorization'] != 'Bearer $token') {
      return _err(423, 'locked', 'unlock first');
    }
    Map<String, dynamic> done() {
      dirty = true;
      return {'rules': _rules(), ..._status()};
    }

    if (path == 'lock') {
      relock();
      return _json(_status());
    }
    if (path == 'publish') {
      _publish();
      return _json({'rules': _rules(), ..._status()});
    }
    if (path == 'lists') {
      final name = body['name'] as String;
      if (lists.containsKey(name)) return _err(400, 'invalid', "list '$name' already exists");
      lists[name] = {'domains': [], 'android_packages': [], 'windows_programs': []};
      return _json(done());
    }
    final item = RegExp(r'^lists/([^/]+)/items$').firstMatch(path);
    if (item != null) {
      final v = (body['item'] as String).toLowerCase();
      if (v.contains('/')) return _err(400, 'invalid', "give a domain, not a URL: '$v'");
      lists[item[1]!]![body['kind'] as String]!.add(v);
      return _json(done());
    }
    if (path == 'devices') {
      devices.add({
        ...body,
        'added_at': '2026-10-19T12:00:00Z',
        'last_seen': null,
        'status': 'never',
        'active_schedules': [],
      });
      return _json(done());
    }
    if (path == 'schedules' || path == 'block-now') {
      final id = 's${schedules.length + 1}';
      schedules.add({
        'id': id,
        'kind': path == 'schedules' ? 'weekly' : 'once',
        ...body,
        if (path == 'block-now') ...{'start': '2026-10-19T12:00:00Z', 'end': '2026-10-19T14:00:00Z'},
      });
      return _json({...done(), 'id': id});
    }
    return _err(404, 'http_404', 'not found: $path');
  }
}
