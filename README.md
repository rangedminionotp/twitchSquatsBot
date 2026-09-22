# Squat Capture

Developer notes: [Frontend structure and readiness rules](docs/FRONTEND.md).

A local Twitch streaming tool that turns Channel Points redemptions into a squat
queue and tracks the reps you owe and complete. Keep your normal webcam view,
then switch to pose-based counting when you are ready.

**Early-access / source-run app:** there is no packaged installer yet. Automated
tests do not guarantee camera compatibility or end-to-end delivery from every
provider. Try it privately before relying on it during a stream.

[中文使用说明](README.zh-CN.md)

## Features

- Twitch sign-in and separate readiness indicators for Channel Points, subs/gifts and Bits.
- Persistent FIFO redemption queue: start, pause and resume manually.
- Configurable Sub, Bits, Streamlabs and StreamElements additions to overall owed.
- Camera Overlay with Webcam and Capture modes, using the same video stream.
- Separate OBS/Streamlabs counter overlay.
- Overall owed, per-Twitch-broadcast completed, and internally retained lifetime reps.
- Recent counter history, safe rule previews, setup guide and startup checks.
- Browser-local pending rep recovery and duplicate-report protection.
- Optional League account checks before starting the queue.

## 1. Download and start

You need Python 3, internet access for installation/Twitch/pose-model loading,
a webcam, a regular Chrome or Edge window, and OBS or Streamlabs Desktop.
Channel Points features require access to Channel Points rewards on your channel.

Clone this repository or download and extract its ZIP, then open a terminal in
the project folder. Choose **one** runtime below; Windows and WSL have separate
home directories and therefore separate default app data.

### Windows — PowerShell

Install Python 3 first, then run:

```powershell
.\scripts\start_windows.ps1
```

If PowerShell blocks scripts, an alternative that does not change execution policy is:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m squat_capture.startup_check --repair
.\.venv\Scripts\python.exe -m squat_capture
```

Run the final command only after startup checks pass. If `py` is unavailable,
use your installed `python` command for the first step.

### WSL — Bash

Inside WSL, install Linux Python and venv support if needed:

```bash
sudo apt update
sudo apt install python3 python3-venv
bash scripts/start_wsl.sh
```

Do not run the PowerShell launcher inside Bash. Open the app in your **Windows**
browser, not inside a Linux desktop.

### What startup does

The launcher creates a project-local `.venv`, checks dependencies on every launch,
and attempts to repair missing/incompatible packages and pip. Installation requires
network access. It also checks data-directory write access. Port conflicts produce
an error; the app does not kill other processes or silently change ports.

Keep the terminal running. Open:

| Page | URL | Purpose |
|---|---|---|
| Control panel | http://127.0.0.1:8080/control | Settings, queue, modes and diagnostics |
| Camera window | http://127.0.0.1:8080/camera-overlay | Regular browser window captured by Streamlabs |
| Counter overlay | http://127.0.0.1:8080/overlay | OBS/Streamlabs Browser Source |

If you override the `PORT` environment variable, update all three URLs.
Use the same hostname and port consistently for browser pending-rep recovery.

## 2. First-time setup

1. Open **Quick setup** on the control panel.
2. Click **Connect with Twitch** and authorize your broadcaster account.
   The app includes a public Client ID; normal users do not enter a client secret.
3. Under **Reward**, select the Channel Points reward and click **Save reward**.
   Use a clear name such as `10 squats`: the **first number in its title** becomes
   the target. Without a number, the default is 10 (configurable via
   `DEFAULT_SQUAT_TARGET`). Avoid putting unrelated numbers first.
4. Optionally enable sources in **Auto-add squats**, set their rates and save.
   After first enabling Sub or Bits, reconnect Twitch for the additional permissions.
5. Check **Connection health**. Successful login alone does not mean listeners
   are ready. Enabled sources should report that they are listening.
6. Set up the camera and OBS as described below. The guide's camera and OBS
   checkboxes are **your confirmation**, not automatic detection.

For an existing squat debt, use **Your progress → Adjust totals → Set owed**.
This replaces the total; it is not an “add this many” button.

## 3. Camera and Streamlabs/OBS

**Use two different sources. A camera window and a counter card are not the same thing.**

| What you want on stream | Source type | What to select |
|---|---|---|
| Webcam / squat recognition video | **Window Capture** | Chrome/Edge window titled Squat Capture · Camera Overlay |
| Owed / Completed card | **Browser Source** | `http://127.0.0.1:8080/overlay` |

### Camera window

1. Release the webcam from existing Streamlabs/OBS camera sources and other apps.
   Hiding a source may not release its device; deactivate it or close the competing app.
