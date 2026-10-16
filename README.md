# Fortress

Self-control software for Isaiah's own devices. A Windows PC is the only control point;
the PC itself, a Pixel 8a and a Lenovo Idea Tab enforce website blocks, app blocks and scheduled blocks.
One password unlocks changes.

**Status: Phases 1–2 built and tested** (Core and the Console). No device Agents yet.

- Design: [`docs/fortress_design.md`](docs/fortress_design.md)
- Rules and bundle format, for Agents: [`docs/rules_format.md`](docs/rules_format.md)

## Core (Phase 1)

```
cd core
python -m venv .venv
.venv/bin/pip install -e '.[test]'     # Windows: .venv\Scripts\pip
.venv/bin/pytest
```

The `fortress` command stands in for the Console until Phase 2:

```
fortress init                                   # set password, prints recovery code
fortress list add social
fortress item add social site tiktok.com *.reddit.com
fortress device add tablet android "Lenovo Idea Tab"
fortress schedule add social --devices tablet --days mon,tue,wed,thu,fri \
    --from 08:00 --to 15:00 --tz America/New_York
fortress block-now social 2
fortress check tablet site www.tiktok.com       # BLOCKED / allowed
fortress bundle --out bundle.json && fortress verify bundle.json
fortress status | show | activity | passwd | recover
```

Every changing command asks for the password, makes the change, then locks and
publishes a new signed bundle. The database defaults to `%PROGRAMDATA%\Fortress\fortress.db`
on Windows and `~/.fortress/fortress.db` elsewhere (`--db` to override).

## Console (Phase 2)

The main UI, a Flutter Windows desktop app. It talks to Core on `127.0.0.1:47800`, so
start Core first:

```
fortress serve                      # leave running
cd console
flutter run -d windows              # or: flutter build windows
flutter test
```

The Console shows everything while locked and changes nothing until unlocked; Lock
publishes any changes to the devices. Unlocking gives this Console a session token, so
no other program on the PC can make changes through Core while it is unlocked.

`test/core_contract_test.dart` drives a real Core through every call the Console makes.
Run it against a Core on an empty database:

```
fortress --db %TEMP%\contract.db serve --port 47811
set FORTRESS_CORE_URL=http://127.0.0.1:47811/api/v1/
flutter test test/core_contract_test.dart
```

Core does not install itself as a Windows service yet; `fortress serve` runs in the
foreground until then.
