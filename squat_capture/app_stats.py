import json
import os
import copy
import uuid
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock


class PersistentStats:
    """Durable, deduplicated squat totals keyed by capture-page session."""

    def __init__(self):
        root = Path(os.environ.get("SQUAT_CAPTURE_DATA_DIR", Path.home() / ".squat-capture"))
        self.path = root / "stats.json"
        self._lock = RLock()
        self._data = {
            "schema_version": 3,
            "owed_squats": 0,
            "completed_squats": 0,
            "stream_id": "",
            "stream_completed": 0,
            "capture_sessions": {},
            "support_events": {},
            "activity": [],
            "redemption_queue": [],
            "redemption_ids": {},
            "queue_runs": [],
        }
        self._load()
        self._stream_status = "unknown"
        self._queue_active = False

    def _load(self):
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                if int(loaded.get("schema_version", 1)) < 2:
                    # The original counter was presented as the amount owed.
                    self._data["owed_squats"] = max(0, int(loaded.get("lifetime_squats", 0)))
                else:
                    self._data["owed_squats"] = max(0, int(loaded.get("owed_squats", 0)))
                    self._data["completed_squats"] = max(0, int(loaded.get("completed_squats", 0)))
                sessions = loaded.get("capture_sessions", {})
                for key, kind in (("redemption_queue", list), ("redemption_ids", dict), ("queue_runs", list)):
                    if isinstance(loaded.get(key), kind):
                        self._data[key] = loaded[key]
                if isinstance(loaded.get("activity"), list):
                    self._data["activity"] = loaded["activity"][-100:]
                self._data["stream_id"] = str(loaded.get("stream_id", ""))
                self._data["stream_completed"] = max(0, int(loaded.get("stream_completed", 0)))
                if isinstance(loaded.get("support_events"), dict):
                    self._data["support_events"] = loaded["support_events"]
                if isinstance(sessions, dict):
                    self._data["capture_sessions"] = sessions
        except (OSError, TypeError, ValueError):
            pass

    def _audit(self, kind, amount, reason):
        self._data["activity"].append({"time": datetime.now(timezone.utc).isoformat(),
            "kind": kind, "amount": amount, "reason": reason})
        self._data["activity"] = self._data["activity"][-100:]

    def activity(self):
        with self._lock:
            return list(reversed(self._data["activity"]))

    def snapshot(self):
        with self._lock:
            return {
                "owed_squats": self._data["owed_squats"],
                "completed_squats": self._data["stream_completed"],
                "stream_status": self._stream_status,
                "stream_id": self._data["stream_id"],
                # Compatibility for older capture/overlay pages during a restart.
                "lifetime_squats": self._data["completed_squats"],
            }

    def queue_snapshot(self):
        with self._lock:
            return {"items": copy.deepcopy(self._data["redemption_queue"]), "active": self._queue_active,
                    "run": self._data["queue_runs"][-1] if self._queue_active and self._data["queue_runs"] else None}

    def enqueue(self, redemption_id, viewer, title, target):
        """Queue an immediate challenge without increasing future owed reps."""
        if not redemption_id or not isinstance(target, int) or not 1 <= target <= 1000000:
            raise ValueError("Invalid redemption")
        with self._lock:
            if redemption_id in self._data["redemption_ids"]:
                return self.queue_snapshot()
            before = copy.deepcopy(self._data)
            self._data["redemption_ids"][redemption_id] = True
            self._data["redemption_queue"].append({"id": redemption_id, "viewer": viewer, "title": title, "target": target, "done": 0})
            self._audit("redemption", target, "Challenge queued; total owed unchanged")
            try:
                self._save()
            except OSError:
                self._data = before
                raise
            return self.queue_snapshot()

    def set_queue_active(self, active):
        with self._lock:
            if active and not self._data["redemption_queue"]:
                raise ValueError("Queue is empty")
            if active and not self._queue_active:
                self._data["queue_runs"].append(uuid.uuid4().hex)
                try:
                    self._save()
                except OSError:
                    self._data["queue_runs"].pop()
                    raise
            self._queue_active = bool(active)
            return self.queue_snapshot()

    def record_count(self, capture_session_id, count, queue_run=None):
        if not capture_session_id:
            return self.snapshot()
        try:
            count = max(0, int(count))
        except (TypeError, ValueError):
            return self.snapshot()

        with self._lock:
            sessions = self._data["capture_sessions"]
            previous = max(0, int(sessions.get(capture_session_id, 0)))
            if count > previous:
                before = copy.deepcopy(self._data)
                was_active = self._queue_active
                delta = count - previous
                self._data["completed_squats"] += delta
                if self._stream_status == "live":
                    self._data["stream_completed"] += delta
                self._data["owed_squats"] = max(0, self._data["owed_squats"] - delta)
                sessions[capture_session_id] = count
                self._audit("capture", delta, "Reps completed; owed reduced (minimum zero)")
                if queue_run and queue_run in self._data["queue_runs"]:
                    remaining = delta
                    while remaining and self._data["redemption_queue"]:
                        head = self._data["redemption_queue"][0]
                        used = min(remaining, head["target"] - head["done"])
                        head["done"] += used
                        remaining -= used
                        if head["done"] == head["target"]:
                            self._audit("queue_complete", head["target"], "Queued challenge completed")
                            self._data["redemption_queue"].pop(0)
                    if not self._data["redemption_queue"]:
                        self._queue_active = False
                # Keep the persistence file bounded while retaining recent dedupe keys.
                if len(sessions) > 100:
                    for old_key in list(sessions)[:-100]:
                        if not old_key.startswith('camera:'):
                            sessions.pop(old_key, None)
                try:
                    self._save()
                except OSError:
                    self._data = before
                    self._queue_active = was_active
                    raise
            return self.snapshot()

    def observe_stream(self, stream_id=None, status="unknown"):
        """A Twitch broadcast ID, not a browser/app restart, defines a session."""
        with self._lock:
            if status == "live" and stream_id and stream_id != self._data["stream_id"]:
                old_id, old_count = self._data["stream_id"], self._data["stream_completed"]
                self._data["stream_id"], self._data["stream_completed"] = stream_id, 0
                try:
                    self._save()
                except OSError:
                    self._data["stream_id"], self._data["stream_completed"] = old_id, old_count
                    raise
            self._stream_status = status
            return self.snapshot()

    def add_support(self, event_key, amount):
        """Commit the increment and replay guard together; retain IDs across restarts."""
        if not event_key or not isinstance(amount, int) or amount < 0:
            raise ValueError("Invalid support event")
        with self._lock:
            if event_key in self._data["support_events"]:
                return {**self.snapshot(), "support_added": False}
            old_owed = self._data["owed_squats"]
            old_activity = list(self._data["activity"])
            self._data["owed_squats"] += amount
            self._data["support_events"][event_key] = amount
            self._audit(event_key.split(":", 1)[0], amount, "Added to owed" if amount else "Below one configured unit")
            try:
                self._save()
            except OSError:
                self._data["owed_squats"] = old_owed
                del self._data["support_events"][event_key]
                self._data["activity"] = old_activity
                raise
            return {**self.snapshot(), "support_added": True}

    def set_counters(self, owed=None, completed=None):
        updates = {}
        if owed is not None:
            updates["owed_squats"] = self._parse_counter(owed, "Owed counter")
        if completed is not None:
            updates["stream_completed"] = self._parse_counter(completed, "Session completed counter")
        if not updates:
            raise ValueError("Provide owed_squats or completed_squats")
        with self._lock:
            self._data.update(updates)
            self._audit("manual", 0, "Counters set: " + ", ".join(f"{key}={value}" for key, value in updates.items()))
            self._save()
            return self.snapshot()

    @staticmethod
    def _parse_counter(value, label):
        try:
            value = int(value)
        except (TypeError, ValueError) as error:
            raise ValueError(f"{label} must be a whole number") from error
        if value < 0:
            raise ValueError(f"{label} cannot be negative")
        return value

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps(self._data, indent=2), encoding="utf-8")
        temp.replace(self.path)


APP_STATS = PersistentStats()