2. Open the Camera Overlay URL in a **separate Chrome/Edge window**.
   Do not use an embedded chat browser or add this URL as a Browser Source.
3. Click **Start Camera**, allow camera permission, and choose your device.
   Verify video in the browser before configuring window capture.
4. Add a **Window Capture** source in Streamlabs/OBS and select that browser window.
   Crop browser chrome if needed. Keep unrelated/private tabs in another window.
5. Press **H** in the camera page to hide or show its setup controls.
   Keep this window open and not minimized.

No virtual camera is required. Open only one Camera Overlay and close the older
`/squat-popup` page. One overlay page owns capture at a time; after closing it,
wait about eight seconds before starting the camera on another page.

In the control panel:

- **Webcam**: video only; no pose counting. Also pauses an active queue.
- **Capture squats**: free exercise; counts reps but does **not** start a paused queue.
- **Start / resume queue**: switches to Capture and works through queued challenges.

Keep both shoulders and at least one complete leg visible. Try a side or slight
angle. Current knee-angle thresholds are fixed, not personalized calibration.
Pose recognition is approximate; check a few reps manually before going live.

### Counter card

Add `/overlay` as a Browser Source. A starting size of **460 × 440** gives the card
room to expand. This source never needs camera permission. The control panel queue
is currently the detailed view of queued challenge progress; do not assume every
queue transition is shown on the older challenge section of the counter overlay.

## 4. How counts and the queue work

| Event | Overall Owed | Completed this stream | Challenge queue |
|---|---|---|---|
| Matching redemption for N reps | +N, once per redemption ID | Unchanged | Add N-rep challenge |
| Enabled Sub/Bits/tip event | Add configured amount | Unchanged | Unchanged |
| One rep during a running queue | −1, minimum zero | +1 when Twitch is known live | Advance FIFO by one |
| One rep in free Capture | −1, minimum zero | +1 when Twitch is known live | Unchanged |
| New Twitch broadcast detected | Retained | Reset to zero | Retained |

Queue progress is **part of the same debt**, not a second deduction.

- Redemptions queue while the app is running, even with the camera closed.
- Nothing automatically opens a camera, starts a challenge or soft-locks your game.
- **Start / resume queue** starts FIFO processing; **Pause · Webcam** preserves progress.
- Restarting the server retains the queue but starts it paused.
- When the queue clears, Capture stays on for free exercise. Choose Webcam to stop counting.
- Free exercise can lower owed without clearing a paused queue.
- Twitch reward fulfillment/cancellation/refunds are not automated. There are no
  queue cancellation, reorder or undo controls yet.

Completed follows the Twitch broadcast ID, checked approximately every 15 seconds.
The same broadcast survives app restarts; offline display retains the last stream.
When Twitch is offline or unavailable, reps still reduce owed and increment the
internal lifetime total, but not stream Completed. Late uploads use server state
at receipt, not historical stream attribution.

## 5. Sub, Bits and donation rules

All sources are optional and initially disabled. Save each source's rate before testing.

- **Twitch subs:** new and gifted subscriptions; a gift bundle counts each gift once.
  Automatic renewals / resub chat messages are not counted.
- **Bits:** whole configured units per event. For example, 100 Bits → 3 reps means
  250 Bits adds 6, not 7.5.
- **Streamlabs / StreamElements:** separate amount, currency and rep settings.
  USD 2.50 → 4 reps means USD 5.01 adds 8. Remainders are discarded per event.
  Other currencies are ignored; there is no currency conversion.

Streamlabs needs a Socket API token. StreamElements needs a channel ID and JWT.
These go in **Connection settings**, not in source code. Blank token inputs keep
saved credentials. Provider setup references:

