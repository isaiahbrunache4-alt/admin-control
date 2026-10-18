# Fortress

Self-control software for Isaiah's own devices. A Windows PC is the only control point;
the PC itself, a Pixel 8a and a Lenovo Idea Tab enforce website blocks, app blocks and scheduled blocks.
One password unlocks changes.

**Status:** Phases 1–2 (Core, Console) built and tested. Phase 3 (Android Agent, app
blocking) built and tested off-device; next is trying it on the tablet
([`android/README.md`](android/README.md)).

- Design: [`docs/fortress_design.md`](docs/fortress_design.md)
- Rules and bundle format, for Agents: [`docs/rules_format.md`](docs/rules_format.md)
- How Agents enrol and talk to Core: [`docs/agent_protocol.md`](docs/agent_protocol.md)
- Cases every Agent must pass, generated from Core: [`testdata/fortress_vectors.json`](testdata/fortress_vectors.json)

| Folder | What |
|---|---|
| `core/` | Fortress Core (Python): rules, password, signing, the Console and Agent APIs, the `fortress` command |
| `console/` | Fortress Console (Flutter, Windows): the main UI |
| `android/` | Fortress Agent for Android (Kotlin): the phone and the tablet |

## Core (Phase 1)

On Windows, in a normal (not administrator) PowerShell, in a folder you own such as your
home folder. Use Python from python.org (`winget install -e --id Python.Python.3.13`),
not the Microsoft Store one: Core will later run as a Windows service, which the Store
Python cannot do.

```powershell
cd core
& "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe" -m venv .venv
.\.venv\Scripts\pip install -e ".[test]"
.\.venv\Scripts\pytest
.\.venv\Scripts\fortress init
```

Elsewhere: `python -m venv .venv && .venv/bin/pip install -e '.[test]' && .venv/bin/pytest`.

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

## Agents

`fortress serve` also listens for device Agents on the home network, port **47801**
(`--no-agents` turns that off). A device joins with a one-time code from
**Devices → Enrol** in the unlocked Console (or `fortress device enrol ID`). The Android
Agent, how to build it and how to set up the tablet: [`android/README.md`](android/README.md).

After changing anything that decides blocking or the protocol in `core/`, regenerate the
shared cases and run every Agent's tests against them:

```
cd core && python -m tests.make_vectors
cd android && gradlew :agent-core:test
```
