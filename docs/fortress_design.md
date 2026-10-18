# Fortress — Software Design (Spec 01, draft)

**Status: draft, for review. Phases 1–2 (Core `core/`, Console `console/`) are
implemented. Phase 3 (Android Agent, `android/`) is built and tested off-device; the
on-device check is still to do.** Agent protocol: `docs/agent_protocol.md` (approved
2026-10-18). Written 2026-10-16;
**revised 2026-10-16** to add the PC-layer lock and the "any device" model (§3, §7.2,
§8, §9); build order changed to PC lock last, and Windows Home noted (§11, §13).
Items that are assumptions rather than stated requirements are marked **assumed**.
Decisions still needed before code is written are listed in §12.

---

## 1. Purpose

Fortress is a **self-control** system for Isaiah's own devices. It blocks distracting
websites and apps, runs blocks on a schedule, and puts all control behind one computer
and one password.

**Fortress is the whole system, not one app.** It is one set of rules, one password
and one control point, plus an **Agent** for each kind of device. In principle any
device with an Agent can join. The computer is both the control point **and** a
locked device itself.

| Role | Device |
|---|---|
| **Command terminal**, the only place settings change | Windows PC |
| Enforced device: **PC layer** | The same Windows PC |
| Enforced device | **Google Pixel 8a** (Android) |
| Enforced device | **Lenovo Idea Tab** (Android) |

### Requirements

| # | Requirement | Section |
|---|---|---|
| R1 | The PC is the primary terminal | §3, §5 |
| R2 | **Unlocking on the PC is the only way to change or alter anything** | §6 |
| R3 | Enforced devices cannot drop out of Fortress | §7 |
| R4 | Website blocking | §8.1 |
| R5 | App blocking | §8.2 |
| R6 | Scheduled blocks | §8.3 |
| R7 | One main UI for the whole system | §5 |
| R8 | Lock / unlock, unlock only by password | §6 |
| R9 | Modelled on existing accountability software | §2 |
| R10 | Debugging still works on enforced devices | §10 |
| R11 | **A PC-layer lock**: the PC itself is limited the way the other devices are | §7.2, §8 |
| R12 | **Any device** can, in principle, run Fortress | §3.2 |

---

## 2. What it is modelled on

| Product | Idea borrowed |
|---|---|
| **Freedom** | Named block lists, recurring schedules, one set of rules synced to every device, PC and phone alike |
| **Cold Turkey** | A PC lock that its own UI cannot undo; locks survive reboot; password-only unlock |
| **Covenant Eyes** | Accountability: when a device stops reporting, the console shows it. The password can be held by a partner |
| **Google Family Link / Qustodio** | One console, several devices; per-app blocking; daily time windows |

Lesson taken from all of them: **software alone is a weak barrier against its own
owner.** What makes self-control software work is (a) using each operating system's
supported management features rather than tricks, and (b) **accountability**: someone
else holds the password, and dropping out is visible.

---

## 3. System overview

### 3.1 Layout

```
┌──────────────────────────────────────────────────┐
│ WINDOWS PC                                       │
│                                                  │
│  Fortress Console (Flutter desktop) — main UI    │
│        │ localhost only                          │
│  Fortress Core (Python service)                  │
│   ├─ rules database (SQLite)                     │
│   ├─ password check + rule signing               │
│   ├─ sync server (home Wi-Fi)                    │
│   └─ activity log                                │
│        │ signed rules (same path as phones)      │
│  Windows Agent  ── the PC-layer lock             │
└──────────────┬───────────────────────────────────┘
               │ signed rules ↓     check-ins ↑
       ┌───────┴─────────┐
       ▼                 ▼
┌──────────────┐  ┌──────────────┐
│ Pixel 8a     │  │ Lenovo       │
│ Android      │  │ Idea Tab     │
│ Agent        │  │ Android      │
│              │  │ Agent        │
└──────────────┘  └──────────────┘
```

Three rules hold everywhere:

1. **Every Agent accepts only rules signed by Fortress Core.** That includes the
   Windows Agent on the PC itself: it is treated exactly like a phone and gets no
   shortcut. Nothing typed into any Agent changes the rules.
2. **Every Agent keeps enforcing offline.** It caches the last good rules. Losing the
   network never lifts a block.
3. **The password is the only key.** Signing new rules needs the password (§6.2), and
   the password is only accepted by the Console on the PC.

