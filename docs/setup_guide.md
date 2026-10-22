# Fortress setup guide: from nothing to fully locked

This guide takes you from an empty PC to Fortress running on the PC, the Pixel 8a and
the Lenovo Idea Tab. You do not need to know how Fortress works inside. Do the parts in
order, and don't skip the **Check** at the end of each one: it tells you that part works
before you build on it.

Budget **one afternoon** for Parts 1–6 and **another session** for Parts 7–9. Part 8
factory-resets the phone and tablet, so back them up first (Part 0).

> **Not tried on the real PC yet.** Part 9 (making the PC lock permanent) has been
> written carefully but not yet run on a real Windows PC. Go slowly there. If something
> behaves differently from what this guide says, stop and note it down.

---

## What Fortress is, in one minute

- **Fortress blocks websites and apps on a schedule**, for example "no TikTok or YouTube
  on school days from 8:00 to 15:00", on the PC, the phone and the tablet at once.
- **The PC is the only place where rules can be changed.** It runs two programs:
  - **Fortress Core**, which works in the background and holds the rules.
  - **Fortress Console**, the window you use to edit the rules.
- **Every device runs an "Agent"**, a small program that enforces the rules even when
  it is offline. The PC has one too, so the PC is blocked like the others.
- **One password unlocks changes.** Without it, nothing can be loosened on any device.
  Unlocking only lets you *edit*: blocks keep running until you change the rules.
- **A recovery code** is printed once, at setup. It resets the password if it's forgotten.

### The most important decision: who holds the password

Fortress is strongest when **someone you trust (the "partner") sets the password and
keeps it**, together with the **recovery code** and the **Windows administrator
password**. If you hold all three yourself, Fortress is a speed bump, not a wall.
Decide this before Part 3, because the partner needs to be there to type the password.

---

## Words used in this guide

| Word | Meaning |
|---|---|
| **Core** | The background program on the PC that holds the rules and signs them |
| **Console** | The window on the PC where you edit rules |
| **Agent** | The program on each device that does the blocking |
| **Block list** | A named set of sites and apps, e.g. `social` = tiktok.com, instagram.com |
| **Schedule** | When a block list is enforced, and on which devices |
| **Enrol** | Connect a device to Fortress using a one-time code |
| **PowerShell** | Windows' command window. Start menu → type "PowerShell". "As administrator" means right-click → *Run as administrator* |
| **venv** | A private folder of Python packages for one project. You create it once |

When this guide shows a box of commands, type (or paste) them **one line at a time**
into PowerShell and press Enter after each.

---

## Part 0: Before you start (15 min)

You need:

- The **Windows PC**, with the Windows **administrator** account you use now.
- The **Pixel 8a** and the **Lenovo Idea Tab**, plus a **USB cable** for each.
- The **partner**, for Part 3 (or at least a password you will hand over later).
- A **printer or pen and paper**, for the recovery code.
- All devices on the **same home Wi-Fi**.

Do now:

1. **Back up the phone and tablet** (photos, chats, 2FA apps). Part 8 needs them to have
   no Google account on them, which in practice usually means a factory reset.
2. In Windows: **Settings → Network & Internet → Wi-Fi → (your network) → Network
   profile type → Private.** Fortress only accepts devices on a private network.
3. Write down the PC's name and Windows admin password somewhere safe. You will hand
   the admin password to the partner at the end.

---

## Part 1: Install the tools on the PC (30–45 min)

Open **PowerShell** (not as administrator) and install the tools with `winget`, which
comes with Windows:

```powershell
winget install -e --id Git.Git
winget install -e --id Python.Python.3.13
```

- Use this Python from python.org (the command above). **Don't use the Microsoft Store
  Python**: it can't run in the background later.
- **Close PowerShell and open a new one** after installing, so it finds the new tools.

For the Console (the editing window) you also need **Flutter**, which builds Windows
apps:

1. Install **Visual Studio 2022 Community** with the workload **"Desktop development
   with C++"** (from visualstudio.microsoft.com). Flutter needs it to build Windows apps.
