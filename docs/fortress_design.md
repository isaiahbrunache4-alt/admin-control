# Fortress — Software Design (Spec 01, draft)

**Status: draft, for review. Nothing is implemented.** Written 2026-10-16.
Items that are assumptions rather than stated requirements are marked **assumed**.
Decisions still needed before code is written are listed in §11.

---

## 1. Purpose

Fortress is a **self-control** system for Isaiah's own devices. It blocks distracting
websites and apps, runs blocks on a schedule, and puts all control behind one computer
and one password.

| Role | Device |
|---|---|
| **Command terminal** (the only place settings change) | Windows PC |
| Enforced device | **Google Pixel 8a** (Android) |
| Enforced device | **Lenovo Idea Tab** (Android) |

### Requirements

| # | Requirement | Section |
|---|---|---|
| R1 | The PC is the primary terminal | §3, §5 |
| R2 | The PC is the only way to change Fortress | §6 |
| R3 | The phone and tablet cannot drop out of Fortress | §7 |
| R4 | Website blocking | §8.1 |
| R5 | App blocking | §8.2 |
| R6 | Scheduled blocks | §8.3 |
| R7 | One main UI for the whole system | §5 |
| R8 | Lock / unlock, unlock only by password | §6 |
| R9 | Modelled on existing accountability software | §2 |
| R10 | Debugging still works on the phone and tablet | §9 |

---

## 2. What it is modelled on

| Product | Idea borrowed |
|---|---|
| **Freedom** | Named block lists, recurring schedules, one set of rules synced to every device |
| **Cold Turkey** | A lock that the UI itself cannot undo; locks survive reboot |
| **Covenant Eyes** | Accountability: when a device stops reporting, the console shows it. The password can be held by a partner |
| **Google Family Link / Qustodio** | One console, several devices; per-app blocking; daily time windows |

Lesson taken from all of them: **software alone is a weak barrier against its own
owner.** What makes self-control software work is (a) using Android's supported
management features rather than tricks, and (b) **accountability**: someone else holds
the password, and dropping out is visible.

---

## 3. System overview

```
┌─────────────────────────────────────────────┐
│ COMMAND TERMINAL (Windows PC)               │
│  Fortress Console (Flutter desktop) — UI    │
│        │ localhost only                     │
│  Fortress Core (Python service)             │
│   ├─ rules database (SQLite)                │
│   ├─ password check + rule signing          │
│   ├─ sync server (home Wi-Fi)               │
│   └─ activity log                           │
└──────────────┬──────────────────────────────┘
               │ signed rules ↓     check-ins ↑
       ┌───────┴─────────┐
       ▼                 ▼
┌──────────────┐  ┌──────────────┐
│ Pixel 8a     │  │ Lenovo       │
│ Fortress     │  │ Idea Tab     │
│ Agent        │  │ Fortress     │
│ (Kotlin app) │  │ Agent        │
└──────────────┘  └──────────────┘
```

Two rules hold everywhere:

1. **The Agent accepts only rules signed by the Command PC.** Nothing typed on the
   phone or tablet changes the rules.
2. **The Agent keeps enforcing offline.** It caches the last good rules. Leaving home
   Wi-Fi never lifts a block; it only delays new rules until the device reconnects.

---

## 4. Components and stack

Matches the stack already in use on ExVelo (Python, Flutter, Kotlin, Android).

| Component | Runs on | Language | Notes |
|---|---|---|---|
| **Fortress Core** | PC, as a background service | Python | Rules, password check, signing, sync, log |
| **Fortress Console** | PC | Flutter (Windows desktop) | The main UI. Talks to Core on localhost only |
| **Fortress Agent** | Pixel 8a, Idea Tab | Kotlin | Blocking needs native Android APIs |

Main libraries: `cryptography` (Ed25519 signatures), `argon2-cffi` (password hashing),
`fastapi` (sync API), `zeroconf` (find devices on home Wi-Fi), SQLite. Android:
`VpnService` (website filter), `UsageStatsManager` + accessibility-free app blocking
via Android's management APIs, WorkManager (scheduled sync).

---

## 5. The main UI (Fortress Console)

| Screen | Contents |
|---|---|
| **Dashboard** | Lock state (large, top); Pixel and tablet with last check-in; blocks active now |
| **Block lists** | Named lists: websites (domains, `*.example.com`) and apps (Android package names) |
| **Schedules** | Weekly grid. Each entry = *list × device(s) × time window*. Plus "Block now for N hours" |
| **Allowed** | Always-allowed apps, sites and developer tools (§9) |
| **Devices** | Add a device (setup walkthrough), remove a device (§7.3) |
| **Activity** | Rule pushes, check-ins, blocked-attempt counts, devices gone quiet |
| **Settings** | Change password, recovery code, auto-lock time, partner mode |

When **locked**, every screen is read-only and the only working button is **Unlock**.

---

## 6. Lock, unlock and the password

### 6.1 States

| State | Blocks | Console | Leaving it |
|---|---|---|---|
| **Locked** | Enforced as scheduled | Read-only | Password, at the PC |
| **Unlocked** | Still enforced as scheduled | Editable | **Lock** button, or auto-relock after 15 min idle (**assumed**) |

Unlocking does **not** turn blocking off; it allows editing. Ending a block early means
unlocking, then editing the schedule, so the password gates every change.

### 6.2 How the password protects changes

