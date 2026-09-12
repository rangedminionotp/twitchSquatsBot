"""Opt-in support rules. No provider credentials are sent to the browser."""
import json
import threading
import time
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode

SOURCES = ("subs", "bits", "streamlabs", "streamelements")
SUPPORT_DEFAULTS = {}
for source in SOURCES:
    SUPPORT_DEFAULTS.update({source + "_enabled": "0", source + "_squats": "1"})
SUPPORT_DEFAULTS.update({"bits_unit": "100", "streamlabs_unit": "1",
    "streamelements_unit": "1", "streamlabs_currency": "USD",
    "streamelements_currency": "USD", "streamlabs_token": "",
    "streamelements_token": "", "streamelements_channel": ""})


def number(value):
    result = Decimal(str(value))
    if not result.is_finite() or result < 0 or result > 1000000000:
        raise ValueError("Amount must be finite and between 0 and 1,000,000,000")
    return result


def validate_support_settings(values):
    if not isinstance(values, dict):
        raise ValueError("Settings must be an object")
    values = dict(values)
    for key in SUPPORT_DEFAULTS.keys() & values.keys():
        value = str(values[key]).strip()
        if key.endswith("_enabled") and value not in ("0", "1"):
            raise ValueError("Enable options must be 0 or 1")
        if key.endswith(("_unit", "_squats")):
            try:
                n = number(value)
                if n < Decimal("0.01") or (key.endswith("_squats") or key == "bits_unit") and n != n.to_integral_value():
                    raise ValueError()
            except (ValueError, InvalidOperation):
                raise ValueError(key + ": use a positive number (whole squats / Bits)") from None
        if key.endswith("_currency"):
            value = value.upper()
            if len(value) != 3 or not value.isascii() or not value.isalpha():
                raise ValueError("Currency must be a three-letter code, e.g. USD")
        values[key] = value
    return values


