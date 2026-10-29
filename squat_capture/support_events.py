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
SUPPORT_DEFAULTS.update({"subs_enabled": "1", "subs_squats": "5",
    "bits_enabled": "1", "bits_unit": "500", "bits_squats": "10", "streamlabs_unit": "1",
    "bits_bundle_enabled": "1", "bits_bundle_unit": "1000", "bits_bundle_squats": "30",
    "streamelements_unit": "1", "streamlabs_currency": "USD",
    "streamelements_currency": "USD", "streamlabs_token": "",
    "streamelements_token": "", "streamelements_channel": ""})


def number(value):
    result = Decimal(str(value))
    if not result.is_finite() or result < 0 or result > 1000000000:
        raise ValueError("Amount must be finite and between 0 and 1,000,000,000")
    return result


def bits_squats(amount, unit, squats, bundle_unit=1000, bundle_squats=0):
    """Per-event bundles first, then base units; never carry remainders forward."""
    fields = [number(value) for value in (amount, unit, squats, bundle_unit, bundle_squats)]
    if any(value != value.to_integral_value() for value in fields):
        raise ValueError("Bits rules require whole numbers")
    amount, unit, squats, bundle_unit, bundle_squats = map(int, fields)
    if unit < 1 or bundle_unit < 1:
        raise ValueError("Bits units must be positive")
    if bundle_squats and (bundle_unit <= unit or bundle_unit % unit):
        raise ValueError("Bits bundle must be a larger multiple of the base unit")
    if not squats:  # Cloud uses zero base reps to disable Bits entirely.
        return 0
    bundles, remainder = divmod(amount, bundle_unit) if bundle_squats else (0, amount)
    return bundles * bundle_squats + (remainder // unit) * squats


def validate_support_settings(values, current=None):
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
                if n < Decimal("0.01") or (key.endswith("_squats") or key.startswith("bits_")) and n != n.to_integral_value():
                    raise ValueError()
            except (ValueError, InvalidOperation):
                raise ValueError(key + ": use a positive number (whole squats / Bits)") from None
        if key.endswith("_currency"):
            value = value.upper()
            if len(value) != 3 or not value.isascii() or not value.isalpha():
                raise ValueError("Currency must be a three-letter code, e.g. USD")
        values[key] = value
    merged = {**SUPPORT_DEFAULTS, **(current or {}), **values}
    if merged['bits_bundle_enabled'] == '1':
        bits_squats(0, merged['bits_unit'], merged['bits_squats'],
                    merged['bits_bundle_unit'], merged['bits_bundle_squats'])
    return values


class SupportService:
    def __init__(self, config, stats, publish):
        self.config, self.stats, self.publish = config, stats, publish
        self.status = {s: "Disabled" for s in ("streamlabs", "streamelements")}
        self._workers = {}
        self._lock = threading.RLock()
        self.recent = []

    def preview(self, source, amount=1, currency=None):
        if source not in SOURCES:
            raise ValueError("Unknown source")
        if self.config.get(source + "_enabled") != "1":
            return {"delta": 0, "reason": "Source disabled"}
        if source in ("streamlabs", "streamelements") and str(currency or "").upper() != self.config.get(source + "_currency"):
            return {"delta": 0, "reason": "Currency does not match saved rule"}
        try:
            amount = number(amount)
            if source in ("subs", "bits") and amount != amount.to_integral_value():
                raise ValueError()
            unit = number(self.config.get(source + "_unit", "1"))
            delta = int(amount // unit) * int(number(self.config.get(source + "_squats")))
            if source == 'bits':
                delta = bits_squats(amount, unit, self.config.get('bits_squats'),
                    self.config.get('bits_bundle_unit', '1000'),
                    self.config.get('bits_bundle_squats', '30') if self.config.get('bits_bundle_enabled') == '1' else 0)
        except (ValueError, InvalidOperation, ZeroDivisionError):
            raise ValueError("Invalid amount or saved rule") from None
        return {"delta": delta, "reason": "Would add to owed" if delta else "Below one configured unit"}

    def _notice(self, source, reason):
        with self._lock:
            self.recent.insert(0, {"source": source, "reason": reason, "time": time.time()})
            del self.recent[30:]

    def diagnostics(self):
        with self._lock:
            return list(self.recent)

    def add(self, source, event_id, amount=1, currency=None):
        if not event_id:
            self._notice(source, "Ignored: missing event ID")
            return
        try:
            result = self.preview(source, amount, currency)
        except ValueError:
            self._notice(source, "Ignored: invalid amount or rule")
            return
        if result["reason"] in ("Source disabled", "Currency does not match saved rule"):
            self._notice(source, result["reason"])
            return
        account = self.config.get("broadcaster_id") if source in ("subs", "bits") else ""
        snapshot = self.stats.add_support(f"{source}:{account}:{event_id}", result["delta"])
        self._notice(source, "Added +" + str(result["delta"]) if snapshot.pop("support_added", False) else "Ignored: duplicate event")
        self.publish(snapshot)

    def twitch(self, payload):
        kind = payload.get("subscription", {}).get("type", "")
        event = payload.get("event", {})
        if kind not in ("channel.subscribe", "channel.subscription.gift", "channel.cheer"):
            return False
        if event.get("broadcaster_user_id") != self.config.get("broadcaster_id"):
            self._notice("twitch", "Ignored: different broadcaster")
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