### 3.2 Fortress on any device: the Agent contract

An Agent is whatever program enforces Fortress on one kind of device. Every Agent,
on any platform, must do the same six things:

| # | An Agent must… |
|---|---|
| A1 | Enrol once with Fortress Core and pin Core's public key |
| A2 | Accept only signed rule bundles with a higher version than it holds |
| A3 | Block websites and apps, and run schedules, from those rules |
| A4 | Keep enforcing the cached rules offline |
| A5 | Check in and upload its activity log when it can reach Core |
| A6 | Stand down only on a signed "release" from Core |

Adding a new kind of device means writing one new Agent against this contract.
Core, the Console and the rules format do not change.

| Platform | Agent | Status |
|---|---|---|
| Android (Pixel 8a, Idea Tab) | Kotlin app | Planned, v1 |
| Windows (the PC layer) | Python service | Planned, v1 |
| Another Windows PC | Same Windows Agent | Works once v1 exists |
| macOS, Linux | Would need their own Agents | Not planned |
| iPhone / iPad | Apple only allows this through its Screen Time APIs, which limit what an outside app can do | Not planned; feasibility **unverified** |

---

## 4. Components and stack

Matches the stack already in use on ExVelo (Python, Flutter, Kotlin, Android).

| Component | Runs on | Language | Notes |
|---|---|---|---|
| **Fortress Core** | PC, as a Windows service | Python | Rules, password check, signing, sync, log |
| **Fortress Console** | PC | Flutter (Windows desktop) | The main UI. Talks to Core on localhost only |
| **Windows Agent** | PC | Python, as a Windows service | The PC-layer lock. Separate from Core so that it follows the same contract as any other Agent |
| **Android Agent** | Pixel 8a, Idea Tab | Kotlin | Blocking needs native Android APIs |

Main libraries: `cryptography` (Ed25519 signatures), `argon2-cffi` (password hashing),
`fastapi` (Console API on localhost, Agent API on the home network, port 47801), SQLite.
Android: Android's management APIs (app suspension), the Keystore (device key),
AlarmManager (schedule boundaries and 15-minute check-ins), and later `VpnService`
(website filter). In v1 the Agent is given Core's address at enrolment; finding it
automatically on the Wi-Fi (`zeroconf`) is left for later.

---

## 5. The main UI (Fortress Console)

| Screen | Contents |
|---|---|
| **Dashboard** | Lock state (large, top); every device, **the PC included**, with last check-in; blocks active now |
| **Block lists** | Named lists: websites (domains, `*.example.com`) and apps (Android package names, Windows programs) |
| **Schedules** | Weekly grid. Each entry = *list × device(s) × time window*. Plus "Block now for N hours" |
| **Allowed** | Always-allowed apps, sites and developer tools, per platform (§10) |
| **Devices** | Add a device (setup walkthrough), remove a device (§7.4) |
| **Activity** | Rule pushes, check-ins, blocked-attempt counts, devices gone quiet |
| **Settings** | Change password, recovery code, auto-lock time, partner mode |

When **locked**, every screen is read-only and the only working button is **Unlock**.
A block list can target "all devices", so the same list blocks a site on the PC,
the phone and the tablet at once.

---

## 6. Lock, unlock and the password

### 6.1 One lock for the whole system

There is **one** lock. It covers the PC layer, the Pixel and the tablet together.

| State | Blocks | Console | Leaving it |
|---|---|---|---|
| **Locked** | Enforced as scheduled on every device | Read-only | Password, in the Console on the PC |
| **Unlocked** | Still enforced as scheduled | Editable | **Lock** button, or auto-relock after 15 min idle (**assumed**) |

Unlocking does **not** turn blocking off; it allows editing. Ending a block early, on
any device, means unlocking on the PC and then editing the schedule. **Every change to
Fortress, on any device, goes through that one unlock.**

### 6.2 How the password protects changes

- Stored only as an **Argon2id** hash.
- Rules are **signed** with a key that is itself encrypted by the password. No
  password → no signature → no Agent accepts the change, the PC's own Agent included.
  This is what makes R2 hold.
- Each rules bundle carries a version number; Agents reject older versions, so old
  laxer rules cannot be replayed.
- The password is entered **only in the Console on the PC**. No Agent has an unlock box.
- Wrong attempts: growing delay (1 s, 2 s, 4 s … up to 15 min), each logged.
- **Recovery code**: shown once at setup, to be printed and kept somewhere safe. It
  resets the password.

