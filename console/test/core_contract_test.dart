// Drives a real, freshly set-up Fortress Core through every call the Console makes, and
// parses every answer with the Console's models. Skipped unless Core is running:
//
//   fortress --db /tmp/contract.db serve --port 47811 &
//   FORTRESS_CORE_URL=http://127.0.0.1:47811/api/v1/ flutter test test/core_contract_test.dart

import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:fortress_console/api.dart';
import 'package:fortress_console/models.dart';

void main() {
  final url = Platform.environment['FORTRESS_CORE_URL'];

  test('Console ↔ Core contract', () async {
    final api = FortressApi(base: Uri.parse(url!));
    const pw = 'contract password';

    var status = Status.fromJson(await api.status());
    expect(status.setUp, isFalse, reason: 'start Core on an empty database');
    final code = await api.setup(pw);
    expect(code, matches(RegExp(r'^[A-Z2-9]{4}(-[A-Z2-9]{4}){5}$')));

    status = Status.fromJson(await api.status());
    expect(status.isLocked, isTrue);
    expect(status.version, 1);
    var rules = Rules.fromJson(await api.rules());
    expect(rules.allow['domains'], contains('github.com'));

    // Locked: changes refused.
    await expectLater(api.addList('social'), throwsA(isA<ApiError>().having((e) => e.status, 'status', 423)));

    // Wrong password, then the growing delay.
    await expectLater(
      api.unlock('wrong password'),
      throwsA(isA<ApiError>().having((e) => e.kind, 'kind', 'wrong_password')),
    );
    final tooSoon = await api.unlock(pw).then<ApiError?>((_) => null, onError: (Object e) => e as ApiError);
    expect(tooSoon?.isTooSoon, isTrue);
    expect(tooSoon?.retryAfter, isNotNull);
    await Future<void>.delayed(const Duration(milliseconds: 1100));

    final unlocked = Status.fromJson(await api.unlock(pw));
    expect(unlocked.isUnlocked, isTrue);
    expect(api.token, isNotNull);

    await api.addDevice('tablet', 'Lenovo Idea Tab', 'android');
    await api.addDevice('pc', 'This PC', 'windows');
    final enrolment = Enrolment.fromJson(await api.startEnrolment('tablet'));
    expect(enrolment.code, matches(RegExp(r'^[A-Z2-9]{5}-[A-Z2-9]{5}$')));
    expect(enrolment.deviceId, 'tablet');
    expect(enrolment.keyId, status.keyId);
    expect(enrolment.expiresAt.isAfter(DateTime.now()), isTrue);
    await expectLater(api.startEnrolment('nobody'), throwsA(isA<ApiError>().having((e) => e.status, 'status', 400)));
    await api.addList('social');
    await api.addItem('social', 'domains', 'TikTok.com');
    await api.addItem('social', 'domains', '*.reddit.com');
    await api.addItem('social', 'android_packages', 'com.zhiliaoapp.musically');
    var r = await api.addItem('social', 'windows_programs', 'Steam.exe');
    rules = Rules.fromJson(r['rules'] as Json);
    expect(rules.lists['social']!['domains'], ['*.reddit.com', 'tiktok.com']);
    expect(rules.lists['social']!['windows_programs'], ['steam.exe']);
    await api.removeItem('social', 'domains', '*.reddit.com');

    // Validation errors come back readable.
    await expectLater(
      api.addItem('social', 'domains', 'https://x.com/'),
      throwsA(isA<ApiError>().having((e) => e.message, 'message', contains('URL'))),
    );
    await expectLater(
      api.addItem('social', 'tweets', 'x'),
      throwsA(isA<ApiError>().having((e) => e.status, 'status', 422)),
    );

    r = await api.addWeekly(
      list: 'social',
      devices: ['tablet'],
      days: ['mon', 'tue'],
      from: '22:00',
      to: '06:00',
      tz: 'America/New_York',
    );
    final weeklyId = r['id'] as String;
    r = await api.blockNow('social', 1, ['all']);
    final onceId = r['id'] as String;
    rules = Rules.fromJson(r['rules'] as Json);
    expect(rules.schedule(weeklyId)!.when(), 'Mon, Tue 22:00–06:00 (overnight), America/New_York');
    expect(rules.schedule(onceId)!.isWeekly, isFalse);
    expect(Status.fromJson(r).unpublishedChanges, isTrue);

    await api.allow('domains', 'example.org');
    await api.disallow('domains', 'example.org');
    await api.settings(unlockDelayMinutes: 0, relockMinutes: 30);

    status = Status.fromJson(await api.publish());
    expect(status.version, 2);
    expect(status.unpublishedChanges, isFalse);
    expect(status.activeSchedules, contains(onceId));
    expect(status.devices.map((d) => d.id), ['tablet', 'pc']);
    expect(status.devices.first.status, 'never');
    expect(status.relockMinutes, 30);

    await api.removeSchedule(onceId);
    await api.removeDevice('pc'); // publishes a release
    status = Status.fromJson(await api.status());
    expect(status.devices.map((d) => d.id), ['tablet']);
    expect(status.version, 3);

    await api.changePassword(pw, 'second password');
    status = Status.fromJson(await api.lock());
    expect(status.isLocked, isTrue);
    expect(api.token, isNull);

    status = Status.fromJson(await api.recover(code.toLowerCase(), 'third password'));
    expect(status.isLocked, isTrue);
    await api.unlock('third password');
    final until = DateTime.now().add(const Duration(minutes: 5));
    status = Status.fromJson(await api.lockUntil(until));
    expect(status.isLocked, isTrue);
    expect(status.lockedUntil!.difference(until.toUtc()).inSeconds.abs(), lessThan(2));
    final locked = await api
        .unlock('third password')
        .then<ApiError?>((_) => null, onError: (Object e) => e as ApiError);
    expect(locked?.isTooSoon, isTrue);

    final activity = [for (final a in await api.activity()) ActivityEntry.fromJson(a as Json)];
    expect(activity.map((a) => a.kind), containsAll(['wrong_password', 'publish', 'password_reset']));
    expect((await api.bundle())['format'], 1);
    api.close();
  }, skip: url == null ? 'set FORTRESS_CORE_URL to run against a live Core' : false);
}
