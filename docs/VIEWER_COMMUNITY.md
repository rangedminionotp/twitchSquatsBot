# Viewer Community Squats (local MVP)

This is the local, single-streamer MVP for Viewer-contributed squats. It is part
of the separate cloud preview and does not change the original port 8080 app.
No public URL, DNS record, hosting resource or production Twitch application is
created by this implementation.

## What works

- A public `/viewer` page with a separate Twitch Viewer login.
- Browser-local MediaPipe pose inference; camera frames and pose landmarks are
  never sent to this server.
- Per-Viewer calibration: stable standing, demonstrated squat depth and return
  to standing. Later reps use that personal range.
- Full stand → depth → stand detection with stability, pose-loss and frame-gap
  protection, plus live knee angle and calibration metrics.
- Server-issued runs with cumulative counts, monotonically increasing sequence
  numbers, idempotent retries and plausible client/server timing checks.
- A 20-rep run target and a hard 100-rep daily limit in the configured channel
  timezone. A smaller final run is issued when fewer than 20 reps remain.
- An all-time Community Count, recent contribution ledger, impossible-speed
  review flags and broadcaster revocation.
- Viewer sessions cannot access broadcaster counters, rules, queue, camera page
  or moderation APIs.

## Run it locally

On WSL, `bash scripts/start_cloud_wsl.sh` loads the ignored `.env.cloud` file.
On its first run it prepares non-secret defaults, imports the broadcaster ID from
the existing local app and generates a stable encryption key. It stops with the
exact missing fields until a separate Twitch Confidential Web App is configured.

1. Complete the cloud developer setup in [CLOUD.md](CLOUD.md), using a separate
   confidential Twitch application with this exact development redirect:
   `http://127.0.0.1:8090/auth/callback`.
2. Start with `CLOUD_COMMUNITY_OWNER_ID` empty, run the cloud service and sign in
   to the broadcaster control panel once. This creates the owner in the selected
   cloud database.
3. Set `CLOUD_COMMUNITY_OWNER_ID` to that broadcaster's numeric Twitch user ID.
   Set `CLOUD_COMMUNITY_TIMEZONE` to the IANA timezone that defines the daily
   reset; the default is `America/Los_Angeles`.
4. Restart the cloud service. Open `http://127.0.0.1:8090/viewer` in Chrome or
   Edge. The control panel at `/` now includes Viewer Community moderation.
5. Sign in through **Continue with Twitch**, start the camera and select
   **Calibrate & play**. Keep the full body visible and follow the three prompts.

The server intentionally binds only to `127.0.0.1`. Another device cannot reach
this local preview. Do not expose port 8090 directly or put it behind a quick
tunnel; the public edge design is a separate, not-yet-performed step.

## Data and trust boundary

The browser sends only:

- the opaque server run ID;
- a monotonically increasing request sequence;
- the cumulative accepted count for that run; and
- milliseconds elapsed since calibration.

Calibration sends the demonstrated standing angle, squat angle and calibration
duration. Video frames and the 33 MediaPipe landmarks stay in browser memory.
They are neither serialized nor written to the database. Loading MediaPipe still
makes normal asset requests to jsDelivr and Google model storage.

This is an entertainment anti-abuse model, not cryptographic proof of exercise.
A developer-tools user controls their browser and can fabricate metadata. The
server raises the cost of casual cheating with Twitch identity, a bound session,
CSRF/origin checks, calibration gating, cumulative values, strict sequencing,
client/server timing checks, daily limits, automatic flags and manual revocation.
It does not make local pose inference trustworthy enough for money, prizes,
withdrawals or anything with material value.

## HTTP contract

All Viewer writes require the Viewer/admin session cookie, exact Origin and the
session CSRF header. Request bodies cannot select a Viewer or channel.

| Endpoint | Access | Exact JSON fields | Purpose |
| --- | --- | --- | --- |
| `GET /api/community` | Public | — | Minimal channel and Community Count. |
| `GET /api/viewer` | Signed in | — | Viewer identity, CSRF, daily allowance and active run. |
| `POST /api/viewer/start` | Signed in | none (`{}`) | Resume the active run or issue the next bounded run. |
| `POST /api/viewer/calibrate` | Signed in | `run_id`, `standing_angle`, `squat_angle`, `duration_ms` | Unlock progress after plausible calibration. |
| `POST /api/viewer/progress` | Signed in | `run_id`, `sequence`, `count`, `elapsed_ms` | Submit an idempotent cumulative total. |
| `POST /api/viewer/delete` | Signed in Viewer | `confirm` = `DELETE` | Delete Viewer participation and remove accepted reps. |
| `GET /api/community/admin` | Configured owner | — | Recent increments and review flags. |
| `POST /api/community/revoke` | Configured owner | `contribution_id` | Revoke one increment and end its run. |

Revocation subtracts the increment from the Community Count and that Viewer's
daily accepted amount. It is idempotent. It does not rewrite a prior video or pose
record because no such record exists.

Public plain-language disclosures are served at `/privacy` and `/rules`. Viewer
OAuth tokens are discarded after identity verification; only the Twitch ID and
login name are retained for Viewer-only accounts. The live deletion action does
not remove records from existing backups, which remain subject to the operator's
documented retention policy.

## Verification

```text
python -m unittest tests.python.test_community tests.python.test_cloud -v
node tests/javascript/test_viewer_detector.mjs
node --experimental-vm-modules tests/javascript/test_viewer_controller.mjs
```

The controller test asserts that calibration and progress requests contain only
their allowlisted metadata fields. Tests use temporary databases and fake camera,
model, OAuth and HTTP responses. A local headless Chrome render has been checked
at desktop and narrow responsive layouts; real camera accuracy still needs manual
testing on the intended devices.

## Stop point before a public URL

The next milestone must be treated as a deployment/security task, not as another
frontend toggle. Before creating or connecting a public URL:

1. choose the host, domain, budget, backup retention and operator access model;
2. review the supplied reverse-proxy/service templates and expose only HTTPS 443;
3. register the exact production OAuth callback and use production secrets;
4. test Viewer and broadcaster flows with two real Twitch accounts;
5. test phone/desktop cameras, model download failures and daily timezone rollover;
6. add production monitoring, database backup/restore practice and abuse-rate policy;
7. perform the deployment review in [CLOUD_DEPLOY.md](CLOUD_DEPLOY.md).

Do not set `CLOUD_DEV=0`, change the Twitch callback, provision hosting or expose a
port as part of this local milestone.
