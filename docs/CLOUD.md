# Cloud preview: multi-user software

This is an **experimental, separate entry point**, not a production deployment.
The existing `python -m squat_capture` local app and local data remain unchanged.
Do not expose the local app's port 8080 through a public tunnel.

## Implemented

- Manual free-capture sets (1–500 reps), separate from the redemption queue;
  accepted reps reduce overall debt without adding new debt.
- Twitch reward picker and stream-ID-based completion totals. Stream status is
  polled every 60 seconds; only a live observation newer than 120 seconds receives
  stream completion increments. Offline/unknown increments remain lifetime-only
  and are not retrospectively assigned to a stream.
- Optional per-account Streamlabs and StreamElements donation connections with
  encrypted, write-only credentials and independent amount/currency/rep rules.
  Configure only one provider for the same payment feed: different provider IDs
  cannot reliably deduplicate a payment relayed through both services.
- Twelve-hour browser sessions, production enrollment allowlist (empty denies
  login), bounded connection concurrency, request timeouts and rate limits.
- Account deletion after EventSub cleanup, SQLite backup command and deployment
  templates. Deletion does not remove historical backups or revoke provider grants.

- Twitch authorization-code login, with server-side identity validation.
- Browser-bound, expiring, single-use OAuth state.
- SQLite user isolation: mutations use the server session's user ID, never an ID
  supplied by the browser. Account login does not overwrite existing counters.
- Encrypted OAuth credentials (Fernet); hashed opaque sessions and overlay keys.
- HttpOnly / SameSite cookies; Secure and `__Host-` prefix outside development.
- Origin + CSRF verification for all mutations; bounded JSON bodies.
- Personal manual owed counter and read-only, revocable OBS overlay link.
- No default request-URL logs, referrers or response caching that disclose links.
- Per-account reward/sub/gift/Bits rules, strict validation and authenticated editing.
- Durable FIFO redemption queue: Channel Points never add owed; support events
  only add owed, never queue. Completed challenge reps also pay down future owed.
- Transactional receipts, counter increments and enqueue; concurrent duplicate
  delivery is counted once. Redemption IDs are also deduplicated across message IDs.
- Optional `/eventsub` receiver with HMAC/raw-body verification, message-age checks,
  expected subscription ID, callback and broadcaster matching. Disabled by default.
  Gift recipient subscribe events are ignored; gift batches are counted once.
- Background token validation at startup and every 55 minutes (or sooner near
  expiry). A 401 triggers a serialized per-user refresh and identity recheck.
- Rotated refresh tokens are encrypted and saved before revalidation, so a
  temporary validation outage does not lose the rotated credential.
- Confirmed unusable authorization clears only that user's credentials and web
  sessions, preserves counters/queue, and rejects further incoming events for
  that user. Provider/network failures retry without deleting credentials.
- Compare-and-swap credential writes prevent stale refresh/revocation responses
  from overwriting a newer login. Auth health never exposes tokens or raw errors.

- Opt-in EventSub provisioning, complete paginated inventory reconciliation,
  per-account enable/stop controls, verification and revocation tracking. Only
  subscriptions matching this exact callback and broadcaster are managed.
- Missing scopes, verification pending, provider failures and rate limits are
  distinct from listening. Signed verification can arrive before create returns.

- Persisted, per-account FIFO challenge start/resume/pause; completion waits for
  manual next. Idempotent start command IDs prevent lost replies starting the next job.
- Exclusive 15-second camera leases and cumulative progress acknowledgments.
  Progress, owed deduction and lifetime completion update in one transaction;
  duplicate/reordered reports cannot increment twice. Owed never becomes negative.

- Authenticated `/camera` page: Webcam/Capture modes, camera selection, permission
  and model errors, hidden-window pause, pinned browser-side MediaPipe inference.
- Account/run-scoped local outbox saved before reporting; lost acknowledgments
  retry safely. Expired lease recovery requires explicit review before reapplying
  a saved cumulative total. Webcam mode never increments counters.

**Not implemented:** Donation platforms, free capture outside queued challenges,
stream-session totals,
account deletion, deployment and production operational hardening. The UI labels
these omissions explicitly. Camera code is covered by mocked integration tests;
real-device accuracy and OBS/Streamlabs window capture still require validation.
No camera/video upload is implemented. No existing local credentials or counters
are imported. Cloud browser sessions expire after 30 minutes in this milestone;
background token maintenance does not extend browser sessions. Sign out ends
the browser session, not the underlying Twitch grant. Revoking access on Twitch
is discovered during validation. Existing read-only overlay links remain valid.

## Local developer setup

1. Use the project's virtual environment and install `requirements-cloud.txt`.
2. Create a **separate confidential web application** in the Twitch developer
   console. The local app's public/device-flow Client ID is not the cloud client.
   Register `http://127.0.0.1:8090/auth/callback` exactly for development.
