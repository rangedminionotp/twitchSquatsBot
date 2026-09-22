# Project map

## Current folders

- `squat_capture/`: local Python package. `__main__.py` calls the server entry point.
- `static/control/`, `static/capture/`, `static/overlay/`: the three browser surfaces.
- `tests/python/`: backend, storage and HTTP/static-resource regression tests.
- `tests/javascript/`: readiness and camera outbox regression tests.
- `scripts/`: Windows and WSL launchers, which resolve the project root.
- `examples/`: the standalone Channel Points matching example.
- `docs/`: developer documentation. See [FRONTEND.md](FRONTEND.md).
- `README.md`, `README.zh-CN.md`, `requirements.txt`: root-level setup and dependency files.

## Backend responsibilities

- `twitch_eventsub_listener.py`: HTTP server, JSON APIs, event handling and challenge coordination.
- `twitch_eventsub_websocket.py`: Twitch authorization, EventSub and stream-session monitoring.
- `support_events.py`: support-event rules and Streamlabs / StreamElements connections.
- `camera_overlay.py`: camera ownership, heartbeats and bounded telemetry.
- `control_panel.py`: page loading, public asset allowlist and legacy refresh-template rendering.
- `app_config.py`: local configuration.
- `app_stats.py`: persistent counters, queue and stream sessions.
- `script.py`: optional Riot checks.
- `startup_check.py`: dependency and data-directory checks.

All modules above are in `squat_capture/`. Their names were retained to keep this
a relocation, not a simultaneous business-logic rewrite.

## Runtime flow

Twitch events enter through EventSub WebSocket (or the optional legacy webhook).
Selected redemptions add owed and queue challenges; subs and donations add owed
without joining the challenge queue. Browser pose detection reports reps to the
local API. Persistent stats and queue state feed the control panel and OBS overlay.

Camera frames are processed in the browser. Static route configuration contains
no credentials. Existing browser/OBS URLs and local data locations are unchanged.

## Running and testing

Run these from the repository root:

```sh
bash scripts/start_wsl.sh
# Windows PowerShell: .\scripts\start_windows.ps1
# With dependencies already installed:
python -m squat_capture
python -m unittest discover -s tests/python -q
node tests/javascript/test_control_state.mjs
node tests/javascript/test_camera_outbox.cjs
```

The launchers keep using the root `.venv`. Personal settings/counters remain in
the configured data directory, not in the Python package. The next architectural
step is extracting API routing and challenge services from the listener.
