import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser


EVENTSUB_URL = "wss://eventsub.wss.twitch.tv/ws?keepalive_timeout_seconds=30"
API_URL = "https://api.twitch.tv/helix"
IDENTITY_URL = "https://id.twitch.tv/oauth2"
REDEMPTION_TYPE = "channel.channel_points_custom_reward_redemption.add"


def _request_json(url, method="GET", headers=None, data=None):
    body = None
    request_headers = dict(headers or {})
    if data is not None:
        body = urllib.parse.urlencode(data).encode("utf-8")
        request_headers.setdefault("Content-Type", "application/x-www-form-urlencoded")
    request = urllib.request.Request(url, data=body, headers=request_headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Twitch HTTP {error.code}: {detail}") from error


class TwitchService:
    def __init__(self, config, on_notification):
        self.config = config
        self.on_notification = on_notification
        self.status = {"state": "stopped", "message": "Not connected"}
        self._thread = None
        self._stop = threading.Event()
        self._socket = None
        self._auth_thread = None

    def api_headers(self):
        return {
            "Client-Id": self.config.get("twitch_client_id"),
            "Authorization": "Bearer " + self.config.get("twitch_access_token"),
        }

    def identify(self):
        payload = _request_json(API_URL + "/users", headers=self.api_headers())
        users = payload.get("data", [])
        if not users:
            raise RuntimeError("The Twitch token did not resolve to a user")
        self.config.update_identity(users[0])
        return users[0]

    def refresh_access_token(self):
        refresh_token = self.config.get("twitch_refresh_token")
        if not refresh_token:
            raise RuntimeError("Twitch login expired; reconnect from /control")
        result = _request_json(
            IDENTITY_URL + "/token",
            method="POST",
            data={
                "client_id": self.config.get("twitch_client_id"),
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
        )
        self.config.update_tokens(result["access_token"], result.get("refresh_token", ""))
        return result["access_token"]

    def rewards(self):
        broadcaster_id = self.config.get("broadcaster_id")
        if not broadcaster_id:
            self.identify()
            broadcaster_id = self.config.get("broadcaster_id")
        url = API_URL + "/channel_points/custom_rewards?" + urllib.parse.urlencode({"broadcaster_id": broadcaster_id})
        return _request_json(url, headers=self.api_headers()).get("data", [])

    def start_device_login(self):
        client_id = self.config.get("twitch_client_id")
        if not client_id:
            raise RuntimeError("Save a Twitch Client ID first")
        result = _request_json(
            IDENTITY_URL + "/device",
            method="POST",
            data={"client_id": client_id, "scopes": "channel:read:redemptions"},
        )
        if self._auth_thread and self._auth_thread.is_alive():
            raise RuntimeError("A Twitch login is already in progress")
        self.status = {"state": "authorizing", "message": "Waiting for Twitch authorization"}
        self._auth_thread = threading.Thread(target=self._poll_device_login, args=(result,), daemon=True)
        self._auth_thread.start()
        try:
            webbrowser.open(result["verification_uri"])
        except Exception:
            pass
        return {
            "verification_uri": result.get("verification_uri"),
            "user_code": result.get("user_code"),
            "expires_in": result.get("expires_in"),
        }

    def _poll_device_login(self, device):
        deadline = time.time() + int(device.get("expires_in", 900))
        interval = max(2, int(device.get("interval", 5)))
        while time.time() < deadline:
            try:
                result = _request_json(
                    IDENTITY_URL + "/token",
                    method="POST",
                    data={
                        "client_id": self.config.get("twitch_client_id"),
                        "device_code": device["device_code"],
                        "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                    },
                )
                self.config.update_tokens(result["access_token"], result.get("refresh_token", ""))
                user = self.identify()
                self.status = {"state": "authorized", "message": f"Logged in as {user['login']}"}
                self.start()
                return
            except RuntimeError as error:
                message = str(error)
                if "authorization_pending" not in message and "slow_down" not in message:
                    self.status = {"state": "error", "message": message}
                    return
            time.sleep(interval)
        self.status = {"state": "error", "message": "Twitch login expired"}

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        if not self.config.get("twitch_client_id") or not self.config.get("twitch_access_token"):
            self.status = {"state": "setup_required", "message": "Open /control to connect Twitch"}
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run_forever, daemon=True)
        self._thread.start()

    def _run_forever(self):
        try:
            import websocket
        except ImportError:
            self.status = {"state": "error", "message": "Install dependencies: pip install -r requirements.txt"}
            return
        delay = 2
        while not self._stop.is_set():
            self.status = {"state": "connecting", "message": "Connecting to Twitch EventSub"}
            try:
                self._socket = websocket.create_connection(EVENTSUB_URL, timeout=45)
                delay = 2
                seamless_reconnect = False
                while not self._stop.is_set():
                    packet = json.loads(self._socket.recv())
                    message_type = packet.get("metadata", {}).get("message_type")
                    if message_type == "session_welcome":
                        session_id = packet["payload"]["session"]["id"]
                        if not seamless_reconnect:
                            self._subscribe(session_id)
                        seamless_reconnect = False
                        self.status = {"state": "connected", "message": "Listening for channel point redeems"}
                    elif message_type == "notification":
                        self.on_notification(packet.get("payload", {}))
                    elif message_type == "session_reconnect":
                        reconnect_url = packet["payload"]["session"]["reconnect_url"]
                        self._socket.close()
                        self._socket = websocket.create_connection(reconnect_url, timeout=45)
                        seamless_reconnect = True
            except Exception as error:
                self.status = {"state": "disconnected", "message": str(error)}
                if not self._stop.wait(delay):
                    delay = min(delay * 2, 30)

    def _subscribe(self, session_id, allow_refresh=True):
        broadcaster_id = self.config.get("broadcaster_id")
        if not broadcaster_id:
            self.identify()
            broadcaster_id = self.config.get("broadcaster_id")
        payload = {
            "type": REDEMPTION_TYPE,
            "version": "1",
            "condition": {"broadcaster_user_id": broadcaster_id},
            "transport": {"method": "websocket", "session_id": session_id},
        }
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            API_URL + "/eventsub/subscriptions",
            data=body,
            headers={**self.api_headers(), "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=20):
                return
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            if error.code == 401 and allow_refresh:
                self.refresh_access_token()
                return self._subscribe(session_id, allow_refresh=False)
            raise RuntimeError(f"Could not create EventSub subscription ({error.code}): {detail}") from error
