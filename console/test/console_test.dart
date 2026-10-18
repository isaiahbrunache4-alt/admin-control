import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:fortress_console/api.dart';
import 'package:fortress_console/models.dart';
import 'package:fortress_console/state.dart';
import 'package:fortress_console/ui/app.dart';
import 'package:fortress_console/ui/dashboard.dart';

import 'fake_core.dart';

Future<(FakeCore, ConsoleState)> boot(WidgetTester tester, {FakeCore? core}) async {
  tester.view.physicalSize = const Size(1400, 1000);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  core ??= FakeCore();
  final state = ConsoleState(FortressApi(client: core.client), pollEvery: null);
  addTearDown(state.dispose);
  await state.start();
  await tester.pumpWidget(ConsoleApp(state: state));
  await tester.pumpAndSettle();
  return (core, state);
}

Future<void> unlock(WidgetTester tester, String password) async {
  await tester.tap(find.byKey(const ValueKey('unlock-button')));
  await tester.pumpAndSettle();
  await tester.enterText(find.byKey(const ValueKey('unlock-password')), password);
  await tester.tap(find.widgetWithText(FilledButton, 'Unlock').last);
  await tester.pumpAndSettle();
}

Future<void> go(WidgetTester tester, String screen) async {
  await tester.tap(find.descendant(of: find.byType(NavigationRail), matching: find.text(screen)));
  await tester.pumpAndSettle();
}

String lockState(WidgetTester tester) => tester.widget<Text>(find.byKey(const ValueKey('lock-state'))).data!;

bool enabled(WidgetTester tester, Finder button) => tester.widget<ButtonStyleButton>(button).onPressed != null;