### 6.3 Self-control options

| Option | Effect |
|---|---|
| **Partner holds password** (recommended) | A trusted person sets the password. Strongest option for self-control, and matters most for the PC layer (§7.2) |
| **Unlock delay** | After the right password, wait N minutes before unlocking (cancelable). Stops impulse unlocks |
| **Locked until** | Ignores the password until a chosen date and time. The recovery code still works |

---

## 7. Staying enrolled (R3)

### 7.1 Android

The Android Agent is set up using **Android's official device-management mode** (the
same mode companies use for work phones), during a one-time setup from the PC over
USB. In that mode Android itself prevents the app from being removed or switched off
from the device, and lets it enforce the blocks in §8.

This mode can only be turned on **right after a factory reset, before a Google account
is added**. Both devices need backing up and resetting once. Detailed steps belong in
the Android Agent spec.

### 7.2 The PC layer

The PC is the control point *and* a locked device, so its protection rests on Windows
accounts:

- **Daily use happens in a standard (non-administrator) Windows account.** The Fortress
  services run at system level, which a standard account cannot stop or change.
- **The Windows administrator password is kept with the Fortress password**, by the
  same person (ideally the partner, §6.3). Admin access to Windows and the Fortress
  password are two keys to the same door, so both have to be held together.
- Changes still go through the Console unlock. The Windows admin account is for
  installing software and system maintenance, not for editing Fortress.

Detailed hardening belongs in the Windows Agent spec.

### 7.3 Limits, stated honestly

- A **hardware factory reset** on the phone or tablet, or **reinstalling Windows** on
  the PC, always removes Fortress. No software can prevent that. It wipes the
  device, and the Console (or its absence) makes it obvious.
- Whoever holds the Windows administrator password can, in the end, remove Fortress
  from the PC. That is why §7.2 puts it with the Fortress password.
- Fortress is a commitment device for its owner, not a prison. Its real strength is
  the password being held by someone else, and dropping out being visible.

### 7.4 Check-ins and removal

- Each device checks in with Core when it is reachable. The Console marks a device
  **amber** after 24 h without a check-in and **red** after 72 h (**assumed**). The
  PC's own Agent checks in too; if it stops, Core flags it.
- The only normal way to remove a device is **Devices → Remove** in an unlocked
  Console. That sends a signed release, and the Agent stands down.

---

## 8. Blocking

Same rules, same lists, every device. How each Agent enforces them:

### 8.1 Websites

| | Android | PC layer (Windows) |
|---|---|---|
| Filter | A **local filter** on the device (Android `VpnService`) refuses lookups for blocked domains. It is not a remote VPN | A **local filter** on the PC refuses lookups for blocked domains |
| Browsers | Browser settings that would skip the filter are managed | Chrome, Edge and Firefox are managed through their official policy settings so they use the filter and cannot skip it |
| Matching | Exact domains and wildcards (`*.tiktok.com`) | Same |

**Allowed** domains always pass (§10).

### 8.2 Apps

| | Android | PC layer (Windows) |
|---|---|---|
| Method | Blocked apps are **suspended** through Android's management API. They stay installed but will not open | Blocked programs are **stopped from launching**; Fortress shows a "blocked by Fortress" notice |
| Identified by | Package name (e.g. `com.zhiliaoapp.musically`) | Program file and publisher (e.g. `steam.exe`, Valve) |
| Picker | Built from the apps each device reports | Built from installed programs |

New installs while locked: a decision (§12).

### 8.3 Schedules

- Each schedule = block list × devices × days × time window × time zone.
- Every Agent evaluates schedules **locally** with automatic network time, so blocks
  start and stop on time even offline.
- "Block now for N hours" makes a one-off schedule.
- When schedules overlap, a block always wins over an allow, except the always-allowed
  list (§10).

---

## 9. The Console and the PC layer together

The Console runs on the PC that is itself locked, so it needs a few rules of its own:

- **The Console and Fortress's own components are never blockable.** The Console
  is always reachable, so unlocking is always possible.
- **The PC-layer lock never blocks the tools needed to unlock or recover**: the
  Console, Windows settings for networking, and the Windows administrator account.
- A schedule targeting the PC applies to the standard daily account. The Windows
  admin account (§7.2) is not used for daily work.

