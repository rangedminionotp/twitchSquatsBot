import hashlib
import hmac
import json
import os
import shlex
import subprocess
import sys
import threading
import time
from pathlib import Path
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from squat_capture.app_config import APP_CONFIG
from squat_capture.app_stats import APP_STATS
from squat_capture.control_panel import CONTROL_HTML, POPUP_HTML, OVERLAY_HTML, static_asset, render_refresh_page
from squat_capture.camera_overlay import CAMERA_CONTROL
from squat_capture.twitch_eventsub_websocket import TwitchService
from squat_capture.support_events import SupportService


HOST = "0.0.0.0"
PORT = int(os.environ.get("PORT", "8080"))
CALLBACK_PATH = os.environ.get("TWITCH_CALLBACK_PATH", "/eventsub")
POPUP_PATH = os.environ.get("TWITCH_POPUP_PATH", "/squat-popup")
POPUP_EVENTS_PATH = os.environ.get("TWITCH_POPUP_EVENTS_PATH", "/popup-events")
OVERLAY_PATH = os.environ.get("TWITCH_OVERLAY_PATH", "/overlay")
OVERLAY_REFRESH_PATH = os.environ.get("TWITCH_OVERLAY_REFRESH_PATH", "/overlay-refresh")
OVERLAY_KEY_PATH = os.environ.get("TWITCH_OVERLAY_KEY_PATH", "/overlay-key")
OVERLAY_MAGENTA_KEY_PATH = os.environ.get("TWITCH_OVERLAY_MAGENTA_KEY_PATH", "/overlay-magenta-key")
OVERLAY_EVENTS_PATH = os.environ.get("TWITCH_OVERLAY_EVENTS_PATH", "/overlay-events")
OVERLAY_STATE_PATH = os.environ.get("TWITCH_OVERLAY_STATE_PATH", "/overlay-state")
SQUAT_PROGRESS_PATH = os.environ.get("TWITCH_SQUAT_PROGRESS_PATH", "/squat-progress")
SQUAT_COMPLETE_PATH = os.environ.get("TWITCH_SQUAT_COMPLETE_PATH", "/squat-complete")
EVENTSUB_SECRET = os.environ.get("TWITCH_EVENTSUB_SECRET", "")
BROADCASTER_LOGIN = os.environ.get("TWITCH_BROADCASTER_LOGIN", "")
TARGET_REWARD_TITLE = os.environ.get("TARGET_REWARD_TITLE", "")
TARGET_REWARD_ID = os.environ.get("TARGET_REWARD_ID", "")
MAX_MESSAGE_AGE_SECONDS = 600
AUTO_OPEN_POPUP = os.environ.get("AUTO_OPEN_POPUP", "1") == "1"
POPUP_OPEN_URL = os.environ.get("POPUP_OPEN_URL", f"http://127.0.0.1:{PORT}{POPUP_PATH}")
DEFAULT_SQUAT_TARGET = int(os.environ.get("DEFAULT_SQUAT_TARGET", "10"))
MAX_SESSION_SQUATS = int(os.environ.get("MAX_SESSION_SQUATS", "100"))
POPUP_VERSION = "2026-07-12-live-progress-1"
RIOT_CHECK_ENABLED = os.environ.get("RIOT_CHECK_ENABLED", "1") == "1"
RIOT_CHECK_COMMAND = os.environ.get("RIOT_CHECK_COMMAND", f'"{sys.executable}" -m squat_capture.script')
SOFT_LOCK_ENABLED = os.environ.get("SOFT_LOCK_ENABLED", "1") == "1"

MESSAGE_ID_HEADER = "Twitch-Eventsub-Message-Id"
MESSAGE_TIMESTAMP_HEADER = "Twitch-Eventsub-Message-Timestamp"
MESSAGE_SIGNATURE_HEADER = "Twitch-Eventsub-Message-Signature"
MESSAGE_TYPE_HEADER = "Twitch-Eventsub-Message-Type"
HMAC_PREFIX = "sha256="



