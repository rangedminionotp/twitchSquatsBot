import json
import os
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
        }
        self._load()
        self._stream_status = "unknown"

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

    def record_count(self, capture_session_id, count):
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
                delta = count - previous
                self._data["completed_squats"] += delta
                if self._stream_status == "live":
                    self._data["stream_completed"] += delta
                self._data["owed_squats"] = max(0, self._data["owed_squats"] - delta)
                sessions[capture_session_id] = count
                self._audit("capture", delta, "Reps completed; owed reduced (minimum zero)")
                # Keep the persistence file bounded while retaining recent dedupe keys.
                if len(sessions) > 100:
                    for old_key in list(sessions)[:-100]:
                        sessions.pop(old_key, None)
                self._save()
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