2. Install Flutter: follow flutter.dev → *Get started* → *Windows* → *Desktop*. At the
   end, `flutter doctor` should show a green tick for "Windows Version" and "Visual Studio".

For the phone and tablet you need **Android Studio** (developer.android.com/studio).
Install it with the defaults and open it once so it downloads the Android SDK. That
also gives you `adb`, the tool that talks to the phone over USB.

**Check:** in a new PowerShell, each of these prints a version and no error:

```powershell
git --version
& "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe" --version
flutter --version
```

---

## Part 2: Get the Fortress code (5 min)

Put it in your **administrator account's own home folder**, not on a shared drive or
in a folder the daily account will be able to change later (Part 9 explains why).

```powershell
cd ~
git clone https://github.com/isaiahbrunache4-alt/admin-control.git fortress
cd fortress
```

**Check:** `dir` shows the folders `core`, `console`, `android`, `windows` and `docs`.

---

## Part 3: Install and set up Fortress Core (15 min, partner present)

```powershell
cd ~\fortress\core
& "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe" -m venv .venv
.\.venv\Scripts\pip install -e ".[test]"
.\.venv\Scripts\pytest
```

The last line runs Fortress's self-tests. It must end with **"passed"** and no
"failed". If anything fails, stop here: something is wrong with the install.

Now the **first-time setup**. **The partner should type the password.**

```powershell
.\.venv\Scripts\fortress init
```

- The password must be at least 8 characters. **Use a passphrase of 4 or more random
  words**: the database is protected by the password alone, so a short password can be
  guessed by a computer given enough time.
- Fortress then shows a **recovery code** like `ABCD-EFGH-JKMN-PQRS-TUVW-XYZ2`.
  **It's shown only once.** Print it or write it down, check it twice, and give it
  to the partner. Anyone holding this code can reset the password, even while
  "Locked until" is on.

**Check:** `.\.venv\Scripts\fortress status` shows `locked` and `version 1`.

---

## Part 4: Start Core and open the Console (20 min)

### 4a. Start Core

In a PowerShell window you leave open:

```powershell
cd ~\fortress\core
.\.venv\Scripts\fortress serve
```

It prints nothing much and keeps running. **Leave this window open** for now (Part 9
makes it start by itself).

### 4b. Let the phone and tablet reach Core

Once, in a PowerShell **as administrator**:

```powershell
New-NetFirewallRule -DisplayName "Fortress Agents" -Direction Inbound -Protocol TCP -LocalPort 47801 -Profile Private -Action Allow
```

### 4c. Build and open the Console

In a second PowerShell:

```powershell
cd ~\fortress\console
flutter build windows
```