class RedeemPopupState:
    def __init__(self):
        self.condition = threading.Condition()
        self.current_job = None
        self.sequence = 0
        self.last_popup_opened_at = 0.0
        self.last_popup_connected_at = 0.0
        self.session_squats_accepted = 0
        self.current_squat_count = 0
        self.current_squat_target = 0
        self.last_progress_at = 0.0

    def remaining_session_squats(self):
        if MAX_SESSION_SQUATS <= 0:
            return None
        return max(0, MAX_SESSION_SQUATS - self.session_squats_accepted)

    def can_accept(self, squat_target):
        remaining = self.remaining_session_squats()
        if remaining is None:
            return True, "session_limit_disabled", None
        if squat_target <= remaining:
            return True, "within_session_limit", remaining
        return False, "session_squat_limit_reached", remaining

    def publish(self, redemption):
        with self.condition:
            squat_target = extract_squat_target(redemption.get("reward_title"))
            can_accept, reason, remaining = self.can_accept(squat_target)
            if not can_accept:
                return None, {
                    "accepted": False,
                    "reason": reason,
                    "requested_squats": squat_target,
                    "session_squats_accepted": self.session_squats_accepted,
                    "max_session_squats": MAX_SESSION_SQUATS,
                    "remaining_session_squats": remaining,
                }

            self.sequence += 1
            payload = dict(redemption)
            payload["sequence"] = self.sequence
            payload["squat_target"] = squat_target
            self.session_squats_accepted += squat_target
            payload["session_squats_accepted"] = self.session_squats_accepted
            payload["queue_squat_target"] = self.session_squats_accepted
            payload["max_session_squats"] = MAX_SESSION_SQUATS
            payload["remaining_session_squats"] = self.remaining_session_squats()
            self.current_squat_target = self.session_squats_accepted
            self.current_job = payload
            self.condition.notify_all()
            return payload, {
                "accepted": True,
                "reason": reason,
                "requested_squats": squat_target,
                "session_squats_accepted": self.session_squats_accepted,
                "queue_squat_target": self.session_squats_accepted,
                "max_session_squats": MAX_SESSION_SQUATS,
                "remaining_session_squats": self.remaining_session_squats(),
            }

    def record_progress(self, progress_payload, squat_target=None):
        with self.condition:
            try:
                squat_count = max(0, int(progress_payload.get("squat_count", 0)))
            except (TypeError, ValueError):
                squat_count = self.current_squat_count

            if squat_target is None:
                reported_target = progress_payload.get("squat_target", self.current_squat_target)
                try:
                    squat_target = int(reported_target)
                except (TypeError, ValueError):
                    squat_target = self.current_squat_target

            squat_target = max(
                0,
                int(squat_target or 0),
                int(self.session_squats_accepted or 0),
                int(self.current_squat_target or 0),
            )
            self.current_squat_count = min(squat_count, squat_target) if squat_target else squat_count
            self.current_squat_target = squat_target
            self.last_progress_at = time.time()
            return {
                "squat_count": self.current_squat_count,
                "squat_target": self.current_squat_target,
                "progress_updated_at": self.last_progress_at,
            }

    def progress_snapshot(self):
        with self.condition:
            return {
                "squat_count": self.current_squat_count,
                "squat_target": self.current_squat_target,
                "progress_updated_at": self.last_progress_at,
            }

    def wait_for_next(self, last_seen_sequence, timeout=30.0):
        with self.condition:
            self.last_popup_connected_at = time.time()
            if self.current_job and self.current_job["sequence"] > last_seen_sequence:
                return self.current_job

            self.condition.wait(timeout)
            self.last_popup_connected_at = time.time()
            if self.current_job and self.current_job["sequence"] > last_seen_sequence:
                return self.current_job
            return None


POPUP_STATE = RedeemPopupState()


class ChallengeOverlayState:
    def __init__(self):
        self.condition = threading.Condition()
        self.sequence = 0
        self.state = {
            "status": "idle",
            "locked": False,
            "user_login": None,
            "user_name": None,
            "reward_title": None,
            "squat_count": 0,
            "squat_target": 0,
            "message": "Waiting for a channel point redeem.",
            "updated_at": time.time(),
        }

    def publish(self, updates):
        with self.condition:
            self.sequence += 1
            self.state.update(updates)
            self.state["sequence"] = self.sequence
            self.state["updated_at"] = time.time()
            snapshot = dict(self.state)
            self.condition.notify_all()
            return snapshot

    def snapshot(self):
        with self.condition:
            snapshot = dict(self.state)
            snapshot["sequence"] = self.sequence
            return snapshot

    def wait_for_next(self, last_seen_sequence, timeout=25.0):
        with self.condition:
            if self.sequence > last_seen_sequence:
                return dict(self.state)

            self.condition.wait(timeout)
            if self.sequence > last_seen_sequence:
                return dict(self.state)
            return None


OVERLAY_STATE = ChallengeOverlayState()
SOFT_LOCK_STATE = {
    "locked": False,
    "sequence": None,
    "started_at": None,
    "released_at": None,
}
SOFT_LOCK_STATE_LOCK = threading.Lock()


def extract_squat_target(reward_title):
    if not reward_title:
        return DEFAULT_SQUAT_TARGET

    digits = "".join(character if character.isdigit() else " " for character in reward_title)
    for token in digits.split():
        parsed = int(token)
        if parsed > 0:
            return parsed
    return DEFAULT_SQUAT_TARGET