void main() {
  testWidgets('says so when Core is not running, and recovers', (tester) async {
    final core = FakeCore()..up = false;
    final (_, state) = await boot(tester, core: core);
    expect(find.text('Fortress Core is not running'), findsOneWidget);
    core.up = true;
    await tester.tap(find.text('Try again'));
    await tester.pumpAndSettle();
    expect(lockState(tester), 'Locked');
    expect(state.reachable, isTrue);
  });

  testWidgets('first run: set password, show the recovery code once, land locked', (tester) async {
    final (core, _) = await boot(tester, core: FakeCore(setUp: false));
    expect(find.text('Set up Fortress'), findsWidgets);

    await tester.enterText(find.byKey(const ValueKey('setup-password')), 'short');
    await tester.tap(find.widgetWithText(FilledButton, 'Set up Fortress'));
    await tester.pumpAndSettle();
    expect(find.text('At least 8 characters'), findsOneWidget);

    await tester.enterText(find.byKey(const ValueKey('setup-password')), 'a long password');
    await tester.enterText(find.byKey(const ValueKey('setup-again')), 'a long password');
    await tester.tap(find.widgetWithText(FilledButton, 'Set up Fortress'));
    await tester.pumpAndSettle();

    expect(find.text('ABCD-EFGH-JKMN-PQRS-TUVW-XYZ2'), findsOneWidget);
    final cont = find.widgetWithText(FilledButton, 'Continue');
    expect(enabled(tester, cont), isFalse);
    await tester.tap(find.text('I have written it down'));
    await tester.pump();
    await tester.tap(cont);
    await tester.pumpAndSettle();

    expect(core.password, 'a long password');
    expect(lockState(tester), 'Locked');
  });

  testWidgets('locked is read-only; wrong password is refused', (tester) async {
    await boot(tester);
    await go(tester, 'Block lists');
    expect(find.text('Read-only. Unlock to make changes.'), findsOneWidget);
    expect(enabled(tester, find.widgetWithText(FilledButton, 'New list')), isFalse);

    await unlock(tester, 'wrong password');
    expect(find.byKey(const ValueKey('unlock-error')), findsOneWidget);
    expect(find.text('Wrong password'), findsOneWidget);
  });

  testWidgets('unlock, build a list, schedule it, lock and publish', (tester) async {
    final (core, _) = await boot(tester);
    await unlock(tester, 'right password');
    expect(lockState(tester), 'Unlocked');

    await go(tester, 'Block lists');
    await tester.tap(find.widgetWithText(FilledButton, 'New list'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const ValueKey('new-list-name')), 'Social');
    await tester.tap(find.widgetWithText(FilledButton, 'Create'));
    await tester.pumpAndSettle();
    expect(find.text('Lower-case letters, digits, - or _, up to 40'), findsOneWidget);
    await tester.enterText(find.byKey(const ValueKey('new-list-name')), 'social');
    await tester.tap(find.widgetWithText(FilledButton, 'Create'));
    await tester.pumpAndSettle();
    expect(core.lists.keys, ['social']);

    await tester.enterText(find.byKey(const ValueKey('add-domains')), 'tiktok.com');
    await tester.testTextInput.receiveAction(TextInputAction.done);
    await tester.pumpAndSettle();
    expect(find.widgetWithText(InputChip, 'tiktok.com'), findsOneWidget);

    // Core's refusal is shown, and the text stays for fixing.
    await tester.enterText(find.byKey(const ValueKey('add-domains')), 'https://youtube.com/');
    await tester.testTextInput.receiveAction(TextInputAction.done);
    await tester.pumpAndSettle();
    expect(find.textContaining('not a URL'), findsOneWidget);

    await go(tester, 'Schedules');
    await tester.tap(find.widgetWithText(FilledButton, 'Weekly schedule'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const ValueKey('weekly-from')), '22:00');
    await tester.enterText(find.byKey(const ValueKey('weekly-to')), '06:00');
    await tester.pump();
    expect(find.textContaining('Overnight'), findsOneWidget);
    await tester.tap(find.widgetWithText(FilledButton, 'Add schedule'));
    await tester.pumpAndSettle();
    expect(core.schedules.single['days'], ['mon', 'tue', 'wed', 'thu', 'fri']);
    expect(find.text('Mon–Fri 22:00–06:00 (overnight), America/New_York · all devices'), findsOneWidget);

    expect(find.widgetWithText(FilledButton, 'Lock and publish'), findsOneWidget);
    await tester.tap(find.byKey(const ValueKey('lock-button')));
    await tester.pumpAndSettle();
    expect(lockState(tester), 'Locked');
    expect(core.version, 2);
    expect(enabled(tester, find.widgetWithText(FilledButton, 'Weekly schedule')), isFalse);
  });

  testWidgets('an unlock that ends under us drops the screen to read-only', (tester) async {
    final (core, _) = await boot(tester);
    await unlock(tester, 'right password');
    await go(tester, 'Block lists');

    core.relock(); // Core auto-relocked
    await tester.tap(find.widgetWithText(FilledButton, 'New list'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const ValueKey('new-list-name')), 'games');
    await tester.tap(find.widgetWithText(FilledButton, 'Create'));
    await tester.pumpAndSettle();

    expect(find.text('Fortress is locked. Unlock to make changes.'), findsOneWidget);
    expect(lockState(tester), 'Locked');
    expect(core.lists, isEmpty);
  });

  testWidgets('add a device; dashboard lists it', (tester) async {
    final (core, _) = await boot(tester);
    await unlock(tester, 'right password');
    await go(tester, 'Devices');
    await tester.tap(find.widgetWithText(FilledButton, 'Add device'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const ValueKey('device-name')), 'Lenovo Idea Tab');
    await tester.pump();
    expect(find.widgetWithText(TextFormField, 'lenovo-idea-tab'), findsOneWidget);
    await tester.tap(find.widgetWithText(FilledButton, 'Add'));
    await tester.pumpAndSettle();
    expect(core.devices.single['id'], 'lenovo-idea-tab');
    expect(find.textContaining('Agent not enrolled'), findsOneWidget);

    // Enrol: the code, the PC's address and the device id, to type on the tablet.
    await tester.tap(find.byKey(const ValueKey('enrol-lenovo-idea-tab')));
    await tester.pumpAndSettle();
    expect(find.text('Enrol Lenovo Idea Tab'), findsOneWidget);
    expect(find.text('ABCDE-FGHJK'), findsOneWidget);
    expect(find.text('192.168.1.20'), findsOneWidget);
    expect(find.text('lenovo-idea-tab'), findsWidgets);
    await tester.tap(find.widgetWithText(FilledButton, 'Done'));
    await tester.pumpAndSettle();

    await go(tester, 'Dashboard');
    expect(find.text('Lenovo Idea Tab'), findsOneWidget);
    expect(find.text('Never checked in\nAgent not enrolled'), findsOneWidget);
  });

  testWidgets('enrolling needs the unlock', (tester) async {
    final (core, _) = await boot(tester);
    await unlock(tester, 'right password');
    await go(tester, 'Devices');
    await tester.tap(find.widgetWithText(FilledButton, 'Add device'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const ValueKey('device-name')), 'tablet');
    await tester.tap(find.widgetWithText(FilledButton, 'Add'));
    await tester.pumpAndSettle();
    core.relock();
    await tester.tap(find.byKey(const ValueKey('enrol-tablet')));
    await tester.pumpAndSettle();
    expect(find.text('Fortress is locked. Unlock to make changes.'), findsOneWidget);
    expect(find.text('Enrol tablet'), findsNothing);
    expect(lockState(tester), 'Locked');
  });

  group('models', () {
    test('agent status line', () {
      Device d({bool enrolled = true, int? held}) =>
          Device(id: 'tablet', name: 'Tab', platform: 'android', enrolled: enrolled, versionHeld: held);
      expect(agentText(d(enrolled: false), 5), 'Agent not enrolled');
      expect(agentText(d(), 5), 'Agent enrolled · no check-in yet');
      expect(agentText(d(held: 4), 5), startsWith('Agent has rules v4 of v5'));
      expect(agentText(d(held: 5), 5), 'Agent up to date (rules v5)');
    });

    test('describeDays', () {
      expect(describeDays(['fri', 'mon', 'tue', 'wed', 'thu']), 'Mon–Fri');
      expect(describeDays(['sat', 'sun']), 'Weekends');
      expect(describeDays(weekDays), 'Every day');
      expect(describeDays(['sun', 'wed']), 'Wed, Sun');
    });

    test('weekly schedule text', () {
      Schedule s(String from, String to) => Schedule(
        id: 's1',
        list: 'social',
        devices: ['tablet', 'pixel'],
        kind: 'weekly',
        days: ['mon'],
        from: from,
        to: to,
        tz: 'UTC',
      );
      expect(s('08:00', '15:00').when(), 'Mon 08:00–15:00, UTC');
      expect(s('22:00', '06:00').when(), 'Mon 22:00–06:00 (overnight), UTC');
      expect(s('00:00', '00:00').when(), 'Mon all day, UTC');
      expect(s('08:00', '15:00').target(), 'tablet, pixel');
    });
  });
}
