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

1. **Run the agent as SYSTEM at every start-up, restarted if it stops.** Use Task
   Scheduler, not `sc.exe create`: `fortress-agent run` is an ordinary program, and a
   Windows *service* has to answer the Service Control Manager, so `sc.exe` would start it
   and then kill it after about 30 seconds (error 1053). In an administrator PowerShell,
   with the path to *your* venv:

   ```powershell
   $exe = "C:\path\to\windows\.venv\Scripts\fortress-agent.exe"
   $action   = New-ScheduledTaskAction -Execute $exe -Argument "run"
   $atBoot   = New-ScheduledTaskTrigger -AtStartup
   $every5   = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 5)
   $settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) `
       -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -MultipleInstances IgnoreNew `
       -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
   Register-ScheduledTask -TaskName "Fortress PC Lock" -Action $action -Trigger $atBoot,$every5 `
       -Settings $settings -User "SYSTEM" -RunLevel Highest
   Start-ScheduledTask -TaskName "Fortress PC Lock"
   ```

   `ExecutionTimeLimit 0` stops Windows ending it after its default 3 days; the 5-minute
   trigger starts it again if it ever exits (a second copy is never started while one
   runs). A task that runs as SYSTEM cannot be ended from a standard account. Check with
   `Get-ScheduledTask "Fortress PC Lock" | Get-ScheduledTaskInfo` (LastTaskResult `267009`
   means "running").

   The venv must live where the daily account **cannot write** (for example in the
   administrator's home folder, or under `C:\Program Files`). Otherwise editing a `.py`
   file in it would switch the lock off.

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