def maybe_open_popup():
    if CAMERA_CONTROL.snapshot()["page_connected"]:
        return
    if not AUTO_OPEN_POPUP:
        return

    now = time.time()
    if now - POPUP_STATE.last_popup_connected_at < 20:
        return

    if now - POPUP_STATE.last_popup_opened_at < 2:
        return

    open_commands = [
        ["explorer.exe", POPUP_OPEN_URL],
        ["wslview", POPUP_OPEN_URL],
        ["xdg-open", POPUP_OPEN_URL],
        ["open", POPUP_OPEN_URL],
    ]
    errors = []
    for command in open_commands:
        try:
            subprocess.Popen(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            POPUP_STATE.last_popup_opened_at = now
            print(
                json.dumps({"popup_opened": True, "command": command[0], "url": POPUP_OPEN_URL}),
                flush=True,
            )
            return
        except OSError as error:
            errors.append(f"{command[0]}:{error}")

    print(
        json.dumps(
            {
                "popup_open_error": "no_supported_open_command",
                "attempts": errors,
                "url": POPUP_OPEN_URL,
            }
        ),
        flush=True,
    )


def soft_lock_game_windows(popup_job):
    if not SOFT_LOCK_ENABLED:
        return {"enabled": False, "locked": False, "reason": "soft_lock_disabled"}

    powershell_script = r"""
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class WindowTools {
    [DllImport("user32.dll")]
    public static extern bool ShowWindowAsync(IntPtr hWnd, int nCmdShow);
}
"@

$targets = @(
    "League of Legends",
    "LeagueClient",
    "LeagueClientUx",
    "LeagueClientUxRender",
    "Riot Client",
    "RiotClientServices"
)

$matched = @()
Get-Process | Where-Object { $_.MainWindowHandle -ne 0 } | ForEach-Object {
    $process = $_
    $isTarget = $targets -contains $process.ProcessName
    if (-not $isTarget -and $process.MainWindowTitle) {
        foreach ($target in $targets) {
            if ($process.MainWindowTitle -like "*$target*") {
                $isTarget = $true
                break
            }
        }
    }

    if ($isTarget) {
        [WindowTools]::ShowWindowAsync($process.MainWindowHandle, 6) | Out-Null
        $matched += [PSCustomObject]@{
            process = $process.ProcessName
            title = $process.MainWindowTitle
        }
    }
}

$matched | ConvertTo-Json -Compress
"""

    with SOFT_LOCK_STATE_LOCK:
        SOFT_LOCK_STATE["locked"] = True
        SOFT_LOCK_STATE["sequence"] = popup_job.get("sequence")
        SOFT_LOCK_STATE["started_at"] = time.time()
        SOFT_LOCK_STATE["released_at"] = None

    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", powershell_script],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception as error:
        return {
            "enabled": True,
            "locked": True,
            "window_action": "failed",
            "reason": str(error),
            "sequence": popup_job.get("sequence"),
        }

    stdout = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()
    return {
        "enabled": True,
        "locked": True,
        "window_action": "minimize",
        "returncode": result.returncode,
        "matched_windows": stdout,
        "error": stderr,
        "sequence": popup_job.get("sequence"),
    }


def release_soft_lock(completion_payload):
    with SOFT_LOCK_STATE_LOCK:
        was_locked = SOFT_LOCK_STATE["locked"]
        SOFT_LOCK_STATE["locked"] = False
        SOFT_LOCK_STATE["released_at"] = time.time()
        released_sequence = SOFT_LOCK_STATE["sequence"]

    return {
        "released": was_locked,
        "sequence": released_sequence,
        "completion": completion_payload,
    }


def publish_overlay_active(popup_job, soft_lock_result=None):
    locked = bool(soft_lock_result and soft_lock_result.get("locked"))
    queued_target = (
        popup_job.get("queue_squat_target")
        or popup_job.get("session_squats_accepted")
        or popup_job.get("squat_target")
        or DEFAULT_SQUAT_TARGET
    )
    stats = APP_STATS.snapshot()
    return OVERLAY_STATE.publish(
        {
            "status": "active",
            "locked": locked,
            "user_login": popup_job.get("user_login"),
            "user_name": popup_job.get("user_name"),
            "reward_title": popup_job.get("reward_title"),
            "squat_count": 0,
            "squat_target": queued_target,
            "message": "Redeem received. Squat challenge started.",
            "session_squats_accepted": popup_job.get("session_squats_accepted"),
            "max_session_squats": popup_job.get("max_session_squats"),
            "remaining_session_squats": popup_job.get("remaining_session_squats"),
            "owed_squats": stats["owed_squats"],
            "completed_squats": stats["completed_squats"],
        }
    )


def publish_overlay_progress(progress_payload):
    status = progress_payload.get("status") or "active"
    with SOFT_LOCK_STATE_LOCK:
        locked = status == "active" and bool(SOFT_LOCK_STATE["locked"])
    reported_target = progress_payload.get("squat_target", DEFAULT_SQUAT_TARGET)
    try:
        squat_target = max(int(reported_target), int(POPUP_STATE.session_squats_accepted))
    except (TypeError, ValueError):
        squat_target = POPUP_STATE.session_squats_accepted or DEFAULT_SQUAT_TARGET
    progress_state = POPUP_STATE.record_progress(progress_payload, squat_target)
    stats = APP_STATS.record_count(
        progress_payload.get("capture_session_id"),
        progress_state["squat_count"],
    )

    return OVERLAY_STATE.publish(
        {
            "status": status,
            "locked": locked,
            "user_login": progress_payload.get("user_login"),
            "user_name": progress_payload.get("user_name"),
            "reward_title": progress_payload.get("reward_title"),
            "squat_count": progress_state["squat_count"],
            "squat_target": progress_state["squat_target"],
            "message": "Squat progress updated.",
            "progress_updated_at": progress_state["progress_updated_at"],
            "owed_squats": stats["owed_squats"],
            "completed_squats": stats["completed_squats"],
        }
    )


def publish_overlay_skipped(reason, user_login=None, reward_title=None):
    return OVERLAY_STATE.publish(
        {
            "status": "skipped",
            "locked": False,
            "user_login": user_login,
            "user_name": user_login,
            "reward_title": reward_title,
            "squat_count": 0,
            "squat_target": 0,
            "message": f"Redeem skipped: {reason}",
        }
    )


def html_escape(value):
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#x27;")
    )


def build_refresh_overlay_html(page_background="rgba(0, 0, 0, 0)"):
    state = OVERLAY_STATE.snapshot()
    if state.get("status") in ("active", "complete"):
        state.update(POPUP_STATE.progress_snapshot())
    status = state.get("status") or "idle"
    viewer = state.get("user_name") or state.get("user_login") or "No active viewer"
    reward = state.get("reward_title") or "squat redeem"
    squat_count = int(state.get("squat_count") or 0)
    squat_target = int(state.get("squat_target") or 0)
    percent = min(100, round(squat_count / squat_target * 100)) if squat_target > 0 else 0

    if status == "complete":
        pill = "Unlocked"
        pill_class = "pill complete"
        message = f"{viewer}'s challenge is complete."
        footer_status = "Complete"
    elif status == "active":
        pill = "Locked" if state.get("locked") else "Active"
        pill_class = "pill"
        message = f"{viewer} redeemed {reward}."
        footer_status = "In Progress"
    elif status == "skipped":
        pill = "Skipped"
        pill_class = "pill"
        message = state.get("message") or "Redeem skipped."
        footer_status = "Skipped"
    else:
        pill = "Waiting"
        pill_class = "pill"
        message = "Waiting for a channel point redeem..."
        footer_status = "Idle"

    visible_class = "visible"
    return render_refresh_page({
        "page_background": html_escape(page_background),
        "percent": percent,
        "visible_class": visible_class,
        "pill_class": pill_class,
        "squat_count": squat_count,
        "squat_target": squat_target,
        "OVERLAY_STATE_PATH": OVERLAY_STATE_PATH,
        "html_escape(pill)": html_escape(pill),
        "html_escape(message)": html_escape(message),
        "html_escape(viewer)": html_escape(viewer),
        "html_escape(footer_status)": html_escape(footer_status),
    })