class SupportService:
    def __init__(self, config, stats, publish):
        self.config, self.stats, self.publish = config, stats, publish
        self.status = {s: "Disabled" for s in ("streamlabs", "streamelements")}
        self._workers = {}
        self._lock = threading.RLock()

    def add(self, source, event_id, amount=1, currency=None):
        if self.config.get(source + "_enabled") != "1" or not event_id:
            return
        if currency is not None and str(currency).upper() != self.config.get(source + "_currency"):
            return
        try:
            amount = number(amount)
            unit = number(self.config.get(source + "_unit", "1"))
            squats = number(self.config.get(source + "_squats"))
            delta = int(amount // unit) * int(squats)
        except (ValueError, InvalidOperation, ZeroDivisionError):
            return
        account = self.config.get("broadcaster_id") if source in ("subs", "bits") else ""
        snapshot = self.stats.add_support(f"{source}:{account}:{event_id}", delta)
        self.publish(snapshot)

    def twitch(self, payload):
        kind = payload.get("subscription", {}).get("type", "")
        event = payload.get("event", {})
        if kind not in ("channel.subscribe", "channel.subscription.gift", "channel.cheer"):
            return False
        if event.get("broadcaster_user_id") != self.config.get("broadcaster_id"):
            return True
        key = payload.get("message_id")
        if kind == "channel.subscribe" and not event.get("is_gift"):
            self.add("subs", key)
        elif kind == "channel.subscription.gift":
            self.add("subs", key, event.get("total", 0))
        elif kind == "channel.cheer":
            self.add("bits", key, event.get("bits", 0))
        return True

    def streamlabs(self, event):
        if event.get("type") != "donation" or event.get("for") not in (None, "", "streamlabs") or event.get("isTest"):
            return
        for donation in event.get("message", []):
            if not isinstance(donation, dict) or donation.get("isTest"):
                continue
            self.add("streamlabs", donation.get("id") or donation.get("_id"),
                     donation.get("amount"), donation.get("currency", ""))

    def streamelements(self, packet):
        if packet.get("type") != "message" or packet.get("topic") != "channel.tips":
            return
        tip = packet.get("data", {})
        if tip.get("channel") != self.config.get("streamelements_channel") or tip.get("status") != "success" or tip.get("isTest"):
            return
        donation = tip.get("donation", {})
        self.add("streamelements", tip.get("_id"), donation.get("amount"), donation.get("currency", ""))

    def start(self):
        """Reconfigure only changed provider connections; old workers exit before replacement."""
        with self._lock:
            for source in self.status:
                signature = tuple(self.config.get(source + suffix) for suffix in ("_enabled", "_token", "_channel"))
                previous = self._workers.get(source)
                if previous and previous[0] == signature:
                    continue
                if previous:
                    previous[1].set()
                stop = threading.Event()
                self._workers[source] = (signature, stop)
                if signature[0] != "1":
                    self.status[source] = "Disabled"
                elif not signature[1] or source == "streamelements" and not signature[2]:
                    self.status[source] = "Setup required — enter credentials"
                else:
                    self.status[source] = "Connecting"
                    threading.Thread(target=self._run, args=(source, signature, stop), daemon=True).start()

    def _run(self, source, signature, stop):
        try:
            import websocket
        except ImportError:
            self.status[source] = "Install requirements.txt and restart"
            return
        delay = 2
        while not stop.is_set():
            ws = None
            try:
                url = ("wss://sockets.streamlabs.com/socket.io/?" + urlencode({"EIO": 3, "transport": "websocket", "token": signature[1]})) if source == "streamlabs" else "wss://astro.streamelements.com/"
                ws = websocket.create_connection(url, timeout=10)
                ws.settimeout(1)
                ping_at, ping_interval, pong_deadline = time.monotonic() + 20, 20, None
                while not stop.is_set():
                    now = time.monotonic()
                    if source == "streamlabs" and now >= ping_at:
                        ws.send("2")
                        ping_at = now + ping_interval
                        pong_deadline = now + 10
                    if pong_deadline and now > pong_deadline:
                        raise RuntimeError("Heartbeat expired")
                    try:
                        raw = ws.recv()
                    except websocket.WebSocketTimeoutException:
                        continue
                    if stop.is_set():
                        break
                    if not raw:
                        raise RuntimeError("Disconnected")
                    if source == "streamlabs":
                        if raw.startswith("0"):
                            hello = json.loads(raw[1:])
                            ping_interval = max(1, hello.get("pingInterval", 25000) / 1000)
                            ping_at = time.monotonic() + ping_interval
                        elif raw.startswith("40"):
                            self.status[source] = "Listening"
                            delay = 2
                        elif raw == "3":
                            pong_deadline = None
                        elif raw.startswith("42"):
                            event = json.loads(raw[2:])
                            if event[0] == "event":
                                self.streamlabs(event[1])
                        elif raw.startswith(("41", "44")):
                            raise RuntimeError("Authorization failed")
                    else:
                        packet = json.loads(raw)
                        if packet.get("type") == "welcome":
                            ws.send(json.dumps({"type": "subscribe", "nonce": "squat-tips", "data": {
                                "topic": "channel.tips", "room": signature[2], "token": signature[1], "token_type": "jwt"}}))
                        elif packet.get("type") == "response":
                            if packet.get("error"):
                                raise RuntimeError("Authorization failed")
                            self.status[source] = "Listening"
                            delay = 2
                        elif packet.get("type") == "reconnect":
                            raise RuntimeError("Reconnect requested")
                        else:
                            self.streamelements(packet)
            except Exception:
                # Socket errors can contain secret URLs. Never expose exception text.
                if not stop.is_set():
                    self.status[source] = "Disconnected — retrying; check token / channel / network"
            finally:
                if ws:
                    ws.close()
            if not stop.wait(delay):
                delay = min(delay * 2, 60)