---

## 10. What stays allowed (R10)

Never blocked by any schedule, so ExVelo and Block Trainer work keeps going.

| Platform | Always allowed |
|---|---|
| **Android** | Developer options and **USB debugging / ADB**; ExVelo (`com.shotput.app`), Block Trainer, phone, messages, maps, camera, settings; Bluetooth |
| **PC layer** | Arduino IDE and `arduino-cli`, **serial/COM ports** (COM7), Python, Flutter, Android Studio, `adb`, VS Code, Git, terminals |
| **Domains (all devices)** | `github.com`, `pub.dev`, `pypi.org`, `developer.android.com`, `silabs.com`, `seeedstudio.com` (**starter list**, editable) |

Trade-off: an open debugging connection or a terminal is also a way to fiddle with
a device. Fortress **logs** debugging sessions to Activity rather than blocking them,
since R10 requires debugging to work. A setting to allow debugging only while
unlocked is an option (§12).

---

## 11. Build plan

| Phase | What | Done when |
|---|---|---|
| 1 | Core: rules database, password, signing, CLI | Signed bundle produced and verified in tests |
| 2 | Console: Dashboard, Block lists, Schedules, Lock/Unlock | Rules edited and locked from the UI |
| 3 | Android Agent: receive + verify rules, app blocking | Blocked app won't open on the tablet |
| 4 | Android Agent: website filter, schedules, offline | Site blocked on schedule with Wi-Fi off |
| 5 | Android device-management setup + check-ins | Agent cannot be removed on the tablet; Console shows check-ins |
| 6 | Pixel enrolment, self-control options | Pixel and tablet enforced from one Console |
| 7 | **Windows Agent (PC layer)**: verify rules, website + program blocking, schedules | A site and a program are blocked on the PC on schedule; only a Console unlock changes it |
| 8 | Windows standard-account switch-over | Daily use on a standard account; the PC layer cannot be stopped from it |

**The other devices' Agents come first, the PC lock last** (decided 2026-10-16). The
PC is the development machine for Fortress itself (and for ExVelo), so it stays
unrestricted until everything else is proven. Locking the PC is then the final step,
done once the Console and the password flow are trusted.

Android is tested on the **tablet first**, so the Pixel (daily phone) is not reset
until the system is proven.

---

## 12. Open decisions

| Question | Options | Suggested |
|---|---|---|
| Who holds the Fortress password and the Windows admin password? | Isaiah / a partner | Partner, both together |
| Away from home Wi-Fi: how do the phone and tablet get new rules? | Home Wi-Fi only / a relay server later | Home Wi-Fi only for v1 |
| App installs while locked | Allowed / blocked | Allowed, but new apps logged |
| USB debugging and terminals | Always / only while unlocked | Always (ExVelo work), logged |
| Separate block lists for the PC, or shared lists? | Shared / per device | Shared lists, per-device schedules |
| Auto-relock time, amber/red thresholds | 15 min, 24 h, 72 h | Confirm |
| Lenovo Idea Tab exact model and Android version | — | **Android 16** (2026-10-18). Exact model still to note |
| How Agents prove who they are | — | **Decided 2026-10-18:** one-time enrolment code proved by HMAC on both sides, then every request signed by the device's own P-256 key (`docs/agent_protocol.md`) |
| Activate Windows before Phase 7? | Yes / no | Answer before Phase 7 (§13) |

---

## 13. The PC: Windows Home, not activated

Recorded 2026-10-16. This only affects Phases 7 and 8 (the PC layer).

| Fact | Effect on the PC layer |
|---|---|
| **Windows Home** has no Group Policy editor and no AppLocker (those are Pro-only) | The Windows Agent cannot hand program blocking to Windows. It detects and stops blocked programs itself. Settings that Pro would set through Group Policy are written directly where the program reads them |
| Browser policies (Chrome, Edge, Firefox) | These are read from the registry or policy files, so they are not tied to Group Policy. Whether every policy Fortress needs is honoured on an unmanaged Home PC is **unverified**. Check each one in Phase 7 |
| Standard (non-admin) accounts | Available on Home. §7.2 is unchanged |
| **Not activated** | Mainly locks personalization settings and shows a watermark. Effect on accounts, services and browser policies is **unverified**. Check before Phase 7. Activating avoids the question |

None of this blocks Phases 1 to 6.