def should_trigger_popup_from_riot_check():
    configured_enabled = APP_CONFIG.get("riot_check_enabled")
    riot_check_enabled = configured_enabled == "1" if configured_enabled != "" else RIOT_CHECK_ENABLED
    if not riot_check_enabled:
        return True, "riot_check_disabled"

    try:
        command = shlex.split(RIOT_CHECK_COMMAND)
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=20,
            cwd=Path(__file__).resolve().parent.parent,
        )
    except Exception as error:
        return False, f"riot_check_failed:{error}"

    stdout = (result.stdout or "").strip().lower()
    stderr = (result.stderr or "").strip()

    if result.returncode != 0:
        return False, f"riot_check_nonzero:{result.returncode}:{stderr or stdout}"

    if stdout == "false":
        return True, "riot_idle"

    if stdout == "true":
        return False, "riot_in_game_or_unknown"

    return False, f"riot_check_unexpected_output:{stdout}"


def build_hmac(message_id, timestamp, raw_body):
    message = message_id.encode("utf-8") + timestamp.encode("utf-8") + raw_body
    digest = hmac.new(
        EVENTSUB_SECRET.encode("utf-8"),
        message,
        hashlib.sha256,
    ).hexdigest()
    return HMAC_PREFIX + digest


def is_valid_signature(headers, raw_body):
    message_id = headers.get(MESSAGE_ID_HEADER, "")
    timestamp = headers.get(MESSAGE_TIMESTAMP_HEADER, "")
    signature = headers.get(MESSAGE_SIGNATURE_HEADER, "")

    if not message_id or not timestamp or not signature:
        return False, "missing signature headers"

    expected_signature = build_hmac(message_id, timestamp, raw_body)
    if not hmac.compare_digest(expected_signature, signature):
        return (
            False,
            f"signature mismatch expected={expected_signature} got={signature}",
        )
    return True, "ok"


def is_recent_message(headers):
    timestamp = headers.get(MESSAGE_TIMESTAMP_HEADER, "")
    if not timestamp:
        return False, "missing timestamp"

    try:
        if timestamp.endswith("Z"):
            seconds_text, _, fractional_and_zone = timestamp[:-1].partition(".")
            if fractional_and_zone:
                fractional_seconds = fractional_and_zone[:6]
                normalized = f"{seconds_text}.{fractional_seconds}+00:00"
            else:
                normalized = f"{timestamp[:-1]}+00:00"
        else:
            normalized = timestamp

        event_time = datetime.fromisoformat(normalized).timestamp()
    except ValueError:
        return False, f"invalid timestamp format: {timestamp}"

    age_seconds = abs(time.time() - event_time)
    if age_seconds > MAX_MESSAGE_AGE_SECONDS:
        return False, f"message too old age_seconds={age_seconds:.2f}"
    return True, "ok"


def get_matching_redemption(payload):
    event = payload.get("event", {})
    broadcaster_login = (event.get("broadcaster_user_login") or "").lower()
    reward = event.get("reward", {})
    reward_title = reward.get("title")
    reward_id = reward.get("id")

    configured_login = APP_CONFIG.get("broadcaster_login") or BROADCASTER_LOGIN
    configured_reward_id = APP_CONFIG.get("target_reward_id") or TARGET_REWARD_ID
    configured_reward_title = APP_CONFIG.get("target_reward_title") or TARGET_REWARD_TITLE
    if not configured_reward_id and not configured_reward_title:
        return None
    if configured_login and broadcaster_login != configured_login.lower():
        return None

    if configured_reward_id and reward_id != configured_reward_id:
        return None

    if not configured_reward_id and configured_reward_title and reward_title != configured_reward_title:
        return None

    return {
        "redeemed": True,
        "event_type": payload.get("subscription", {}).get("type"),
        "broadcaster_login": broadcaster_login,
        "user_login": event.get("user_login"),
        "user_name": event.get("user_name"),
        "reward_title": reward_title,
        "reward_id": reward_id,
        "redeemed_at": event.get("redeemed_at"),
        "user_input": event.get("user_input"),
    }


def process_eventsub_notification(payload):
    if SUPPORT_SERVICE.twitch(payload):
        return
    if payload.get('subscription', {}).get('type') != 'channel.channel_points_custom_reward_redemption.add':
        return
    matched = get_matching_redemption(payload)
    if not matched:
        return
    event = payload.get('event', {})
    if not event.get('id') or event.get('status') == 'canceled':
        return
    import re
    amount = re.search(r'\d+', matched.get('reward_title') or '')
    target = int(amount.group()) if amount else DEFAULT_SQUAT_TARGET
    APP_STATS.enqueue(str(event.get('broadcaster_user_id', '')) + ':' + event['id'],
                      matched.get('user_name') or matched.get('user_login') or 'Viewer',
                      matched.get('reward_title') or 'Squats', target)
    OVERLAY_STATE.publish(APP_STATS.snapshot())


