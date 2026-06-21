import hashlib
import hmac
import json
import os
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer


HOST = "0.0.0.0"
PORT = int(os.environ.get("PORT", "8080"))
CALLBACK_PATH = os.environ.get("TWITCH_CALLBACK_PATH", "/eventsub")
EVENTSUB_SECRET = os.environ.get("TWITCH_EVENTSUB_SECRET", "")
BROADCASTER_LOGIN = "nannersowo"
TARGET_REWARD_TITLE = os.environ.get("TARGET_REWARD_TITLE", "Hydrate")
TARGET_REWARD_ID = os.environ.get("TARGET_REWARD_ID")
MAX_MESSAGE_AGE_SECONDS = 600

MESSAGE_ID_HEADER = "Twitch-Eventsub-Message-Id"
MESSAGE_TIMESTAMP_HEADER = "Twitch-Eventsub-Message-Timestamp"
MESSAGE_SIGNATURE_HEADER = "Twitch-Eventsub-Message-Signature"
MESSAGE_TYPE_HEADER = "Twitch-Eventsub-Message-Type"
HMAC_PREFIX = "sha256="


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

    if broadcaster_login != BROADCASTER_LOGIN.lower():
        return None

    if TARGET_REWARD_ID and reward_id != TARGET_REWARD_ID:
        return None

    if TARGET_REWARD_TITLE and reward_title != TARGET_REWARD_TITLE:
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

    def do_GET(self):
        if self.path != CALLBACK_PATH:
            self.send_response(404)
            self.end_headers()
            return

        body = json.dumps(
            {
                "ok": True,
                "channel": BROADCASTER_LOGIN,
                "reward_title": TARGET_REWARD_TITLE,
                "reward_id": TARGET_REWARD_ID,
            }
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path != CALLBACK_PATH:
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

        summary = summarize_redemption(payload)
        print(json.dumps({"incoming_redemption": summary}), flush=True)

        matched = get_matching_redemption(payload)
        if matched is not None:
            user_login = matched.get("user_login") or "unknown_user"
            reward_title = matched.get("reward_title") or "unknown_reward"
            print(f"{user_login} redeemed {reward_title}", flush=True)
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
    if not EVENTSUB_SECRET or len(EVENTSUB_SECRET) < 10:
        print("Set TWITCH_EVENTSUB_SECRET to an ASCII string with at least 10 characters.")
        return

    server = HTTPServer((HOST, PORT), EventSubHandler)
    print(
        json.dumps(
            {
                "listening": True,
                "host": HOST,
                "port": PORT,
                "path": CALLBACK_PATH,
                "channel": BROADCASTER_LOGIN,
                "reward_title": TARGET_REWARD_TITLE,
                "reward_id": TARGET_REWARD_ID,
            }
        ),
        flush=True,
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
