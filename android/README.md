# Fortress Agent for Android (Phase 3)

Enforces Fortress on the Lenovo Idea Tab and, later, the Pixel 8a (both Android 16).

**What works now:** enrolment with Core, receiving and verifying signed rules, **app
blocking on schedule** (blocked apps are suspended: installed, but they will not open),
blocking offline, the clock locked to network time, check-ins, and standing down on a
signed release from the Console.

**Not yet:** website blocking (Phase 4, a local filter), and the hardening that stops
the app being removed (Phase 5). Until Phase 5, a **debug build** is used on purpose: it
can still be removed over USB.

| Module | What |
|---|---|
| `agent-core/` | All decisions, in plain Kotlin: bundle verification, schedules, matching, the Agent protocol, check-ins. Tested on the desktop JVM |
| `app/` | The Android part: Keystore device key, app suspension, alarms, boot handling, a read-only status screen |

## Build and test

Needs JDK 17+ and the Android SDK (Android Studio provides both).

```
cd android
gradlew :agent-core:test          # includes testdata/fortress_vectors.json, shared with Core
gradlew :app:assembleDebug        # app/build/outputs/apk/debug/app-debug.apk
```

The live test drives a real Core over the network:

```
fortress device enrol tablet                      # prints a one-time code
fortress serve                                    # in another window
set FORTRESS_AGENT_URL=http://127.0.0.1:47801
set FORTRESS_DEVICE_ID=tablet
set FORTRESS_ENROL_CODE=XXXXX-XXXXX
gradlew :agent-core:test --tests *LiveCoreTest* --rerun
```

## The PC

1. Run Core: `fortress serve`. It now also listens for Agents on port **47801**.
2. Allow that port on the home network only (PowerShell as administrator):

   ```
   New-NetFirewallRule -DisplayName "Fortress Agents" -Direction Inbound -Protocol TCP -LocalPort 47801 -Profile Private -Action Allow
   ```

   and make sure the home Wi-Fi is set to **Private** in Windows network settings.

## Setting up the tablet (test build)

Android only accepts a device owner on a device with **no accounts**. Back up the tablet
first.

1. Remove every account (Settings → Passwords & accounts), or factory-reset and skip
   adding a Google account during setup.
2. Turn on Developer options → **USB debugging**, and connect the tablet to the PC.
3. Install and make Fortress the device owner:

   ```
   adb install -t android\app\build\outputs\apk\debug\app-debug.apk
   adb shell dpm set-device-owner com.fortress.agent/.FortressAdminReceiver
   ```

   The second command must print `Success: Device owner set…`. Accounts can be added
   back after this.
4. In the Console (unlocked): **Devices → Add device** (`tablet`, Android), then **Enrol**.
   It shows the PC's address, the device id and a code valid for 30 minutes.
5. On the tablet, open **Fortress Agent**, enter the three, and tap **Enrol**.

## Phase 3 check: "a blocked app won't open on the tablet"

1. Find an installed app's package name: `adb shell pm list packages | findstr -i game`.
2. In the Console: add it to a block list, **Block now** for 1 hour on the tablet, **Lock**.
3. On the tablet: **Check in now** (or wait up to 15 minutes). The app's icon greys out
   and opening it shows that it is blocked by the administrator.
4. Turn Wi-Fi off and reboot: the app stays blocked. When the hour ends, it opens again
   on its own, with Wi-Fi still off.
5. Settings → Date & time cannot be changed while Fortress is the device owner.

## Removing it

- **The normal way:** Console → Devices → Remove. The tablet gets a signed release at its
  next check-in, lifts every block and stops being device owner.
- **Test builds only, over USB:**

  ```
  adb shell dpm remove-active-admin com.fortress.agent/.FortressAdminReceiver
  adb uninstall com.fortress.agent
  ```

## Before using a release build

A device-owner app can only be updated by an APK **signed with the same key**. Before the
first release build goes on a device (Phase 5), make a signing key, keep it with the
Fortress password, and never lose it: without it, the only way to update or remove
Fortress is a factory reset.
