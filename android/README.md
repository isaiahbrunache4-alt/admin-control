# Fortress Agent for Android

Enforces Fortress on the Lenovo Idea Tab and the Pixel 8a (both Android 16).

**What it does:**

| | |
|---|---|
| App blocking (Phase 3) | Blocked apps are suspended on schedule: installed, but they will not open |
| Website blocking (Phase 4) | A filter on the device refuses lookups for blocked sites on schedule. Allowed sites always pass |
| Offline | Blocks start and end on time with no network; suspensions survive reboots |
| Clock | Locked to network time, so moving the clock cannot end a block |
| Check-ins | Every 15 minutes: fetches new rules, reports what it did and counts of blocked attempts |
| Release | Console → Devices → Remove lifts every block and Fortress steps down |

There is no unlock or setting on the device. Every change is made in the Console on the PC.

| Module | What |
|---|---|
| `agent-core/` | All decisions, in plain Kotlin: bundle verification, schedules, matching, DNS packets, the Agent protocol, check-ins. Tested on the desktop JVM |
| `app/` | The Android part: Keystore device key, app suspension, the website filter, alarms, boot handling, a read-only status screen |

## How website blocking works

Fortress runs a VPN **that stays on the device**. It gives Android one DNS server address
and routes only that address into itself, so it sees DNS lookups and nothing else: web
traffic never passes through it, and Fortress's own traffic is left out of it. A blocked
name gets "no such domain"; any other lookup goes to the network's own DNS server and the
answer comes back unchanged. Blocking `tiktok.com` also blocks `www.tiktok.com` and every
other subdomain.

As device owner, Fortress keeps the filter on and closes the usual ways around it:

- It is the **always-on VPN**: Android starts it at boot and restarts it. VPN settings
  cannot be changed on the device.
- **Private DNS** stays on "automatic" (the strict setting would send lookups past the filter).
- **Chrome's secure DNS** is turned off (Chrome policy `DnsOverHttpsMode`). Check on the
  tablet at `chrome://policy`.

It records **how many** lookups each block-list entry stopped, e.g. "tiktok.com 12", and
nothing about allowed sites.

Limits, stated honestly:

- A browser with its own built-in secure DNS that Fortress does not manage (Firefox, for
  example) can look names up itself. Block such browsers as apps if that matters.
- If the filter ever stopped and Android did not restart it, sites would load unfiltered
  rather than the network failing (it is always-on, not "lockdown"). Fortress logs
  `filter_stopped` to Activity when that happens.

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

1. Run Core: `fortress serve`. It listens for Agents on port **47801**.
2. Allow that port on the home network only (PowerShell as administrator):

   ```
   New-NetFirewallRule -DisplayName "Fortress Agents" -Direction Inbound -Protocol TCP -LocalPort 47801 -Profile Private -Action Allow
   ```

   and make sure the home Wi-Fi is set to **Private** in Windows network settings.

## Setting up a device

The same steps for the tablet and, once the tablet is proven, the Pixel (device id
`pixel`). Android only accepts a device owner on a device with **no accounts**. Back up
first.

1. Remove every account (Settings → Passwords & accounts), or factory-reset and skip
   adding accounts during setup. `adb shell dumpsys account` lists what is left.
2. Turn on Developer options → **USB debugging**, and connect the device to the PC.
3. Install and make Fortress the device owner:

   ```
   adb install -t fortress-agent-debug.apk
   adb shell dpm set-device-owner com.fortress.agent/.FortressAdminReceiver
   ```

   The second command must print `Success: Device owner set…`. Accounts can be added
   back after this.
4. On the PC: add the device and make a code, in the Console (**Devices → Add device**,
   then **Enrol**) or with `fortress device add pixel android "Pixel 8a"` and
   `fortress device enrol pixel`.
5. On the device, open **Fortress Agent**, enter the PC's address, the device id and the
   code, and tap **Enrol**.

**Updating** a device that already has Fortress: `adb install -r -t fortress-agent-debug.apk`.
Nothing else changes; it stays enrolled.

## Checks

**Apps (Phase 3):**

1. Find an installed app's package name: `adb shell pm list packages | findstr -i game`.
2. Add it to a block list, **Block now** for 1 hour on the device, **Lock**.
3. On the device: **Check in now**. The app's icon greys out and it will not open.
4. Wi-Fi off and reboot: still blocked. When the hour ends, it opens again by itself.

**Websites (Phase 4):**

1. Fortress Agent shows **Website filter: on**, and a key icon shows in the status bar.
   If it shows off with a **Start website filter** button, tap it once and approve.
2. Add a site (e.g. `youtube.com`) to a block list, **Block now**, **Lock**, **Check in now**.
3. In Chrome, `youtube.com` and `m.youtube.com` fail to load; other sites load normally.
4. When the block ends, the site loads again (a browser may cache a failed lookup for a
   minute).
5. At the next check-in, Activity on the PC shows `sites_blocked: youtube.com N`.

## Removing it

- **The normal way:** Console → Devices → Remove. The device gets a signed release at its
  next check-in, lifts every block and the filter, and stops being device owner.
- **Test builds only, over USB:**

  ```
  adb shell dpm remove-active-admin com.fortress.agent/.FortressAdminReceiver
  adb uninstall com.fortress.agent
  ```

- **Always:** a factory reset removes Fortress (Spec 01 §7.3).

## Release builds (Phase 5)

The test build can be removed over USB, which is useful while testing and is why it is
used now. A release build cannot: as device owner it cannot be uninstalled from the
device. Switch when everything above works.

A device-owner app can only be updated by an APK **signed with the same key**. Make the
key once, keep it (and its password) with the Fortress password and recovery code, and
never lose it: without it, the only way to update or remove Fortress is a factory reset.

```
cd android
& "C:\Program Files\Android\Android Studio\jbr\bin\keytool.exe" -genkeypair -v -keystore fortress-release.jks -alias fortress -keyalg RSA -keysize 3072 -validity 10000
```

Then create `android\keystore.properties` (never committed; `.gitignore` covers it):

```
storeFile=fortress-release.jks
storePassword=…
keyAlias=fortress
keyPassword=…
```

and build `gradlew :app:assembleRelease` (`app/build/outputs/apk/release/app-release.apk`).
To move a device from the test build to the release build: remove the test build over
USB (above), remove accounts again, then install the release APK and set it as device
owner as in "Setting up a device". The device keeps its id; make a new code with
**Re-enrol** in the Console.