The finished app is `console\build\windows\x64\runner\Release\fortress_console.exe`.
Double-click it (pin it to the taskbar while you're there).

**Check:** the Console opens and shows **Locked** at the top. Click **Unlock**, type the
password, and the screens become editable. Click **Lock**.

---

## Part 5: Your first block list and schedule (10 min)

In the Console, **unlocked**:

1. **Block lists → New list**, name it `social`.
2. Add websites: `tiktok.com`, `instagram.com`, `youtube.com`.
   - Type a **domain**, not a web address: `tiktok.com`, not `https://www.tiktok.com/...`.
   - Blocking `tiktok.com` also blocks `www.tiktok.com` and every other `….tiktok.com`.
3. **Allowed** shows sites that are *never* blocked (GitHub, Python docs…). Leave it as is.
4. **Schedules → Weekly schedule**: list `social`, devices **all**, Monday–Friday, 08:00 to 15:00, your
   time zone (e.g. `America/New_York`).
   - A window like 22:00 to 06:00 runs overnight and belongs to the day it starts on.
5. Click **Lock**. Locking **publishes** the new rules to every device.

Nothing is blocked on any device yet: no device is enrolled. That's next.

The same thing from PowerShell, if you prefer (each command asks for the password):

```powershell
.\.venv\Scripts\fortress list add social
.\.venv\Scripts\fortress item add social site tiktok.com instagram.com youtube.com
.\.venv\Scripts\fortress schedule add social --devices all --days mon,tue,wed,thu,fri --from 08:00 --to 15:00 --tz America/New_York
```

**Check:** **Activity** shows `publish version 2` (or higher).

---

## Part 6: Lock the PC itself, test mode (30 min)

This puts the Windows Agent on the PC **by hand**, so you can test it and stop it with
Ctrl+C. Part 9 makes it permanent.

```powershell
cd ~\fortress\windows
& "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe" -m venv .venv
.\.venv\Scripts\pip install -e ..\core -e ".[test]"
.\.venv\Scripts\pytest
```

Then:

1. Console (unlocked) → **Devices → Add device**: id `pc`, platform **Windows**, name
   "This PC". Then click **Enrol** next to it. It shows a code like `ABCDE-FGHJK`, valid
   for 30 minutes.
2. Enrol the PC (`127.0.0.1` means "this same PC"):

   ```powershell
   .\.venv\Scripts\fortress-agent enrol 127.0.0.1 pc ABCDE-FGHJK
   ```

3. In a PowerShell **as administrator**, start it:

   ```powershell
   cd ~\fortress\windows
   .\.venv\Scripts\fortress-agent run
   ```

**Check:**

- Console → unlock → **Schedules → Block now…**: list `social`, 1 hour, device `pc` → **Lock**.
- In PowerShell (not admin): `.\.venv\Scripts\fortress-agent status` shows the block.
  If the rules version is old, wait a minute or restart `fortress-agent run`.
- In Chrome or Edge, `tiktok.com` doesn't load and `github.com` does. (A tab you
  already had open may keep working for a few minutes. Close it and open a new one.)
- `chrome://policy` or `edge://policy` lists `DnsOverHttpsMode = off`.
- To also block a program, add it to a list as an app, e.g. `steam.exe`. It closes
  within 2 seconds of opening.
- **Ctrl+C** in the admin window stops the Agent and lifts the PC's blocks.

> If the PC **has no internet at all** after stopping the Agent, Windows is still
> sending lookups to the stopped filter. Fix it in a PowerShell as administrator:
> `Get-NetAdapter | ForEach-Object { Set-DnsClientServerAddress -InterfaceIndex $_.ifIndex -ResetServerAddresses }`

---

## Part 7: Build the Android app (20 min)

```powershell
cd ~\fortress\android
.\gradlew :agent-core:test
.\gradlew :app:assembleDebug
```

The app is `android\app\build\outputs\apk\debug\app-debug.apk`. This is a **test build**:
you can still remove it over USB while you try things out (Part 10 swaps it for the
permanent one).

---

## Part 8: Add the tablet, then the phone (45 min each)

Do the **tablet first**. Only move to the Pixel once the tablet passes every check.

Android only lets Fortress take the "device owner" role on a device **with no accounts**
on it. That role is what stops the app from being deleted or switched off.

1. **Remove every account** on the device (Settings → Passwords & accounts), or
   factory-reset it and **skip** signing in to Google during setup.
2. Turn on **Developer options**: Settings → About → tap **Build number** 7 times.
   Then Settings → System → Developer options → turn on **USB debugging**.
3. Plug the device into the PC and tap **Allow** on the device when it asks.
4. On the PC (the `adb` from Android Studio is at
   `$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe`):

   ```powershell
   cd ~\fortress\android
   $adb = "$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe"
   & $adb shell dumpsys account
   & $adb install -t app\build\outputs\apk\debug\app-debug.apk
   & $adb shell dpm set-device-owner com.fortress.agent/.FortressAdminReceiver
   ```

   - `dumpsys account` must list **no accounts**.
   - The last command must print **`Success: Device owner set`**. If it complains about
     accounts, go back to step 1.
   - You can add your Google account back **after** this step.
5. Console (unlocked) → **Devices → Add device**: id `tablet` (or `pixel`), platform
   **Android**. Click **Enrol**. Note the **address** (like `192.168.1.20`), id and code.
