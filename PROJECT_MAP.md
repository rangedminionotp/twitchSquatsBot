# Project Map

这个项目现在不是一个大型前端 app，而是一个小型本地 Python 工具。它的核心流程是：

```text
Twitch channel point redeem
→ Twitch sends EventSub webhook to /eventsub
→ listener verifies the Twitch signature
→ listener checks reward title / reward ID
→ listener optionally runs the Riot gate
→ if allowed, listener publishes a squat job
→ browser popup receives the job through /popup-events
→ popup uses webcam pose detection to count squats
```

## 1. Twitch EventSub line

- `twitch_eventsub_listener.py`: the main server. It listens on port `8080`, receives Twitch EventSub webhook POSTs at `/eventsub`, verifies Twitch signatures, filters for the configured channel point reward, and creates squat popup jobs.
- `twitch_channel_points_check.py`: a small example/helper file for understanding how a Twitch channel point redemption payload is matched by reward title or reward ID. It is not the main running listener.
- `README.md`: setup instructions for Twitch app credentials, broadcaster token, app token, ngrok, EventSub subscriptions, and the listener command.

Key functions/classes in `twitch_eventsub_listener.py`:

- `EventSubHandler.do_POST()`: the main entry point when Twitch sends a webhook event.
- `is_valid_signature()`: checks that the request really came from Twitch using `TWITCH_EVENTSUB_SECRET`.
- `is_recent_message()`: rejects old webhook messages.
- `get_matching_redemption()`: checks that the redemption belongs to `nannersowo` and matches `TARGET_REWARD_TITLE` or `TARGET_REWARD_ID`.
- `summarize_redemption()`: creates readable JSON logs for incoming redemption events.

## 2. Riot gate line

- `script.py`: checks Riot public match history. It prints `true` if the configured Riot account was recently active, and `false` if not recently active or if the Riot check cannot run.
- `twitch_eventsub_listener.py`: calls `script.py` before allowing a squat popup job when `RIOT_CHECK_ENABLED=1`.

Key functions:

- `script.py main()`: resolves Riot account → fetches latest ranked match → checks how recently that match ended → prints `true` or `false`.
- `should_trigger_popup_from_riot_check()`: runs `RIOT_CHECK_COMMAND`, reads the output, and decides whether a redemption should trigger squats.

Important mental model:

- In this project, `false` from `script.py` means “Riot player is idle, allow the squat popup.”
- `true` means “Riot player was recently active, skip the squat popup.”
- This is not a real game lock yet. It is a gate based on recent Riot match activity.

## 3. Squat popup / UI state line

- `twitch_eventsub_listener.py`: serves the popup page at `/squat-popup` and exposes a local event stream at `/popup-events`.
- The popup HTML, CSS, and JavaScript are embedded inside the `POPUP_HTML` string in `twitch_eventsub_listener.py`.

Key server-side pieces:

- `RedeemPopupState`: stores the latest squat job and wakes any connected popup page.
- `RedeemPopupState.publish()`: turns a matched redemption into a popup job.
- `RedeemPopupState.wait_for_next()`: lets the browser wait for the next popup job.
- `EventSubHandler.serve_popup_page()`: returns the browser UI.
- `EventSubHandler.serve_popup_events()`: sends popup jobs to the browser using server-sent events.
- `extract_squat_target()`: reads the first number from the reward title, such as `10` in `do 10 squats`.

Key browser-side pieces inside `POPUP_HTML`:

- `connectEventStream()`: connects to `/popup-events` and waits for redeemed squat jobs.
- `activateJob(job)`: adds the redeemed squat count to the current queue.
- `startCamera()`: loads MediaPipe and starts the selected camera.
- `refreshCameraDevices()`: fills the camera dropdown.
- `openCamera(deviceId)`: starts or switches webcam devices.
- `renderLoop()`: sends video frames into MediaPipe pose detection.
- `onPoseResults(results)`: draws pose landmarks and calls squat detection.
- `detectSquatPhase(landmarks)`: reads hip/knee/ankle landmarks, estimates knee angle, and increments the squat count after a down → stand cycle.
- `resetCounter()`: clears the active squat count and UI state.

## Current actual flow

```text
Viewer redeems channel point reward
→ Twitch POSTs to /eventsub
→ EventSubHandler.do_POST() runs
→ request signature and timestamp are verified
→ incoming redemption is logged
→ get_matching_redemption() checks broadcaster + reward
→ should_trigger_popup_from_riot_check() runs script.py
→ if Riot gate allows it, POPUP_STATE.publish() creates a popup job
→ maybe_open_popup() tries to open the popup URL
→ browser popup receives the job from /popup-events
→ activateJob() adds squats to the target count
→ camera + MediaPipe detect body landmarks
→ detectSquatPhase() counts reps when your knee angle goes down enough, then back up enough
```

## What does not exist yet

These are ideas from the larger app plan, but they are not real modules in this repo yet:

- No `lockManager` file.
- No real game overlay.
- No OS-level game blocking.
- No React dashboard.
- No separate Twitch OAuth module.
- No persistent database.

Right now the project is best understood as:

```text
Twitch webhook listener + Riot recent-activity gate + browser squat counter popup
```

## Useful logs to watch

When testing a redeem, these logs tell the story:

- `{"incoming_redemption": ...}` means Twitch delivered an EventSub notification.
- `{"matched": false, ...}` means the reward did not match your configured title or ID.
- `{"riot_gate": {"allowed": true, "reason": "riot_idle", ...}}` means the Riot check allowed the popup.
- `{"riot_gate": {"allowed": false, ...}}` means the Riot check blocked the popup.
- `{"popup_job": ...}` means the popup queue received the squat job.
- `popup_open_error` means the server tried to auto-open the popup but the OS command failed. The bot can still work if you manually open `http://127.0.0.1:8080/squat-popup`.

## Good next cleanup targets

1. Move the embedded popup HTML/JS/CSS out of `twitch_eventsub_listener.py` into separate files.
2. Rename `script.py` to something clearer, such as `riot_recent_activity_check.py`.
3. Change reward matching to use `TARGET_REWARD_ID` so title typos do not break the bot.
4. Fix `maybe_open_popup()` for WSL/Windows by trying `explorer.exe` before macOS `open`.
5. Add a tiny manual test route or test payload so you can trigger a squat job without redeeming on Twitch every time.