def legacy_process_eventsub_notification(payload):
    """Shared notification path for WebSocket and legacy webhook transports."""
    if SUPPORT_SERVICE.twitch(payload):
        return
    if CAMERA_CONTROL.snapshot()["page_connected"]:
        publish_overlay_skipped("Camera Overlay is in manual mode; switch to Capture in /control", "", "")
        return
    summary = summarize_redemption(payload)
    print(json.dumps({"incoming_redemption": summary}), flush=True)
    matched = get_matching_redemption(payload)
    if matched is None:
        print(json.dumps({"matched": False}), flush=True)
        return

    user_login = matched.get("user_login") or "unknown_user"
    reward_title = matched.get("reward_title") or "unknown_reward"
    should_trigger, trigger_reason = should_trigger_popup_from_riot_check()
    print(json.dumps({"riot_gate": {"allowed": should_trigger, "reason": trigger_reason,
        "user_login": user_login, "reward_title": reward_title}}), flush=True)
    if not should_trigger:
        publish_overlay_skipped(trigger_reason, user_login, reward_title)
        return

    popup_job, session_limit = POPUP_STATE.publish(matched)
    print(json.dumps({"session_limit": session_limit}), flush=True)
    if popup_job is None:
        publish_overlay_skipped(session_limit["reason"], user_login, reward_title)
        return

    soft_lock_result = soft_lock_game_windows(popup_job)
    print(json.dumps({"soft_lock": soft_lock_result}), flush=True)
    print(json.dumps({"overlay": publish_overlay_active(popup_job, soft_lock_result)}), flush=True)
    maybe_open_popup()
    print(f"{user_login} redeemed {reward_title}", flush=True)


SUPPORT_SERVICE = SupportService(APP_CONFIG, APP_STATS, OVERLAY_STATE.publish)
def update_stream_session(stream_id, status):
    stats = APP_STATS.observe_stream(stream_id, status)
    OVERLAY_STATE.publish(stats)


TWITCH_SERVICE = TwitchService(APP_CONFIG, process_eventsub_notification, update_stream_session)


def summarize_redemption(payload):
    event = payload.get("event", {})
    reward = event.get("reward", {})
    return {
        "event_type": payload.get("subscription", {}).get("type"),
        "broadcaster_login": event.get("broadcaster_user_login"),
        "user_login": event.get("user_login"),
        "user_name": event.get("user_name"),
        "reward_title": reward.get("title"),
        "reward_id": reward.get("id"),
        "redeemed_at": event.get("redeemed_at"),
        "user_input": event.get("user_input"),
    }