- Stored only as an **Argon2id** hash.
- Rules are **signed** with a key that is itself encrypted by the password. No
  password → no signature → the phone and tablet ignore the change. This is what
  makes "the PC is the only way to change Fortress" (R2) hold.
- Each rules bundle carries a version number; the Agent rejects older versions, so old
  laxer rules cannot be replayed.
- The password is entered **only on the PC**. The phone and tablet have no unlock box.
- Wrong attempts: growing delay (1 s, 2 s, 4 s … up to 15 min), each logged.
- **Recovery code**: shown once at setup, to be printed and kept somewhere safe. It
  resets the password.

### 6.3 Self-control options

| Option | Effect |
|---|---|
| **Partner holds password** (recommended) | A trusted person sets the password. Strongest option for self-control |
| **Unlock delay** | After the right password, wait N minutes before unlocking (cancelable). Stops impulse unlocks |
| **Locked until** | Ignores the password until a chosen date and time. The recovery code still works |

---

## 7. Staying enrolled (R3)

### 7.1 Approach

The Agent is set up using **Android's official device-management mode** (the same
mode companies use for work phones), during a one-time setup from the PC over USB. In
that mode Android itself prevents the app from being removed or switched off from
the device, and lets it enforce the blocks below.

Detailed setup steps belong in the Agent spec (Spec 02), not here. One fact matters
now: **this mode can only be turned on right after a factory reset, before a Google
account is added.** Both devices will need to be backed up and reset once.

### 7.2 Limits, stated honestly

- A **hardware factory reset** (button combination at boot) always removes Fortress.
  No app can stop that. It erases the device, and the Console shows the device as
  having gone quiet.
- Fortress is a commitment device for its owner, not a prison. Its real strength
  is the password being held by someone else, and dropping out being visible.

### 7.3 Check-ins and removal

- Each device checks in with the PC when it is on home Wi-Fi. The Console marks a
  device **amber** after 24 h without a check-in and **red** after 72 h (**assumed**).
- The only normal way to remove a device is **Devices → Remove** in an unlocked
  Console. That sends a signed release, and the Agent stands down.

---

## 8. Blocking

### 8.1 Websites

- The Agent runs a **local filter** (Android `VpnService`) that refuses lookups for
  blocked domains. Nothing leaves the device; it is not a remote VPN.
- Matches exact domains and wildcards (`*.tiktok.com`).
- Browser settings that would skip the filter are managed so the filter stays in force.
- **Allowed** domains always pass (§9).

### 8.2 Apps

- Blocked apps are **suspended** through Android's management API. They stay
  installed but will not open, and show "blocked by Fortress".
- Lists use package names (e.g. `com.zhiliaoapp.musically`). The Console offers a picker
  built from the apps each device reports.
- New installs: optionally off while locked (**decision**, §11).

### 8.3 Schedules

- Each schedule = block list × devices × days × time window × time zone.
- The Agent evaluates schedules **locally** with automatic network time, so blocks
  start and stop on time even offline.
- "Block now for N hours" makes a one-off schedule.
- When schedules overlap, a block always wins over an allow, except the always-allowed
  list (§9).

---

## 9. What stays allowed (R10)

These are never blocked by any schedule, so ExVelo work keeps going:

| Category | Items |
|---|---|
| Developer options and **USB debugging / ADB** | Installing debug builds from Flutter/Android Studio, logcat |
| Apps | `com.shotput.app` (ExVelo), Block Trainer, phone, messages, maps, camera, settings |
| Bluetooth | Needed for the ExVelo device |
| Domains | `github.com`, `pub.dev`, `pypi.org`, `developer.android.com`, `silabs.com`, `seeedstudio.com` (**starter list**, editable) |

Trade-off: an open ADB connection is also a way to fiddle with a device. Fortress
**logs** every debugging session to Activity rather than blocking debugging, since R10
requires debugging to work. A setting to allow debugging only while unlocked is an
option (§11).

---

## 10. Build plan

| Phase | What | Done when |
|---|---|---|
| 1 | Core: rules database, password, signing, CLI | Signed bundle produced and verified in tests |
| 2 | Console: Dashboard, Block lists, Schedules, Lock/Unlock | Rules edited and locked from the UI |
| 3 | Agent: receive + verify rules, app blocking | Blocked app won't open on the Pixel |
| 4 | Agent: website filter, schedules, offline | Site blocked on schedule with Wi-Fi off |
| 5 | Device-management setup + check-ins | Agent cannot be removed on the device; Console shows check-ins |
| 6 | Tablet enrolment, self-control options, polish | Both devices enforced from one Console |

Phases 1–4 are tested on the **tablet first**, so the Pixel (daily phone) is not reset
until the system is proven.

---

## 11. Open decisions

| Question | Options | Suggested |
|---|---|---|
| Who holds the password? | Isaiah / a partner | Partner |
| Away from home Wi-Fi: how do devices get new rules? | Home Wi-Fi only / a relay server later | Home Wi-Fi only for v1 |
| App installs while locked | Allowed / blocked | Allowed, but new apps get logged |
| USB debugging | Always / only while unlocked | Always (ExVelo work), logged |
| Is the Command PC itself also blocked? | No / yes, Windows Agent later | No for v1 |
| Auto-relock time, amber/red thresholds | 15 min, 24 h, 72 h | Confirm |
| Lenovo Idea Tab exact model and Android version | — | Needed before Phase 3 |
