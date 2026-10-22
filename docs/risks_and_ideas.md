# Weak points and ideas

Found in a code review in October 2026, after Core, the Console and both Agents were
built. **Weak points** are ways Fortress can stop working or be got around, most serious
first. **Ideas** are features that would make it more likely to do its real job:
less time lost to distractions, with blocks that hold when it counts.

Already fixed in the same review: wrong-typed schedules crashing validation, times
without a time zone, the PC's DNS filter ignoring the network's own DNS servers, the
Phase 8 `sc.exe` step that could never start, a wrong recovery code ending the Console's
unlock, and opening a database written by a newer Core.

## Weak points

| # | Weak point | Effect | What to do |
|---|---|---|---|
| 1 | **Core isn't a background service.** `fortress serve` runs only while its window is open, under the account that started it | After switching to a standard account (Phase 8), Core isn't running: the Console can't connect and devices can't check in | Run it as a SYSTEM scheduled task. [Setup guide](setup_guide.md) Part 9c |
| 2 | **The database is readable by the daily account** (`%LOCALAPPDATA%`, or `C:\ProgramData` with default permissions) | Anyone who can read it can guess the password offline at full speed, skipping the growing wait. Anyone who can write it can clear "Locked until", the unlock delay and the failure count | Move it to `C:\ProgramData\Fortress` with SYSTEM/Administrators-only access (guide Part 9b). Also consider a longer minimum password (it's 8 now; a 4-word passphrase is far stronger) |
| 3 | **The PC's filter only covers IPv4 DNS.** `netsh … ipv4 set dnsservers` points the adapters at the filter, but IPv6 DNS servers from the router stay | On a home network with IPv6, Windows can look names up over IPv6 and skip the filter completely | On the PC, run `nslookup tiktok.com` while a block is on. If it answers with an address, this is happening. Fix: also point IPv6 at the filter (listen on `::1` and `netsh … ipv6 set dnsservers … static ::1`), or turn off IPv6 on the adapters. Needs testing on the PC |
| 4 | **Windows programs are matched by file name only** (`steam.exe`). The design says "file and publisher" | Copying or renaming `steam.exe` to `s.exe` gets around the block. Portable browsers dropped into the Downloads folder do too | Match on the code-signing publisher, or on the path, or both. Or block running programs from user-writable folders (Downloads, Desktop, AppData) while locked |
| 5 | **Browsers not covered by policy.** Only Chrome, Edge and Firefox get "secure DNS off". Brave, Opera, Vivaldi, Tor Browser, and Firefox on Android, can use their own encrypted DNS | Blocked sites load in those browsers | Add the known browsers to a default "other browsers" block list, on the PC and on Android |
| 6 | **Open connections survive a block.** Blocking works by refusing name lookups | A video or feed already open when a block starts can keep playing for minutes, sometimes until the tab closes | When a block starts, the PC Agent could close the browsers (or just the affected tabs/apps). On Android, briefly suspending and then un-suspending the browser has the same effect |
| 7 | **The PC with no backup is a single point of failure.** The signing key exists only in Core's database | If the PC dies, no device can be released or changed again: every device needs a factory reset | Back up `fortress.db` regularly. It's safe to copy because everything secret in it is sealed. Guide: "Back up" |
| 8 | **The Android release signing key** | If it's lost, Fortress on the devices can't be updated or removed except by a factory reset | Back it up with the password (guide Part 10) |
| 9 | **The recovery code bypasses "Locked until"** (by design) | If the user holds the recovery code, "Locked until" only blocks the password | The partner must hold the code, not the user. The guide says so |
| 10 | **Tampering is only visible after 24 h** (amber) or 72 h (red), and only to whoever opens the Console | A device removed on Friday night goes unnoticed all weekend | Alerts to the partner (Idea 2) |
| 11 | **When the PC Agent stops, the PC has no internet.** The adapters still point at the stopped filter | Good for blocking (it fails closed), but confusing, and after uninstalling without a release the PC stays offline | The guide gives the fix. The scheduled task restarts the Agent within 5 minutes |
| 12 | **Release resets DNS to "automatic"** | A PC that had DNS servers set by hand loses them after Fortress is removed | Save the original settings at enrolment and restore them on release |
| 13 | **Any program on the PC can send wrong passwords to Core** (the API is local-only, which is right) | Each wrong try doubles the wait, up to 15 minutes, so a misbehaving program can keep the real user waiting | Low priority. Could limit the delay to the Console's own attempts by counting them per client |

## Ideas that would make Fortress work better

Most useful first.

1. **Loosening waits, tightening is instant.** Adding a block applies straight away, but
   removing one, shortening a schedule or adding to the allowed list only takes effect
   after, say, 24 hours. It can be cancelled in that time. This is the strongest single
   defence against impulse changes, and it still works when you hold the password
   yourself. Core already signs everything, so the bundle can carry the "takes effect at"
   time and the Agents apply it on schedule offline.
2. **Partner alerts and a weekly summary.** Send the partner a message (email, or a
   phone notification) when a device goes amber, an Agent reports "not enforcing", or
   someone unlocks or makes a change. Send a weekly summary of blocked attempts per site.
   Being seen is a large part of what makes commitment devices work.
3. **The partner approves unlocks from their phone** instead of typing a password into
   your PC. You request an unlock with a reason, they tap Approve. The password stays
   with them, the reason is logged, and a 2 a.m. unlock is much less likely.
4. **"Only these" schedules (allow-list mode).** For bedtime or exam weeks: block
   everything except a short list (phone, messages, maps, school sites). This is much
   harder to get around than listing every distracting site one by one.
5. **Ready-made block lists that are actually complete.** Blocking `tiktok.com` doesn't
   stop the TikTok app, which uses other domains (`tiktokv.com`, `tiktokcdn.com`,
   `byteoversea.com`, …). Ship maintained lists for social media, video, games, news and
   browsers, with every domain and app package each one needs.
6. **Daily time allowances** instead of all-or-nothing, e.g. "YouTube 30 minutes a day".
   Android can measure app usage, and the PC Agent already sees programs and lookups.
   Allowances are easier to keep to than total bans, so people keep Fortress on longer.
7. **New apps need approval while locked.** As device owner, the Android Agent can
   suspend every newly installed app until it's allowed in the Console. That closes "just
   install a different browser". Same on the PC with Idea 4 above.
8. **A gentle "blocked" screen.** Instead of a page that just fails to load, show "You
   blocked this until 15:00. What did you come here to do?" This prompt is known to cut
   repeat attempts. On Android, a notification is the easy version. In browsers it needs
   a local page, plus care with HTTPS certificates.
9. **Streaks and trends on the Dashboard:** days without an unlock, blocked attempts going
   down week by week. Encouraging progress keeps people using the tool.
10. **Focus sessions from any device.** Start "block `social` for 2 hours" from the phone
    without the password. It only ever tightens, so it's safe. Core accepts it from an
    enrolled device and signs it.