class EventSubHandler(BaseHTTPRequestHandler):
    seen_message_ids = set()

    def safe_write(self, body):
        try:
            self.wfile.write(body)
            return True
        except (BrokenPipeError, ConnectionResetError):
            print(json.dumps({"client_disconnected": self.path}), flush=True)
            return False

    def send_json_response(self, status_code, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.safe_write(body)

    def read_json_body(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        try:
            return json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            return {}

    def send_api_error(self, error):
        print(json.dumps({"control_api_error": str(error)}), flush=True)
        self.send_json_response(400, {"ok": False, "error": str(error)})

    def serve_control_page(self):
        body = CONTROL_HTML.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.safe_write(body)

    def serve_popup_page(self):
        html = POPUP_HTML.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.send_header("Content-Length", str(len(html)))
        self.end_headers()
        self.wfile.write(html)

    def serve_overlay_page(self):
        html = OVERLAY_HTML.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.send_header("Content-Length", str(len(html)))
        self.end_headers()
        self.safe_write(html)

    def serve_overlay_refresh_page(self):
        html = build_refresh_overlay_html().encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.send_header("Content-Length", str(len(html)))
        self.end_headers()
        self.safe_write(html)

    def serve_overlay_key_page(self):
        html = build_refresh_overlay_html("#00ff00").encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.send_header("Content-Length", str(len(html)))
        self.end_headers()
        self.safe_write(html)

    def serve_overlay_magenta_key_page(self):
        html = build_refresh_overlay_html("#ff00ff").encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.send_header("Content-Length", str(len(html)))
        self.end_headers()
        self.safe_write(html)

    def serve_overlay_events(self):
        last_event_id = self.headers.get("Last-Event-ID", "-1")
        try:
            last_seen_sequence = int(last_event_id or "-1")
        except ValueError:
            last_seen_sequence = -1

        event = OVERLAY_STATE.wait_for_next(last_seen_sequence, timeout=25.0)
        if event is None:
            payload = "event: keepalive\ndata: {}\n\n".encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
            self.send_header("Connection", "keep-alive")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.safe_write(payload)
            return

        event_id = event.get("sequence", 0)
        body = f"id: {event_id}\ndata: {json.dumps(event)}\n\n".encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.send_header("Connection", "keep-alive")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.safe_write(body)

    def serve_overlay_state(self):
        state = OVERLAY_STATE.snapshot()
        state.update(APP_STATS.snapshot())
        if state.get("status") in ("active", "complete"):
            progress_state = POPUP_STATE.progress_snapshot()
            state.update(
                {
                    "squat_count": progress_state["squat_count"],
                    "squat_target": progress_state["squat_target"],
                    "progress_updated_at": progress_state["progress_updated_at"],
                }
            )
        self.send_json_response(200, state)

    def serve_popup_events(self):
        last_event_id = self.headers.get("Last-Event-ID", "0")
        try:
            last_seen_sequence = int(last_event_id or "0")
        except ValueError:
            last_seen_sequence = 0

        event = POPUP_STATE.wait_for_next(last_seen_sequence, timeout=25.0)
        if event is None:
            payload = "event: keepalive\ndata: {}\n\n".encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
            self.send_header("Connection", "keep-alive")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.safe_write(payload)
            return

        body = f"id: {event['sequence']}\ndata: {json.dumps(event)}\n\n".encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.send_header("Connection", "keep-alive")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.safe_write(body)

    def do_GET(self):
        parsed_path = urlparse(self.path)
        if parsed_path.path == "/api/web-config":
            self.send_json_response(200, {
                "popupEventsPath": POPUP_EVENTS_PATH,
                "squatProgressPath": SQUAT_PROGRESS_PATH,
                "squatCompletePath": SQUAT_COMPLETE_PATH,
                "defaultSquatTarget": DEFAULT_SQUAT_TARGET,
                "popupVersion": POPUP_VERSION,
                "overlayEventsPath": OVERLAY_EVENTS_PATH,
                "overlayStatePath": OVERLAY_STATE_PATH,
            })
            return
        if parsed_path.path.startswith('/static/'):
            asset = static_asset(parsed_path.path)
            if asset is None:
                self.send_error(404)
                return
            body, content_type = asset
            self.send_response(200)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-cache')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()
            self.safe_write(body)
            return
        if parsed_path.path in ("/control", "/control/"):
            self.serve_control_page()
            return

        if parsed_path.path == "/api/settings":
            self.send_json_response(200, {
                "ok": True,
                "settings": APP_CONFIG.public(),
                "twitch": {**TWITCH_SERVICE.status, "auth_state": TWITCH_SERVICE.auth_state},
                "support": SUPPORT_SERVICE.status,
            })
            return

        if parsed_path.path == "/api/diagnostics":
            self.send_json_response(200, {"health": TWITCH_SERVICE.health(),
                "providers": dict(SUPPORT_SERVICE.status), "activity": APP_STATS.activity(),
                "events": SUPPORT_SERVICE.diagnostics()})
            return

        if parsed_path.path == "/api/stats":
            self.send_json_response(200, {"ok": True, **APP_STATS.snapshot()})
            return

        if parsed_path.path == "/api/twitch/rewards":
            try:
                self.send_json_response(200, {"ok": True, "rewards": TWITCH_SERVICE.rewards()})
            except Exception as error:
                self.send_api_error(error)
            return

        if parsed_path.path == CALLBACK_PATH:
            self.send_json_response(
                200,
                {
                    "ok": True,
                    "channel": BROADCASTER_LOGIN,
                    "reward_title": TARGET_REWARD_TITLE,
                    "reward_id": TARGET_REWARD_ID,
                    "popup_path": POPUP_PATH,
                    "popup_events_path": POPUP_EVENTS_PATH,
                    "overlay_path": OVERLAY_PATH,
                    "overlay_refresh_path": OVERLAY_REFRESH_PATH,
                    "overlay_key_path": OVERLAY_KEY_PATH,
                    "overlay_magenta_key_path": OVERLAY_MAGENTA_KEY_PATH,
                    "overlay_events_path": OVERLAY_EVENTS_PATH,
                    "overlay_state_path": OVERLAY_STATE_PATH,
                    "squat_progress_path": SQUAT_PROGRESS_PATH,
                    "squat_complete_path": SQUAT_COMPLETE_PATH,
                    "auto_open_popup": AUTO_OPEN_POPUP,
                    "soft_lock_enabled": SOFT_LOCK_ENABLED,
                    "max_session_squats": MAX_SESSION_SQUATS,
                    "session_squats_accepted": POPUP_STATE.session_squats_accepted,
                    "remaining_session_squats": POPUP_STATE.remaining_session_squats(),
                },
            )
            return

        if parsed_path.path == "/api/camera":
            self.send_json_response(200, {**CAMERA_CONTROL.snapshot(), "queue": APP_STATS.queue_snapshot()})
            return

        if parsed_path.path == "/api/queue":
            self.send_json_response(200, APP_STATS.queue_snapshot())
            return

        if parsed_path.path == POPUP_PATH or parsed_path.path in ("/", "/camera-overlay", "/capture", "/capture/"):
            self.serve_popup_page()
            return

        if parsed_path.path == POPUP_EVENTS_PATH:
            self.serve_popup_events()
            return

        if parsed_path.path == OVERLAY_PATH or parsed_path.path == "/overlay/":
            self.serve_overlay_page()
            return

        if parsed_path.path == OVERLAY_REFRESH_PATH:
            self.serve_overlay_refresh_page()
            return

        if parsed_path.path == OVERLAY_KEY_PATH:
            self.serve_overlay_key_page()
            return

        if parsed_path.path == OVERLAY_MAGENTA_KEY_PATH:
            self.serve_overlay_magenta_key_page()
            return

        if parsed_path.path == OVERLAY_EVENTS_PATH:
            self.serve_overlay_events()
            return

        if parsed_path.path == OVERLAY_STATE_PATH:
            self.serve_overlay_state()
            return

        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        parsed_path = urlparse(self.path)
        if parsed_path.path == "/api/camera":
            try:
                payload = self.read_json_body()
                camera = CAMERA_CONTROL.update(payload)
                if payload.get('mode') == 'webcam':
                    APP_STATS.set_queue_active(False)
                self.send_json_response(200, {**camera, "queue": APP_STATS.queue_snapshot()})
            except (ValueError, TypeError) as error:
                self.send_api_error(error)
            return
        if parsed_path.path == "/api/queue":
            try:
                action = self.read_json_body().get('action')
                if action not in ('start', 'pause'):
                    raise ValueError('Choose start or pause')
                if action == 'start':
                    if not CAMERA_CONTROL.snapshot().get('telemetry', {}).get('camera_live'):
                        raise ValueError('Open Camera Overlay and start the camera first')
                    allowed, reason = should_trigger_popup_from_riot_check()
                    if not allowed:
                        raise ValueError('League check: ' + reason)
                queue = APP_STATS.set_queue_active(action == 'start')
                CAMERA_CONTROL.update({'mode': 'capture' if action == 'start' else 'webcam'})
                self.send_json_response(200, queue)
            except ValueError as error:
                self.send_api_error(error)
            return
        if parsed_path.path == "/api/camera/progress":
            try:
                payload = self.read_json_body()
                if not CAMERA_CONTROL.owns(payload.get('page_id')):
                    raise ValueError('Camera ownership expired; reconnect before syncing')
                count = payload.get("count")
                session = payload.get("capture_session_id")
                if not isinstance(count, int) or isinstance(count, bool) or count < 0 or count > 1000000 or not isinstance(session, str) or not 1 <= len(session) <= 100:
                    raise ValueError("Invalid camera progress")
                stats = APP_STATS.record_count("camera:" + session, count, payload.get('queue_run'))
                OVERLAY_STATE.publish(stats)
                self.send_json_response(200, stats)
            except (ValueError, TypeError) as error:
                self.send_api_error(error)
            return
        if parsed_path.path == "/api/test-rule":
            try:
                payload = self.read_json_body()
                result = SUPPORT_SERVICE.preview(payload.get("source"), payload.get("amount", 1), payload.get("currency"))
                self.send_json_response(200, {"test_only": True, **result})
            except (ValueError, TypeError, AttributeError) as error:
                self.send_api_error(ValueError("Invalid test input") if not isinstance(error, ValueError) else error)
            return
        if parsed_path.path == "/api/settings":
            try:
                values = self.read_json_body()
                old_twitch = (APP_CONFIG.get("subs_enabled"), APP_CONFIG.get("bits_enabled"))
                APP_CONFIG.update(values)
                SUPPORT_SERVICE.start()
                if old_twitch != (APP_CONFIG.get("subs_enabled"), APP_CONFIG.get("bits_enabled")):
                    TWITCH_SERVICE.reconfigure()
                self.send_json_response(200, {"ok": True, "settings": APP_CONFIG.public()})
            except ValueError as error:
                self.send_api_error(error)
            return

        if parsed_path.path == "/api/stats":
            try:
                payload = self.read_json_body()
                stats = APP_STATS.set_counters(
                    owed=payload.get("owed_squats"),
                    completed=payload.get("completed_squats"),
                )
                OVERLAY_STATE.publish(stats)
                self.send_json_response(200, {"ok": True, **stats})
            except ValueError as error:
                self.send_api_error(error)
            return

        if parsed_path.path == "/api/twitch/login":
            try:
                login = TWITCH_SERVICE.start_device_login()
                self.send_json_response(200, {"ok": True, **login})
            except Exception as error:
                self.send_api_error(error)
            return

        if parsed_path.path == "/api/riot/test":
            allowed, reason = should_trigger_popup_from_riot_check()
            self.send_json_response(200, {"ok": True, "allowed": allowed, "reason": reason})
            return

        if parsed_path.path == SQUAT_PROGRESS_PATH:
            raw_body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            try:
                progress_payload = json.loads(raw_body.decode("utf-8") or "{}")
            except json.JSONDecodeError:
                progress_payload = {}

            overlay_update = publish_overlay_progress(progress_payload)
            print(json.dumps({"squat_progress": overlay_update}), flush=True)
            self.send_json_response(200, {"ok": True, "overlay": overlay_update})
            return

        if parsed_path.path == SQUAT_COMPLETE_PATH:
            raw_body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            try:
                completion_payload = json.loads(raw_body.decode("utf-8") or "{}")
            except json.JSONDecodeError:
                completion_payload = {}

            release_result = release_soft_lock(completion_payload)
            overlay_update = publish_overlay_progress(
                dict(completion_payload, status="complete")
            )
            print(json.dumps({"soft_lock_released": release_result}), flush=True)
            self.send_json_response(
                200,
                {"ok": True, "soft_lock": release_result, "overlay": overlay_update},
            )
            return

        if parsed_path.path != CALLBACK_PATH:
            self.send_response(404)
            self.end_headers()
            return

        raw_body = self.rfile.read(int(self.headers.get("Content-Length", "0")))

        if not EVENTSUB_SECRET:
            self.send_response(500)
            self.end_headers()
            return

        signature_valid, signature_reason = is_valid_signature(self.headers, raw_body)
        if not signature_valid:
            print(
                json.dumps(
                    {
                        "verification_error": "invalid_signature",
                        "reason": signature_reason,
                    }
                ),
                flush=True,
            )
            self.send_response(403)
            self.end_headers()
            return

        message_recent, recent_reason = is_recent_message(self.headers)
        if not message_recent:
            print(
                json.dumps(
                    {
                        "verification_error": "stale_message",
                        "reason": recent_reason,
                    }
                ),
                flush=True,
            )
            self.send_response(403)
            self.end_headers()
            return

        message_id = self.headers.get(MESSAGE_ID_HEADER)
        if message_id in self.seen_message_ids:
            self.send_response(204)
            self.end_headers()
            return
        self.seen_message_ids.add(message_id)

        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except json.JSONDecodeError:
            self.send_response(400)
            self.end_headers()
            return

        message_type = self.headers.get(MESSAGE_TYPE_HEADER, "")

        if message_type == "webhook_callback_verification":
            challenge = payload.get("challenge", "").encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(challenge)))
            self.end_headers()
            self.wfile.write(challenge)
            return

        if message_type == "revocation":
            print(
                json.dumps(
                    {
                        "revoked": True,
                        "subscription_type": payload.get("subscription", {}).get("type"),
                        "status": payload.get("subscription", {}).get("status"),
                    }
                )
            )
            self.send_response(204)
            self.end_headers()
            return

        if message_type != "notification":
            self.send_response(204)
            self.end_headers()
            return

        if message_type == 'notification':
            process_eventsub_notification({**payload, "message_id": message_id})
            self.send_response(204)
            self.end_headers()
            return

        if CAMERA_CONTROL.snapshot()["page_connected"]:
            publish_overlay_skipped("Camera Overlay is in manual mode; switch to Capture in /control", "", "")
            self.send_response(204)
            self.end_headers()
            return

        summary = summarize_redemption(payload)
        print(json.dumps({"incoming_redemption": summary}), flush=True)

        matched = get_matching_redemption(payload)
        if matched is not None:
            user_login = matched.get("user_login") or "unknown_user"
            reward_title = matched.get("reward_title") or "unknown_reward"
            should_trigger, trigger_reason = should_trigger_popup_from_riot_check()
            print(
                json.dumps(
                    {
                        "riot_gate": {
                            "allowed": should_trigger,
                            "reason": trigger_reason,
                            "user_login": user_login,
                            "reward_title": reward_title,
                        }
                    }
                ),
                flush=True,
            )
            if not should_trigger:
                publish_overlay_skipped(trigger_reason, user_login, reward_title)
                print(
                    json.dumps(
                        {
                            "redeemed": False,
                            "skipped": True,
                            "skip_reason": trigger_reason,
                            "user_login": user_login,
                            "reward_title": reward_title,
                        }
                    ),
                    flush=True,
                )
                self.send_response(204)
                self.end_headers()
                return

            popup_job, session_limit = POPUP_STATE.publish(matched)
            print(json.dumps({"session_limit": session_limit}), flush=True)
            if popup_job is None:
                publish_overlay_skipped(session_limit["reason"], user_login, reward_title)
                print(
                    json.dumps(
                        {
                            "redeemed": False,
                            "skipped": True,
                            "skip_reason": session_limit["reason"],
                            "user_login": user_login,
                            "reward_title": reward_title,
                            "requested_squats": session_limit["requested_squats"],
                            "session_squats_accepted": session_limit["session_squats_accepted"],
                            "max_session_squats": session_limit["max_session_squats"],
                            "remaining_session_squats": session_limit["remaining_session_squats"],
                        }
                    ),
                    flush=True,
                )
                self.send_response(204)
                self.end_headers()
                return

            soft_lock_result = soft_lock_game_windows(popup_job)
            print(json.dumps({"soft_lock": soft_lock_result}), flush=True)
            overlay_update = publish_overlay_active(popup_job, soft_lock_result)
            print(json.dumps({"overlay": overlay_update}), flush=True)
            maybe_open_popup()
            print(f"{user_login} redeemed {reward_title}", flush=True)
            print(
                json.dumps(
                    {
                        "popup_job": {
                            "sequence": popup_job["sequence"],
                            "squat_target": popup_job["squat_target"],
                            "popup_url": POPUP_OPEN_URL,
                        }
                    }
                ),
                flush=True,
            )
            print(json.dumps(matched), flush=True)
        else:
            print(
                json.dumps(
                    {
                        "matched": False,
                        "target_reward_title": TARGET_REWARD_TITLE,
                        "target_reward_id": TARGET_REWARD_ID,
                    }
                ),
                flush=True,
            )

        self.send_response(204)
        self.end_headers()


