"""Control page and explicitly allowlisted static assets."""
from pathlib import Path
import re

STATIC_ROOT = Path(__file__).resolve().parent.parent / "static"
CONTROL_HTML = (STATIC_ROOT / "control/index.html").read_text(encoding="utf-8")
POPUP_HTML = (STATIC_ROOT / "capture/index.html").read_text(encoding="utf-8")
OVERLAY_HTML = (STATIC_ROOT / "overlay/index.html").read_text(encoding="utf-8")
REFRESH_HTML = (STATIC_ROOT / "overlay/refresh.html").read_text(encoding="utf-8")


def render_refresh_page(values):
    """Legacy first-frame snapshot; markup, CSS and scripts live in web files."""
    return re.sub(r"%([A-Za-z_][A-Za-z_()]*)%", lambda match: str(values.get(match[1], match[0])), REFRESH_HTML)


ASSETS = {
    "/static/capture/capture.css": ("capture/capture.css", "text/css; charset=utf-8"),
    "/static/capture/capture.js": ("capture/capture.js", "text/javascript; charset=utf-8"),
    "/static/overlay/overlay.css": ("overlay/overlay.css", "text/css; charset=utf-8"),
    "/static/overlay/overlay.js": ("overlay/overlay.js", "text/javascript; charset=utf-8"),
    "/static/overlay/refresh.css": ("overlay/refresh.css", "text/css; charset=utf-8"),
    "/static/overlay/refresh.js": ("overlay/refresh.js", "text/javascript; charset=utf-8"),
    "/static/capture/camera.css": ("capture/camera.css", "text/css; charset=utf-8"),
    "/static/shared/config.js": ("shared/config.js", "text/javascript; charset=utf-8"),
    '/static/js/state.js': ('control/js/state.js', 'text/javascript; charset=utf-8'),
    '/static/js/features/status.js': ('control/js/features/status.js', 'text/javascript; charset=utf-8'),
    "/static/css/tokens.css": ("control/css/tokens.css", "text/css; charset=utf-8"),
    "/static/css/components.css": ("control/css/components.css", "text/css; charset=utf-8"),
    "/static/css/layout.css": ("control/css/layout.css", "text/css; charset=utf-8"),
    "/static/js/api.js": ("control/js/api.js", "text/javascript; charset=utf-8"),
    "/static/js/render.js": ("control/js/render.js", "text/javascript; charset=utf-8"),
    "/static/js/features/challenge.js": ("control/js/features/challenge.js", "text/javascript; charset=utf-8"),
    "/static/js/features/camera.js": ("control/js/features/camera.js", "text/javascript; charset=utf-8"),
    "/static/js/features/setup.js": ("control/js/features/setup.js", "text/javascript; charset=utf-8"),
    "/static/js/features/activity.js": ("control/js/features/activity.js", "text/javascript; charset=utf-8"),
    "/static/js/features/progress.js": ("control/js/features/progress.js", "text/javascript; charset=utf-8"),
    "/static/js/features/support.js": ("control/js/features/support.js", "text/javascript; charset=utf-8"),
    "/static/js/features/twitch.js": ("control/js/features/twitch.js", "text/javascript; charset=utf-8"),
    "/static/js/features/rewards.js": ("control/js/features/rewards.js", "text/javascript; charset=utf-8"),
    "/static/js/features/league.js": ("control/js/features/league.js", "text/javascript; charset=utf-8"),
    "/static/js/app.js": ("control/js/app.js", "text/javascript; charset=utf-8"),
}
# Canonical control URLs and old /static/js, /static/css aliases share files.
ASSETS.update({
    "/static/" + relative: (relative, mime)
    for relative, mime in list(ASSETS.values())
})

def static_asset(path):
    """Never expose config files or arbitrary filesystem paths."""
    entry = ASSETS.get(path)
    if entry is None:
        return None
    relative, content_type = entry
    resolved = (STATIC_ROOT / relative).resolve()
    if not resolved.is_relative_to(STATIC_ROOT.resolve()):
        return None
    try:
        return resolved.read_bytes(), content_type
    except OSError:
        return None