6. On the device, open **Fortress Agent**, enter the address, id and code, and tap
   **Enrol**. When asked to allow the website filter (a VPN that stays on the device),
   tap **OK**.

**Check:**

- The app shows **Website filter: on**, and a key icon appears in the status bar.
- Console → **Schedules → Block now…** `social` for 1 hour on this device → **Lock**. On the device,
  tap **Check in now**: blocked apps grey out, and blocked sites don't load in Chrome.
- Turn Wi-Fi off and restart the device: still blocked.
- Console → **Dashboard** shows the device with a recent check-in.

---

## Part 9: Make it permanent on the PC (45 min)

Until now Core and the PC's Agent run in windows you can close. This part makes them
start with Windows, run as **SYSTEM** (Windows' own account), and move daily use to a
**standard account** that can't stop them.

Do all of this in a PowerShell **as administrator**.

### 9a. Stop the test copies

Press Ctrl+C in the `fortress serve` and `fortress-agent run` windows.

### 9b. Move Core's data somewhere the daily account can't read

Core's database holds the rules, the lock settings and the key, sealed by the password.
If the daily account can read the database, it can try passwords offline without any
waiting time. If it can write the database, it can clear "Locked until". So move it into
a folder that only SYSTEM and administrators can open:

```powershell
New-Item -ItemType Directory -Force C:\ProgramData\Fortress | Out-Null
icacls C:\ProgramData\Fortress /inheritance:r /grant:r "SYSTEM:(OI)(CI)F" "Administrators:(OI)(CI)F"
New-Item -ItemType Directory -Force C:\ProgramData\Fortress\core | Out-Null
Copy-Item "$env:LOCALAPPDATA\Fortress\fortress.db" C:\ProgramData\Fortress\core\fortress.db
```

(The PC's Agent already keeps its files in `C:\ProgramData\Fortress\agent`, which the
`icacls` line now protects as well.)

### 9c. Run Core and the PC Agent at start-up, as SYSTEM

```powershell
function Add-FortressTask($name, $exe, $arguments) {
    $action   = New-ScheduledTaskAction -Execute $exe -Argument $arguments
    $atBoot   = New-ScheduledTaskTrigger -AtStartup
    $every5   = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 5)
    $settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) `
        -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -MultipleInstances IgnoreNew `
        -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
    Register-ScheduledTask -TaskName $name -Action $action -Trigger $atBoot,$every5 `
        -Settings $settings -User "SYSTEM" -RunLevel Highest
    Start-ScheduledTask -TaskName $name
}
Add-FortressTask "Fortress Core" "$HOME\fortress\core\.venv\Scripts\fortress.exe" "--db C:\ProgramData\Fortress\core\fortress.db serve"
Add-FortressTask "Fortress PC Lock" "$HOME\fortress\windows\.venv\Scripts\fortress-agent.exe" "run"
```

What the settings mean: start at every boot; never time out (Windows otherwise stops
tasks after 3 days); if it stops, start it again within 1–5 minutes; never run two copies.

From now on, to use the `fortress` command directly (as administrator), add
`--db C:\ProgramData\Fortress\core\fortress.db`. Day to day you only need the Console.

**Check:**

- Restart the PC. Before opening anything, the Console shows **Locked** and every device.
- `Get-ScheduledTask "Fortress*" | Get-ScheduledTaskInfo` shows `LastTaskResult 267009`
  ("running") for both.
- A blocked site still fails to load.

### 9d. Switch to a standard account

1. **Settings → Accounts → Other users → Add account**. Create your daily account and
   leave its type as **Standard user** (not administrator).
2. Sign in to it, and pin `fortress_console.exe` to its taskbar. (The file is in the admin
   account's folder, so copy `console\build\windows\x64\runner\Release` to
   `C:\Program Files\Fortress Console` from the admin account first.)
3. **From now on, use only the standard account.**
4. **Hand the Windows administrator password to the partner**, together with the Fortress
   password and recovery code.

**Check** (from the standard account):

- Task Manager can't end `fortress-agent.exe` or `fortress.exe` ("Access denied").
- Opening `C:\ProgramData\Fortress` says you don't have permission.
- The Console still unlocks with the password.

---

## Part 10: Make the phone and tablet permanent (30 min)

The test build from Part 7 can still be removed over USB. The **release build** can't.
Switch over only when Part 8 has worked for a few days. The full steps are in
[`android/README.md`](../android/README.md), under "Release builds". In short:

1. Create a **signing key**, once. **Back it up with the password and recovery code.** If
   it's lost, the only way to update or remove Fortress on that device is a factory reset.
2. Build `gradlew :app:assembleRelease`.
3. Remove the test build over USB, then install the release build and make it device
   owner as in Part 8.
4. In the Console, click **Re-enrol** for the device and enter the new code on it.

---

## Day to day

| I want to… | Do this |
|---|---|
| See what's blocked now | Console → **Dashboard** (no unlock needed) |
| Block something right now | Unlock → **Schedules → Block now…** → list, hours, devices → **Lock** |
| Change a schedule | Unlock → **Schedules** → remove the old one, add the new one → **Lock** |
| Make impulse unlocks harder | Settings → **Unlock delay** (e.g. 20 min of waiting after the right password) |
| Lock myself out until a date | Settings → **Locked until**. Only the recovery code gets in before then |
| See if a device stopped checking in | Dashboard: **amber** = no check-in for 24 h, **red** = 72 h |
| See what happened | **Activity**: every unlock, wrong password, change, and blocked-attempt counts |

Changes reach the devices when you **Lock** (or after 15 minutes idle, which locks
automatically), and each device picks them up at its next check-in (every 15 minutes,
or **Check in now** on the device).

## Back up (do this once a month)

If the PC dies with no backup, **no device can ever be released or changed again**,
except by factory-resetting it. Back up, as administrator:

- `C:\ProgramData\Fortress\core\fortress.db`. It's safe to copy: everything secret in it is
  sealed by the password.
- `android\fortress-release.jks` and `android\keystore.properties` (Part 10).

Keep the copies on a USB stick that the **partner** holds.

---

## When something goes wrong

| What you see | Why, and what to do |
|---|---|
| **No internet on the PC at all** | The PC Agent stopped while Windows still sends lookups to it. As admin: `Start-ScheduledTask "Fortress PC Lock"`. To give up filtering until the next boot, reset DNS as shown in Part 6 |
| "Wrong code" when enrolling | Check the code in the Console. 5 wrong tries cancel it; click **Enrol** again for a new one |
| "Code has expired" | Codes last 30 minutes. Make a new one |
| Device can't reach Core | Same Wi-Fi? Network set to **Private** (Part 0)? Firewall rule added (Part 4b)? Core running (Dashboard loads)? |
| "device clock is more than 5 minutes off" | Turn on automatic time on that device |
| Device shows **amber/red** | It hasn't checked in. Open the Agent on it and tap **Check in now**. If it was wiped, re-enrol it |
| "Too many wrong attempts" | Wait: each wrong password doubles the wait, up to 15 minutes |
| Forgot the password | Console → **Unlock** → **Forgot the password? Use the recovery code**, then enter the code and a new password |
| Lost the password **and** recovery code | Nothing can be changed or released. Each device has to be factory-reset (PC: reinstall Windows, or remove it with the admin password). This is by design |
| A site still loads | Was the tab already open? Close the browser and reopen it. Is it a different browser (Brave, Opera, Firefox on Android)? Block that browser as an app |
| `fortress` says the database was "made by a newer Fortress Core" | Update the code (`git pull`) and reinstall (`pip install -e`) before using it |

## Removing Fortress

- **A device:** Console → unlock → **Devices → Remove**. At its next check-in the device
  lifts every block and gives up the device-owner role.
- **The PC lock:** remove the `pc` device as above, then as administrator:
  `Unregister-ScheduledTask "Fortress PC Lock" -Confirm:$false`.
- **All of Fortress:** remove every device first, then
  `Unregister-ScheduledTask "Fortress Core" -Confirm:$false`. Delete
  `C:\ProgramData\Fortress` only after every device is released.
