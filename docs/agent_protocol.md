# Fortress Agent protocol (v1)

How an Agent (Spec 01 §3.2) enrols with Fortress Core, proves who it is, fetches rules
and checks in. Reference implementation: `core/fortress_core/agents.py`. Shared test
vectors that every Agent's tests must pass: `testdata/fortress_vectors.json`.

## 1. Transport

- Core listens for Agents on **TCP 47801, all interfaces** (the Console's API stays on
  `127.0.0.1:47800`). On Windows this needs one inbound firewall rule for the Private
  network profile.
- Plain HTTP on the home network. **Integrity does not depend on the network:** rules
  are signed by Core's Ed25519 key (`rules_format.md`), and every Agent request is
  signed by the device's own key (§3).
- Not confidential: someone on the home Wi-Fi can read which sites and apps are on the
  lists. Accepted for v1.

## 2. Enrolment (contract A1)

Starting an enrolment needs an **unlocked** Console (Devices → Enrol), so R2 holds:
nothing joins Fortress without the password.

1. Core makes a one-time **enrolment code** for one device id: 10 characters from
   `ABCDEFGHJKMNPQRSTUVWXYZ23456789` (about 49 bits), shown as `XXXXX-XXXXX`. It is valid
   for **30 minutes**, works **once**, and is cancelled after **5 wrong proofs**.
2. The Agent creates its device key: **ECDSA P-256**, kept in hardware where the
   platform allows (Android Keystore), never exported.
3. Both sides derive `k = SHA-256("fortress-enrol-v1:" + normalize(code))`, where
   `normalize` upper-cases and keeps only letters and digits.
4. The Agent sends, **without the code itself**:

   ```
   POST /agent/v1/enrol
   {"device_id": "tablet", "public_key": "<b64 SPKI DER>", "nonce": "<b64, 16 random bytes>",
    "proof": "<b64 HMAC-SHA256(k, M_agent)>"}

   M_agent = "fortress-enrol-v1\nagent\n" + device_id + "\n" + public_key + "\n" + nonce
   ```

5. Core checks the proof, binds the public key to the device (replacing any older key),
   deletes the code, and answers:

   ```
   {"core_public_key": "<b64 raw 32-byte Ed25519 key>", "key_id": "<16 hex>",
    "proof": "<b64 HMAC-SHA256(k, M_core)>", "bundle": {<latest envelope>}}

   M_core = "fortress-enrol-v1\ncore\n" + device_id + "\n" + public_key + "\n" + nonce
            + "\n" + core_public_key
   ```

6. The Agent checks the proof (constant-time), checks `key_id`, **pins** Core's key,
   then accepts `bundle` by the normal rules (`rules_format.md` §1).

A fake Core cannot produce `proof` without the code, and the code never crosses the
network. All strings above are UTF-8; base64 is standard with padding.

| Answer | Meaning |
|---|---|
| 200 | Enrolled |
| 403 `bad_proof` | Wrong code (counts toward the 5) |
| 404 `no_enrolment` | No code waiting for this device id |
| 410 `expired` | Code older than 30 minutes, or cancelled |
| 400 `invalid` | Malformed request, or a key that is not P-256 |

## 3. Signed requests

Every other request carries:

| Header | Value |
|---|---|
| `X-Fortress-Device` | device id |
| `X-Fortress-Time` | Unix time, whole seconds |
| `X-Fortress-Nonce` | base64 of 16 random bytes, new for every request |
| `X-Fortress-Signature` | base64 DER ECDSA-P256-SHA256 signature over `S` |

```
S = "fortress-agent-v1\n" + METHOD + "\n" + PATH + "\n" + device_id + "\n"
    + time + "\n" + nonce + "\n" + hex(SHA-256(body bytes))
```

`PATH` is the URL path exactly as sent (no query strings are used). An empty body hashes
as the empty string.

Core refuses (401) when the device is unknown or not enrolled, the time is more than
**300 s** from Core's clock, the nonce was already used by that device within the last
**600 s**, or the signature fails. A released device can still call in, so it can fetch
the bundle that releases it.

## 4. Endpoints

### `GET /agent/v1/bundle`

The latest signed envelope. The Agent applies `rules_format.md` §1 to it as usual.

### `POST /agent/v1/checkin` (contract A5)

```json
{"version": 7, "agent_version": "0.1.0", "enforcing": true,
 "events": [{"at": "2026-10-19T12:00:00Z", "kind": "bundle_accepted", "detail": "version 7"}]}
```

Optional `reports` (Agent 0.4.0): up to 8 sources, each `{"at": "<when the app sent it>",
"data": {...}}` and at most 32 KB as compact JSON, e.g.
`"reports": {"block_trainer": {"at": "2026-10-25T18:00:00Z", "data": {"v": 1, ...}}}`. They
are summaries other apps on the device hand to the Agent (Block Trainer's logged workouts and
bodyweight). Core keeps the newest per device and source and serves them read-only at
`GET /api/v1/reports` on the Console API, for the PC's Beeminder check. Core never acts on
them, and a report can't change what a device blocks.

`version` is the highest bundle the Agent holds. At most 200 events per check-in, each
`kind` up to 40 characters and `detail` up to 500. Core records the check-in time
(what the Console's amber/red uses) and writes the events to Activity.

Answer:

```json
{"latest_version": 8, "released": false}
```

When `latest_version` is higher than what it holds, the Agent fetches the bundle.
`released` is a hint only: an Agent stands down **only** on a signed bundle listing its
id in `released` (contract A6).

## 5. Agent schedule

Check in when the network comes up, at boot, and every 15 minutes; fetch the bundle when
told a newer one exists. Enforcement never waits for the network (contract A4).