- [Streamlabs Socket API](https://dev.streamlabs.com/v1/docs/socket-api)
- [StreamElements WebSockets](https://docs.streamelements.com/websockets)

The app listens live; it does not backfill events missed while offline.
Refunds do not automatically reverse owed. Do not route the same donation through
both providers. Provider-generated test alerts may look real and affect counters.

**Safe rule test** is different: it only previews the saved conversion rule and
does not send a payment, change counters, or prove that live events are arriving.

## 6. Before and after each stream

Before going live:

- Start the server and inspect enabled listeners in **Connection health**.
- Confirm video, model readiness and actual mode under **Camera Overlay**.
- Remember that actual mode can differ from the requested mode during loading/errors.
- Check Owed, selected reward and support rates.
- Run **Safe rule test**; separately test recognition privately (real reps change counters).
- Check your Streamlabs/OBS preview and hide camera setup controls.

When finishing:

- Pause the queue or select Webcam.
- Press H to check the camera page's sync status; wait for **All reps synced**.
- Close the camera window, then stop the server with Ctrl+C.
- A KeyboardInterrupt after Ctrl+C is normal.

## 7. Data, recovery and privacy

Default app data directory:

- Native Windows: `%USERPROFILE%\.squat-capture`
- WSL: `~/.squat-capture` inside the Linux user's home
- Override: `SQUAT_CAPTURE_DATA_DIR`

`config.json` contains settings and credentials; **keep it private**.
`stats.json` contains totals, queue, deduplication records and recent counter activity.

For a manual backup, wait for sync, stop the server, and copy these files to a
private location. Restore with the server stopped. No automatic backup/restore UI
exists yet. Restoring an old stats file also restores old deduplication history,
so do not treat rollback as a harmless “undo”.

Camera Overlay saves pending reports in that browser profile's localStorage.
Reopen the **same origin** (scheme + hostname + port) to retry. Switching
`127.0.0.1` to `localhost`, changing ports/profiles, clearing site data or closing
a private-browsing session can prevent recovery. Storage/connection problems pause
recognition; existing pending reports remain eligible for retry.

Video is processed in the browser; this app does not upload webcam frames to its
Python server. Model files load from external CDNs. OBS/Streamlabs determines what
you actually broadcast. Tokens are stored locally, not in a credential vault.

**Do not expose this server publicly.** It currently binds to `0.0.0.0` and its
control APIs are unauthenticated. Use a trusted local setup and firewall; do not
port-forward or tunnel it. Normal WebSocket operation needs no public URL/ngrok.
Legacy webhook code is not the recommended distribution setup.

## 8. Troubleshooting

| Symptom | Check / action |
|---|---|
| Login succeeds but subs do not add | Check the specific listener, saved enable switch and rate. Reconnect Twitch after enabling new permissions. Look at Recent activity. |
| “Missing dependencies” | Stop and rerun the launcher; it checks existing environments too. |
| “No module named pip” | In the matching venv run `python -m ensurepip --upgrade`, then rerun the launcher. WSL may need its Python-version-matched venv package. |
| “missing client secret” / authorization failure | Reconnect Twitch. If it recurs, application registration / token refresh needs investigation; do not paste a secret into chat or ship it with the app. |
| Port 8080 occupied | Check whether an old instance is running. Stop that instance intentionally; do not repeatedly launch duplicates. |
| Browser video is black | Click Start Camera and check permission/device selection. Release other camera users first. Read the camera page error. |
| Chrome video works, Streamlabs is black | Verify **Window Capture**, selected Chrome/Edge window and that it is not minimized. An old Browser Source loads a separate page. |
| “Another camera page owns capture” | Close duplicate Camera Overlay pages, wait about eight seconds, then Start Camera in the remaining one. |
| Reps not counting | Check actual Capture mode, model readiness, full-body visibility and local saving. Check connection and CDN/model errors. |
| Completed stays unchanged | Is Twitch detected live? Offline/unknown reps do not increase stream Completed. |
| Queue not advancing | Use Start / resume queue, not free Capture. Check optional League gate and camera readiness. |
| Waiting to sync | Keep/reopen the same browser origin, restore the server connection and wait. Do not clear website data. |
| Rules test passes but no real event arrives | Preview tests arithmetic only. Verify listener status and a genuine event; avoid spending money solely to test. |

**Recent activity** retains the last 100 counter records. Received-support-event
diagnostics retain the last 30 decisions in memory and reset on restart. Neither
is a complete historical event archive. Review logs/screenshots for sensitive
information before sharing them.

### Optional League check

Leave it off if not needed. When enabled, configure the Riot key, account IDs and
regions in the control panel, then use the account test. It gates **manual queue
start**, not redemption intake or support accrual. It is not continuous enforcement
during a challenge. API errors can block starting; this is not a guarantee of
perfect game-state detection. Streamer Mode/private-account restrictions can limit
visibility. Never commit a Riot key.

## 9. Current limits and next improvements

This is suitable for guided private testing, not yet a polished public release.
There is no installer, auto-update, camera calibration wizard, queue undo/cancel UI,
automatic refund handling or offline event-history sync. Renewals are excluded.
The legacy `/squat-popup` workflow is not the main workflow described here.

Next priorities: camera calibration, explicit queue corrections, automatic private
backups, control API protection, and a Windows distribution package. Real camera,
long-running stream, reconnect and payment-provider tests remain necessary.

## Development checks

From the project environment:

```bash
python -m unittest discover -s tests/python -p "test_*.py"
node tests/javascript/test_camera_outbox.cjs
```

The second command requires Node.js and uses mocked browser storage/network, not a
real camera. Passing these tests does not validate Streamlabs window capture or
live provider credentials.
