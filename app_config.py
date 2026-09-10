import json
import os
from pathlib import Path
from threading import RLock


DEFAULTS = {
    "twitch_client_id": "",
    "twitch_access_token": "",
    "twitch_refresh_token": "",
    "broadcaster_id": "",
    "broadcaster_login": "",
    "target_reward_id": "",
    "target_reward_title": "",
}


class AppConfig:
    """Small persistent config store. Environment variables remain supported."""

    def __init__(self):
        root = Path(os.environ.get("SQUAT_CAPTURE_DATA_DIR", Path.home() / ".squat-capture"))
        self.path = root / "config.json"
        self._lock = RLock()
        self._data = dict(DEFAULTS)
        self.load()

    def load(self):
        with self._lock:
            try:
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    self._data.update({key: loaded.get(key, value) for key, value in DEFAULTS.items()})
            except (OSError, ValueError):
                pass
            env_map = {
                "twitch_client_id": "TWITCH_CLIENT_ID",
                "twitch_access_token": "TWITCH_ACCESS_TOKEN",
                "twitch_refresh_token": "TWITCH_REFRESH_TOKEN",
                "broadcaster_id": "TWITCH_BROADCASTER_ID",
                "broadcaster_login": "TWITCH_BROADCASTER_LOGIN",
                "target_reward_id": "TARGET_REWARD_ID",
                "target_reward_title": "TARGET_REWARD_TITLE",
            }
            for key, env_name in env_map.items():
                if env_name in os.environ:
                    self._data[key] = os.environ[env_name]

    def get(self, key, default=""):
        with self._lock:
            return self._data.get(key, default)

    def public(self):
        with self._lock:
            result = dict(self._data)
            result["twitch_access_token"] = "" if not result["twitch_access_token"] else "configured"
            result["twitch_refresh_token"] = "" if not result["twitch_refresh_token"] else "configured"
            return result

    def update(self, values):
        with self._lock:
            for key in DEFAULTS:
                if key in values and key not in ("twitch_access_token", "twitch_refresh_token"):
                    self._data[key] = str(values[key] or "").strip()
            self._save()

    def update_tokens(self, access_token, refresh_token=""):
        with self._lock:
            self._data["twitch_access_token"] = access_token
            if refresh_token:
                self._data["twitch_refresh_token"] = refresh_token
            self._save()

    def update_identity(self, user):
        with self._lock:
            self._data["broadcaster_id"] = str(user.get("id", ""))
            self._data["broadcaster_login"] = str(user.get("login", ""))
            self._save()

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps(self._data, indent=2, ensure_ascii=False), encoding="utf-8")
        temp.replace(self.path)


APP_CONFIG = AppConfig()