3. Supply environment variables listed in `.env.cloud.example`. This is a template;
   the server does **not** automatically load `.env` files. Do not paste secrets in
   screenshots, Git commits or issue reports. Use an environment/secret manager.
4. Generate a Fernet key once, store it securely separately from the database,
   and keep it stable across restarts. Losing it makes stored credentials unreadable.
5. Run `python -m squat_capture.cloud`, then open `http://127.0.0.1:8090`.
6. Sign in, change the manual owed total, generate an overlay URL and add it to
   OBS as a Browser Source. Resetting the URL revokes the previous one. Treat it
   as private: it grants read access but does not grant control access.

The listener binds **only to 127.0.0.1**. There is no fake-login HTTP endpoint.
The preview uses its own `.cloud-data/cloud.sqlite3`, ignored by Git. If you set
`CLOUD_DATABASE` elsewhere, protect that location and its backups yourself.

## Tests

```text
python -m unittest tests.python.test_cloud -v
python -m unittest discover -s tests/python -q
```

Install cloud dependencies before treating the first command as a cloud check.
Without cryptography, local-only test discovery skips the cloud tests.
Tests use fake OAuth responses and temporary databases; they do not authenticate
with Twitch or touch real local application data.

## Opt-in live EventSub (controlled developer testing only)

Keep `CLOUD_ENABLE_EVENTS=0` for local development. To test real webhooks, first
provide an HTTPS reverse proxy on public port 443 with the protections below;
set `CLOUD_DEV=0`, `CLOUD_ORIGIN=https://your-host` and update the registered Twitch
redirect to `https://your-host/auth/callback`. The Python listener stays loopback-only.
Set a stable random `CLOUD_EVENTSUB_SECRET` (32–100 ASCII characters) and explicitly
set `CLOUD_ENABLE_EVENTS=1`. Restart the service. Do not expose port 8080 or the
Python listener directly. No tunnel, proxy or public host is provisioned for you.

In the cloud account page:

1. Select **Authorize event permissions** to grant read access to redemptions,
   subscriptions and Bits. Default sign-in requests identity only.
2. Save your rules (reward ID remains manual). Select **Enable listening**.
3. Allow about a minute for reconciliation and Twitch callback verification.
   Only **Twitch events listening** means all requested subscriptions are enabled.
4. **Stop listening** immediately rejects incoming notifications; the worker
   deletes managed remote subscriptions on its next successful cycle. Signing
   out does not stop listening. Disabling the server flag blocks all callbacks
   but does not delete existing Twitch subscriptions: stop users first and wait
   for cleanup before disabling it.

The app token is obtained server-side and never returned to the browser. This
worker is single-instance only. Inventory failure never means “no subscriptions.”
Revoked subscriptions cannot be revived by a stale enabled inventory result.
For persistent pending/revoked status, inspect Twitch permissions; stop and wait
until cleanup completes before enabling again. Keep the callback secret stable:
rotating it requires deleting/recreating the remote subscriptions.

Bits use whole units per event (250 Bits / 100 = 2 units), without fractional carry.
New subscription events exclude gifts and do not cover resubs. Gift batches use
their total once. Optional donation platforms use manually supplied connection
credentials; provider OAuth onboarding is not implemented.

## Remaining work before inviting streamers

1. Validate token lifecycle with a real confidential Twitch test application.
   Automated tests use provider mocks only. The current maintenance loop is for
   a small single-instance preview; it is not a distributed job scheduler.
2. Validate the opt-in EventSub lifecycle against real Twitch callbacks, including
   reconnect, revocation and restart. Automated coverage uses signed fixtures and
   a fake provider only; no real subscriptions have been created by this work.
3. Validate `/camera` on real devices, test recovery/permissions and OBS window
   capture. Stream sessions and free capture are implemented. Inference
   currently runs at up to 12.5 FPS on the main thread; benchmark before considering
   a worker. See [camera usage and protocol](CLOUD_CAPTURE.md).
4. Reuse the full control UI only after its APIs are tenant-aware. Do not route
   cloud requests into the local singleton-based handler.
5. Review and exercise the supplied HTTPS proxy/service templates, backup restore,
   enrollment and deletion flow in a deployment security review. These are not
   deployed or verified on a production host. See [deployment reference](CLOUD_DEPLOY.md).
   The standard-library HTTP listener is not an Internet edge server.
6. Validate on two real Twitch accounts and OBS, then select a host and budget.
   SQLite is a single-instance preview choice, not a multi-replica database.

No hosting account, paid resource, DNS record or public URL is created by this
milestone. Do not call this a publicly launchable service yet.
The user has explicitly deferred deployment. The optional local Riot/League gate
has not been ported into the multi-user cloud service.

References: [Twitch code flow](https://dev.twitch.tv/docs/authentication/getting-tokens-oauth/)
and [token validation requirements](https://dev.twitch.tv/docs/authentication/validate-tokens/),
plus [EventSub subscription management](https://dev.twitch.tv/docs/eventsub/manage-subscriptions/).
