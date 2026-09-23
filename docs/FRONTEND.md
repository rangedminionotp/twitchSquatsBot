# Control-panel frontend

The control panel is a native HTML/CSS/JavaScript app. No npm install, bundler,
frontend framework or new Python dependency is required. Start the app with the
existing launcher and visit `/control`; do not open `index.html` as a local file.

## Files

- `static/control/index.html`: control-panel markup and module entry point.
- `static/control/css/tokens.css`: shared colors and visual tokens.
- `static/control/css/components.css`: baseline controls and cards.
- `static/control/css/layout.css`: live-console composition and responsive overrides.
- `static/control/js/app.js`: composition and feature initialization order.
- `static/control/js/api.js`: HTTP transport, timeout handling and snapshot publication.
- `static/control/js/state.js`: observable snapshots and pure readiness rules.
- `static/control/js/render.js`: shared DOM helpers and live-console composition.
- `static/control/js/features/`: setup, Twitch, rewards, queue, camera, activity,
  progress, support rules, optional League checks and status rendering.
- `squat_capture/control_panel.py`: loads the HTML relative to the repository and explicitly
  allowlists public assets. Configuration and arbitrary filesystem paths are
  never served through `/static/`.

Feature initializers receive a small context for cross-feature operations
(camera mode changes, reward refresh and initial League settings). Feature-local
form state stays in its module; readiness uses API snapshots, not DOM text.
Subscriptions and donations still add owed only; they do not enqueue challenges.

## Readiness is not just authentication

First-run accounts see Twitch onboarding instead of the live console. The header
always exposes Twitch status and account access; overall capture readiness stays
in the live card. Saved credentials/identity are distinguished from the live
socket, so connection interruptions retain counters and queue controls with a
recovery banner. Starting a queued challenge or saving a reward while disconnected
opens a connection-required dialog. Pausing and local camera checks remain available.

`features/onboarding.js` owns this presentation and delegates authorization to
the existing Twitch handler. Loading/failed status requests are not treated as a
new account. Permission help describes the actual conditional read scopes; access
revocation is done in Twitch settings, not through a nonexistent in-app disconnect.

The top badge combines fresh settings, listener diagnostics, camera telemetry
and queue state. It never treats a login alone as Ready. Selected event sources
must be listening; camera capture must have a working model, detected body and
working local storage, with no pending rep batches. A paused queue remains paused
until the user starts it. Optional League checks still run on the server when
starting a challenge; the readiness badge is not a League eligibility check.

Missing snapshots show Checking; failed requests show Status unavailable; data
older than 25 seconds revokes Ready. Camera errors are transmitted only as a
small allowlist of codes, not arbitrary device/error details. Model readiness
requires an actual pose-result callback, not just construction of the detector.

OBS setup is a manual user confirmation. The app cannot infer that an OBS source
is visible just because an overlay URL exists. This refactor does not change the
capture or overlay URLs. Their HTML, styles and scripts now live in sibling\n`static/capture/` and `static/overlay/` directories. `/capture/` opens the manual\nWebcam/Capture window; `/squat-popup` retains the legacy popup behavior. Both\n`/control/` and `/overlay/` are supported, alongside the existing URLs.

## Checks

```sh
python -m unittest discover -s tests/python -q
node tests/javascript/test_control_state.mjs
node tests/javascript/test_camera_outbox.cjs
```

Python covers static routing, MIME types, path boundaries and existing backend
behavior. The Node tests cover pure readiness rules without a browser or network.
`static/package.json` only tells Node that these test imports are ES modules;
it is not a build pipeline and is not served publicly.

For UI testing, use an isolated data directory (`SQUAT_CAPTURE_DATA_DIR`) and a
different port. Verify incomplete/completed setup, queue states, Settings links,
counter editing, safe rule preview and narrow layouts without changing live data.
Real camera permissions and Twitch provider delivery still require a manual
end-to-end check. Restart after changing Python or the HTML template; CSS and JS
assets revalidate on refresh.

## Page assets and migration boundary

- `static/control/`: existing modular control panel.
- `static/capture/`: camera/pose page, pose and counting script, camera-window CSS.
- `static/overlay/`: main OBS overlay plus refresh/chroma-key variants.
- `static/shared/config.js`: loads public routes from `/api/web-config`; no credentials.

The asset allowlist and resolved-root checks remain in place. Old `/static/js/`
and `/static/css/` URLs map to the relocated control files. The refresh overlay
keeps its server-provided first-frame snapshot using an external HTML template;
its CSS and polling script are external too. Viewer text is still HTML-escaped.

The backend now lives in the local `squat_capture/` Python package. Run
`python -m squat_capture` from the project root, or use the launchers in `scripts/`.
No package installation or new dependency is required. API routing and queue-service
extraction are still separate future refactors; this move preserves business logic.
# Desktop console layout

The control page keeps its existing form elements and API handlers. `render.js`
composes them into an accessible section sidebar and focused workspaces. Live
control shows challenges and camera controls; Setup, Rewards, Integrations,
Activity and Settings each show only their related panels. Navigation updates
the page heading, breadcrumb, document title and selected item, then focuses
the heading immediately. Hidden panels keep their existing controls and polling.
Cross-feature repair/settings links reveal the correct workspace before focusing
their target; they do not change camera modes, start challenges or authorize an
account just by changing sections.

`layout.css` uses a full sidebar above 1199px, an icon rail at intermediate
widths, and a single-column workspace with a section selector at 560px and below.
The onboarding card sits outside the dashboard grid so first-run controls stay
hidden without hiding the authorization entry point.

The setup strip uses the same settings and listener checks as Quick setup.
Camera framing and OBS are explicitly **user confirmations**, not inferred
device health. Completion collapses the strip; Manage setup opens the existing
checklist. Camera presentation distinguishes closed, off, denied, loading,
framing and ready states. It never opens a second camera stream in the console.
The challenge progress bar represents the first queued challenge's done/target,
not a ratio between overall owed and stream-completed counters.

Additional presentation tests: `node tests/javascript/test_control_workspace.mjs`.