def main():
    from squat_capture.startup_check import dependency_errors, check_storage
    if dependency_errors():
        print("Startup blocked: missing / incompatible dependencies. Run scripts/start_wsl.sh or scripts/start_windows.ps1 to repair.", file=sys.stderr)
        return 1
    if not check_storage():
        print("Startup blocked: cannot write app data. Check directory permissions and free disk space.", file=sys.stderr)
        return 1
    try:
        server = ThreadingHTTPServer((HOST, PORT), EventSubHandler)
    except OSError:
        print(f"Cannot listen on {HOST}:{PORT}. Another instance may already be running. Check http://127.0.0.1:{PORT}/control, or stop the old instance. No process was stopped automatically.", file=sys.stderr)
        return 1
    TWITCH_SERVICE.start()
    SUPPORT_SERVICE.start()
    print(
        json.dumps(
            {
                "listening": True,
                "host": HOST,
                "port": PORT,
                "path": CALLBACK_PATH,
                "channel": APP_CONFIG.get("broadcaster_login") or BROADCASTER_LOGIN,
                "reward_title": APP_CONFIG.get("target_reward_title") or TARGET_REWARD_TITLE,
                "reward_id": APP_CONFIG.get("target_reward_id") or TARGET_REWARD_ID,
                "popup_path": POPUP_PATH,
                "overlay_path": OVERLAY_PATH,
                "overlay_url": f"http://127.0.0.1:{PORT}{OVERLAY_PATH}",
                "overlay_refresh_url": f"http://127.0.0.1:{PORT}{OVERLAY_REFRESH_PATH}",
                "overlay_key_url": f"http://127.0.0.1:{PORT}{OVERLAY_KEY_PATH}",
                "overlay_magenta_key_url": f"http://127.0.0.1:{PORT}{OVERLAY_MAGENTA_KEY_PATH}",
                "popup_open_url": POPUP_OPEN_URL,
                "auto_open_popup": AUTO_OPEN_POPUP,
                "soft_lock_enabled": SOFT_LOCK_ENABLED,
                "max_session_squats": MAX_SESSION_SQUATS,
                "control_url": f"http://127.0.0.1:{PORT}/control",
                "eventsub_transport": "websocket" if APP_CONFIG.get("twitch_access_token") else "setup_required",
                "legacy_webhook_enabled": bool(EVENTSUB_SECRET),
            }
        ),
        flush=True,
    )
    server.serve_forever()


if __name__ == "__main__":
    sys.exit(main())
