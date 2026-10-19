# Fortress Agent for Windows — the PC-layer lock

The PC is both the control point and a locked device (Spec 01 §7.2). This is the part
that locks the PC itself: it follows the same Agent contract as the phones and tablet,
blocks the same websites and, in addition, blocks programs. It is a **separate program
from Core** with no signing key, so nothing typed on the PC changes the rules without the
Console and the password.

**What it does**

| | |
|---|---|
| Website blocking | A local DNS filter on `127.0.0.1` answers blocked sites with "no such domain" and forwards the rest unchanged. The adapters are pointed at it, and browsers' own secure DNS is turned off so they cannot skip it |
| Program blocking | Blocked programs are stopped from running (a "blocked by Fortress" effect); re-checked every couple of seconds, so a relaunch is caught |
| Offline, schedules | Blocks start and end on time from the cached signed rules, with no network |
| Check-ins | Every 15 minutes: fetches new rules, reports what it did and counts of blocked lookups |
| Release | Console → Devices → Remove lifts every block, restores DNS and clears browser policy |

Windows Home has no Group Policy editor or AppLocker, so Fortress does the program
blocking itself and writes browser policy straight to the registry, where the browsers
read it (Spec 01 §13).

## Install (one venv with Core)

The agent reuses `fortress_core`, so install both into the same environment. In the repo,
in a normal PowerShell:

```powershell
cd windows
& "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe" -m venv .venv
.\.venv\Scripts\pip install -e ..\core -e ".[test]"
.\.venv\Scripts\pytest
```

## Enrol the PC

Core must be running (`fortress serve`). Since Core and the agent are on the same PC, the
address is `127.0.0.1`.

1. In the Console (unlocked): **Devices → Add device** (`pc`, Windows), then **Enrol** for
   a code. Or: `fortress device add pc windows "This PC"` then `fortress device enrol pc`.
2. Enrol the agent:

   ```powershell
   .\.venv\Scripts\fortress-agent enrol 127.0.0.1 pc ABCDE-FGHJK
   .\.venv\Scripts\fortress-agent status
   ```

## Run it (as administrator)

Pointing the adapters at the filter and stopping programs need administrator rights.

```powershell
.\.venv\Scripts\fortress-agent run
```

Leave it running. Blocks are enforced only while it runs; stopping it (Ctrl+C) lifts
them, which is what you want during Phase 7 testing. Making it start itself and resist
being stopped is the switch-over below.

## Checks

With a block scheduled for `pc` and the agent running:

- **Websites:** a blocked site fails to load in Chrome/Edge; others load. Check the policy
  took at `edge://policy` / `chrome://policy` (look for `DnsOverHttpsMode = off`).
- **Programs:** a blocked program (e.g. `steam.exe`) closes within a couple of seconds of
  opening and will not stay open.
- **Offline:** disconnect the network — blocks stay. When a block's window ends, it lifts
  on its own.
- **Activity** on the Console shows `pc: programs_blocked …` and `pc: sites_blocked …`.
- **Remove** the PC in the Console: the filter stops, DNS goes back to automatic, programs
  run again.

## Phase 8: run always, from a standard account

Until now the agent runs by hand from the administrator account. The lock only holds once
it runs on its own and daily use moves to a standard account that cannot stop it.

1. **Run the agent as a service (SYSTEM), auto-starting.** Create it with the built-in
   `sc.exe`, in an administrator PowerShell (one line):

   ```powershell
   sc.exe create FortressAgent binPath= "\"C:\path\to\windows\.venv\Scripts\fortress-agent.exe\" run" start= auto obj= LocalSystem DisplayName= "Fortress PC Lock"
   sc.exe description FortressAgent "Fortress PC-layer lock"
   sc.exe start FortressAgent
   ```

   A SYSTEM service keeps running across logins and cannot be stopped from a standard
   account. (`fortress-agent.exe run` loops in the foreground, which is what a service
   expects; a crash is restarted by `sc.exe failure` settings if you add them.)

2. **Make a standard (non-administrator) Windows account for daily use**, and use it from
   now on. Settings → Accounts → Other users → Add account → change its type to Standard.

3. **Keep the Windows administrator password with the Fortress password** (ideally the
   partner, Spec 01 §6.3, §7.2). Admin access to Windows and the Fortress password are two
   keys to the same door; holding both together is what makes the PC lock hold.

Stated honestly (Spec 01 §7.3): whoever has the Windows administrator password can, in the
end, stop the service and remove Fortress, and reinstalling Windows always removes it.
The strength is the password being held by someone else and dropping out being visible in
the Console.

## Windows: not activated, and policies to verify (Spec 01 §13)

- **Not activated** mainly locks personalization and shows a watermark. Confirm a standard
  account, the service, and the browser policies all still work; activating avoids the
  question.
- In Phase 7, check each browser policy actually takes on this PC (`…/policy` pages).
  Firefox needs the policy keys under `HKLM\SOFTWARE\Policies\Mozilla\Firefox`, which the
  agent writes; if a portable browser ignores policy, block it as a program instead.
