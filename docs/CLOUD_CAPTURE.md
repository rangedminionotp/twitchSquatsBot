# Cloud capture protocol (development only)

The cloud challenge backend and a separate `/camera` frontend are implemented.
The local app and its capture protocol remain unchanged. No camera/video is uploaded.

All endpoints below require the cloud login cookie, exact Origin, JSON content type
and session CSRF header. User IDs never come from request bodies. Invalid payloads
return 400; wrong owner, paused/expired lease or unavailable challenge returns 409.

| Endpoint | Exact JSON fields | Behavior |
| --- | --- | --- |
| POST /api/challenge/start | request_id | Start oldest pending job or resume current; retry same ID for same command. |
| POST /api/challenge/pause | run_id | Pause only that run, invalidate its camera lease. |
| POST /api/capture/claim | run_id, page_id | Acquire/renew exclusive 15-second lease; returns lease and accepted baseline. |
| POST /api/capture/progress | run_id, lease, count | Cumulative count for this run, not an increment; returns accepted count and run state. |

`GET /api/me` includes the active/paused challenge, progress and camera lease status,
but never its lease credential. Public overlays still expose only owed/lifetime.
Start does not acquire a camera or start inference. A prepared job can have no camera.
Authenticated `GET /api/capture/run?id=...` retrieves an owned run (including a
completed one) for recovery, without exposing the lease token.

## Try the cloud camera

1. Start the separate cloud preview and sign in. The local port 8080 UI is unchanged.
2. On the cloud dashboard, start a queued redemption challenge, then **Open camera window**.
3. Release the physical webcam in Streamlabs/OBS. In a normal Chrome/Edge window,
   click **Start camera**, granting browser permission. Webcam mode does not count.
4. Select **Capture challenge** to load the pose model and acquire the camera lease.
   Show both shoulders and a full leg. Stand tall first (155 degrees), squat to
   120 degrees or lower, then stand again. Each phase must persist at least 180 ms.
   Thresholds are heuristic counters, not fitness or medical form assessment.
5. Use Streamlabs/OBS **Window Capture** on this window. Press H to hide controls;
   H or the top-right reveal control restores them. Keep the window visible: hiding
   it pauses counting. Do not open it as an OBS Browser Source that cannot grant
   camera permission. No virtual camera is needed for the window-capture workflow.
6. **Webcam only** stops counting without switching physical cameras. **Camera off**
   releases the device. Neither discards pending reps. Completion waits for manual next.

Only metadata/cumulative counts go to this server. First Capture downloads pinned
MediaPipe Tasks Vision JS/WASM and Google's lite pose model. External CDN/model
requests reveal ordinary connection metadata to those hosts, not camera frames.
The camera document alone allows those assets and WebAssembly in its CSP; the
dashboard/overlay retain the restrictive policy. Webcam-only mode does not load a model.
This uses the [MediaPipe Web API](https://ai.google.dev/edge/mediapipe/solutions/vision/pose_landmarker/web_js).

## Recovery behavior

The camera persists each rep before sending it and waits for acknowledgment before
counting another. On network failure it switches to Webcam, preserving the report.
Automatic retries use the original lease. Reloading recovers only the current
account's saved reports; switching accounts stops the camera and requires reload.

If the lease expired, use **Review and apply saved total**: it shows server and saved
totals, requires confirmation and claims a new lease for the same active run. Resume
a paused run in the dashboard first. This is an absolute total, not an increment;
review carefully if another camera has counted since the outage. You may instead
explicitly discard the unconfirmed report (accepted server reps remain unchanged).
No inference is performed while a saved report is unresolved. Storage failure also
stops counting. Do not clear site data to solve a synchronization error.

## Client integration contract

- Generate a new random request ID per intentional start/resume; retain it across
  retries. A repeated command cannot start another queued job after completion.
- Keep a random page ID per camera page. Renew the lease before expiry, stop
  detection when renewal fails, and never assume the browser timer ran on time.
- On successful claim, initialize from server `accepted`; report a monotonically
  increasing cumulative total. Do not reset the total when pausing or reloading.
- Persist an account/run-scoped outbox before sending progress. Do not send another
  account's entries after login changes.
- A duplicate or older count is acknowledged without mutation, even after pause
  or completion, so lost successful responses can be recovered. New increments
  require an active, unexpired matching lease. A report cannot spill into the next job.
- Pause invalidates the lease. After expiry, takeover or pause, unsent increments
  are **not** automatically accepted: reconcile accepted progress first. Preserve
  pending local data for the explicit recovery flow; never silently replay it into
  a new lease.
- Completion does not automatically start the next challenge. Subs/gifts/Bits
  increase overall owed only. Prepare a free set (1–500 reps) in the control panel
  to work off debt without a redemption. End that set before switching to the queue.

Leases prevent accidental double counting from concurrent pages; they do not prove
that the broadcaster actually exercised. Authenticated clients can submit counts.
The server bounds totals and enforces ownership, not anti-cheat or medical accuracy.
Cloud browser sessions expire after 12 hours; reauthentication is required before
further mutations. Stream completions are attributed only while the latest Twitch
stream observation is live and less than 120 seconds old; lifetime totals always
retain accepted reps.

Tests use fake camera clients, browser/media/model objects, clock and events against
temporary SQLite databases. No real camera, Twitch account, or production data is used.
Real pose accuracy, browser CSP/model runtime and OBS capture are not confirmed by
these tests. Run the frontend tests with:

```text
node tests/javascript/test_cloud_capture.mjs
node --experimental-vm-modules tests/javascript/test_cloud_camera.mjs
```
