import json
import os
from pathlib import Path
from threading import RLock


class PersistentStats:
    """Durable, deduplicated squat totals keyed by capture-page session."""

    def __init__(self):
        root = Path(os.environ.get("SQUAT_CAPTURE_DATA_DIR", Path.home() / ".squat-capture"))
        self.path = root / "stats.json"
        self._lock = RLock()
        self._data = {
            "schema_version": 2,
            "owed_squats": 0,
            "completed_squats": 0,
            "capture_sessions": {},
        }
        self._load()

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
                if isinstance(sessions, dict):
                    self._data["capture_sessions"] = sessions
        except (OSError, TypeError, ValueError):
            pass

    def snapshot(self):
        with self._lock:
            return {
                "owed_squats": self._data["owed_squats"],
                "completed_squats": self._data["completed_squats"],
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
                self._data["owed_squats"] = max(0, self._data["owed_squats"] - delta)
                sessions[capture_session_id] = count
                # Keep the persistence file bounded while retaining recent dedupe keys.
                if len(sessions) > 100:
                    for old_key in list(sessions)[:-100]:
                        sessions.pop(old_key, None)
                self._save()
            return self.snapshot()

    def set_counters(self, owed=None, completed=None):
        updates = {}
        if owed is not None:
            updates["owed_squats"] = self._parse_counter(owed, "Owed counter")
        if completed is not None:
            updates["completed_squats"] = self._parse_counter(completed, "Completed counter")
        if not updates:
            raise ValueError("Provide owed_squats or completed_squats")
        with self._lock:
            self._data.update(updates)
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
