# Fortress rules and bundle format

Reference for every Agent (Spec 01 §3.2). The Python reference implementation is
`core/fortress_core/` (`bundle.py`, `rules.py`, `schedule.py`), and the cases in
`core/tests/test_schedule.py` and `core/tests/test_bundle.py` are the ones each Agent's
own tests should repeat.

## 1. Envelope

What Core publishes and an Agent receives:

```json
{"format": 1, "key_id": "abed986a2cadcdc8", "payload": "<base64>", "sig": "<base64>"}
```

| Field | Meaning |
|---|---|
| `format` | Always `1` for now. Reject anything else |
| `key_id` | First 16 hex characters of SHA-256 of Core's raw 32-byte Ed25519 public key |
| `payload` | Base64 (standard, padded) of the UTF-8 JSON payload bytes |
| `sig` | Base64 Ed25519 signature over **exactly those payload bytes** |

### Agent checks, in order (contract A2)

1. `format == 1`
2. `key_id` equals the id of the key pinned at enrolment
3. `payload` and `sig` decode as base64
4. The signature verifies against the pinned key, **before** the payload is parsed
5. The payload is a JSON object with an integer `version`
6. `version` is **strictly greater** than the highest version this Agent has accepted

Fail any check and the Agent keeps enforcing what it already has (A4). After accepting,
it stores the bundle and the new highest version durably, so a reboot does not reopen
older bundles.

The public key is printed by `fortress pubkey` (base64 of the raw 32 bytes).

## 2. Payload

```json
{
  "version": 3,
  "issued_at": "2026-10-19T12:00:00Z",
  "released": ["tablet"],
  "rules": {
    "lists": {
      "social": {
        "domains": ["*.reddit.com", "tiktok.com"],
        "android_packages": ["com.zhiliaoapp.musically"],
        "windows_programs": ["steam.exe"]
      }
    },
    "schedules": [
      {"id": "s1", "list": "social", "devices": ["pixel", "tablet"], "kind": "weekly",
       "days": ["mon", "tue", "wed", "thu", "fri"], "from": "08:00", "to": "15:00",
       "tz": "America/New_York"},
      {"id": "s2", "list": "social", "devices": ["all"], "kind": "once",
       "start": "2026-10-19T12:00:00Z", "end": "2026-10-19T14:00:00Z"}
    ],
    "allow": {
      "domains": ["github.com", "pypi.org"],
      "android_packages": ["com.shotput.app"],
      "windows_programs": []
    }
  }
}
```

- `released`: device ids that have been removed. An Agent whose id is listed stands
  down (A6). Ids are never reused.
- Unknown fields are ignored, so later versions can add fields.

## 3. Items

| Kind | Form | Notes |
|---|---|---|
| `domains` | `tiktok.com` or `*.tiktok.com` | Lower case. Both forms match the name **and every subdomain**. No URLs |
| `android_packages` | `com.zhiliaoapp.musically` | Exact match |
| `windows_programs` | `steam.exe` | Lower case; compare case-insensitively |

Domain matching: strip one trailing `.`, lower-case the host, then it matches pattern
`p` (with any leading `*.` removed) when `host == p` or `host` ends with `"." + p`.
So `nottiktok.com` does **not** match `tiktok.com`.

## 4. Schedules

| Field | Weekly | Once |
|---|---|---|
| `id` | `s<n>`, never reused | same |
| `list` | name of a list | same |
| `devices` | device ids, or `["all"]` | same |
| `days` | from `mon tue wed thu fri sat sun` | — |
| `from`, `to` | `HH:MM`, 24-hour, local to `tz` | — |
| `tz` | IANA zone, e.g. `America/New_York` | — |
| `start`, `end` | — | UTC, `YYYY-MM-DDTHH:MM:SSZ` |

Weekly evaluation, with `t` the local time in `tz`:

- `from < to`: active on a listed day when `from <= t < to`.
- `from > to` (overnight): the window **belongs to the day it starts on**. Active when
  today is listed and `t >= from`, or yesterday is listed and `t < to`.
- `from == to`: active for the whole of each listed day.

Once: active when `start <= now < end`.

## 5. What is blocked

On a device, at a moment: take every schedule that targets the device (its id, or
`all`) and is active, and union the items of their lists. Then:

1. Anything on the `allow` list is **never** blocked (Spec 01 §10).
2. Otherwise, it is blocked if it is in that union.

Agents evaluate this locally against automatic network time, so blocks start and stop
on time offline (Spec 01 §8.3).
