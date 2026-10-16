# Small invite-only cloud beta: deployment runbook

No infrastructure has been created. This is a template, not a verified production
deployment. Local port 8080 must never be exposed. Keep one Python process/instance.

## Budget and prerequisites

User budget: USD 10/month including recurring extras. DigitalOcean lists a regular
1 GiB / 1 vCPU Droplet at USD 6/month as checked 2026-10-11. That is a candidate for
a small allowlisted beta, not a capacity guarantee. Taxes, domain registration,
off-server backup storage and transfer overages are extra. Check the final quote
before purchasing; do not add paid databases, load balancers or managed services.
[Official pricing](https://www.digitalocean.com/pricing/droplets).

Required human choices: hosting account and region, a hostname you control, final
cost approval, an operator for OS/security updates and a confidential Twitch app.
Use a domain/subdomain with HTTPS, not a public tunnel to the existing local app.

## Server preparation (operator checklist)

1. Provision a supported Linux host with Python/venv, nginx and certificate tooling.
   Configure SSH keys and a firewall allowing SSH only from your admin IP and
   HTTP/HTTPS publicly. Port 8090 is loopback only; do not open it in the firewall.
2. Create an unprivileged `squatcapture` service user. Place reviewed source under
   `/opt/squat-capture`, owned by the operator, not writable by the service user.
   Create a virtual environment there; install `requirements-cloud.txt`.
3. Create `/var/lib/squat-capture` owned by `squatcapture`, mode 700. Store secrets in
   `/etc/squat-capture/cloud.env`, root-owned mode 600. Use `.env.cloud.example` as
   a template, with `CLOUD_DATABASE=/var/lib/squat-capture/cloud.sqlite3`,
   `CLOUD_DEV=0`, and `CLOUD_ORIGIN=https://YOUR_HOST` (no trailing slash).
4. Generate and retain a stable Fernet key separately from backups. Supply the
   confidential Twitch client ID/secret and a random EventSub secret. Never place
   secrets in Git, shell history, browser screenshots or support tickets.
5. Set `CLOUD_ALLOWED_USERS` to a comma-separated list of approved **numeric Twitch
   user IDs**. Start with two testers. Empty blocks production login. There is no
   open registration switch: add users deliberately while watching capacity.
6. Register exactly `https://YOUR_HOST/auth/callback` in your Twitch web application.
   Start with `CLOUD_ENABLE_EVENTS=0` until HTTPS and login checks pass.
7. Point DNS to the host and obtain a valid TLS certificate for it. Replace every
   `example.invalid` in `deploy/cloud/nginx.conf.example` and certificate paths.
   Validate the config with `nginx -t` before enabling it. This repo does not obtain
   or install certificates; configure and test automated renewal yourself.
8. Install `deploy/cloud/squat-capture.service` as a systemd unit, reload systemd,
   then start the service. Check `/health` through HTTPS, server restart recovery,
   secure cookies, unauthorized API rejection, and tenant isolation.
9. Enable EventSub, restart and authorize event scopes from each tester's account.
   Save rules, enable listening and wait for verification. Confirm provider events
   rather than relying on mocked tests. Stop listening before planned teardown.

nginx terminates TLS, limits requests and strips forwarded headers. Python limits
concurrent request threads and sets socket timeouts; application writes and login
attempts are throttled. These measures do not substitute for a deployment review.
Default URL/error logs are suppressed to avoid credential and overlay-link leakage;
monitor health, service restarts, resource usage and coarse error counts instead.

## Backup, restore and deletion

- Back up SQLite with its backup API (not by copying a live partially-written file).
  Use `python -m squat_capture.cloud.backup /absolute/new-backup.sqlite3` with the
  service environment supplied. The command refuses to overwrite an existing file.
- Backups contain personal records and encrypted tokens. Encrypt off-host backups,
  restrict access and adopt a documented short retention (for example seven days).
  The operator must implement retention/off-site copies; they are not automated here.
- Keep the Fernet key separately backed up. Without it, stored tokens are unreadable.
- Test restore to an isolated copy with events/donation connections disabled and no
  public ingress. Use a new path, check SQLite integrity and counters before promotion.
  A production restore must happen while the service is stopped. Preserve the current
  database for rollback; do not overwrite it without an explicit operator decision.
- Users can delete live account data after Twitch subscriptions are cleaned up.
  Backups may retain that data until expiry. A restored old backup may resurrect
  deleted accounts, sessions or overlay links: reconcile deletions and invalidate
  sessions/overlay links before exposing a restored service. Provider grants are
  revoked separately through Twitch/Streamlabs/StreamElements account settings.

## Release gate: not yet passed

- Real Twitch OAuth refresh/revocation and signed EventSub callbacks.
- Two-account isolation and real sub/gift/Bits/redemption events.
- Real donation sockets, currency rules, disconnect/reconnect and duplicates.
- Browser model/CSP, real webcam accuracy, OBS/Streamlabs window capture, long streams.
- HTTPS renewal, reboot, backup/restore, deletion and budget/resource alerts.
- Optional League integration still belongs to the local version, not this cloud beta.

Do not advertise this as fully production-ready until these checks are recorded.
