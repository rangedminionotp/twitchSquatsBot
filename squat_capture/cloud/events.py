"""Signed EventSub receiver, restricted to expected tenant subscriptions."""
import hashlib
import hmac
import json
from datetime import datetime, timezone

SUPPORTED = {'channel.channel_points_custom_reward_redemption.add', 'channel.subscribe',
             'channel.subscription.gift', 'channel.cheer'}


def handle_event(store, secret, headers, raw, now=None):
    if not secret:
        return 503, b'EventSub not configured'
    mid = headers.get('Twitch-Eventsub-Message-Id', '')
    stamp = headers.get('Twitch-Eventsub-Message-Timestamp', '')
    signature = headers.get('Twitch-Eventsub-Message-Signature', '')
    expected = 'sha256=' + hmac.new(secret.encode(), mid.encode()+stamp.encode()+raw, hashlib.sha256).hexdigest()
    if not mid or len(mid) > 200 or not hmac.compare_digest(signature.encode(), expected.encode()):
        return 403, b'Invalid signature'
    try:
        timestamp = datetime.fromisoformat(stamp.replace('Z','+00:00'))
        age = ((now or datetime.now(timezone.utc)) - timestamp).total_seconds()
        if age < -60 or age > 600:
            return 403, b'Expired message'
        body = json.loads(raw)
        sub = body['subscription']
        uid = sub['condition']['broadcaster_user_id']
        if sub['type'] not in SUPPORTED or sub['version'] != '1' or sub['transport']['method'] != 'webhook':
            raise ValueError('Unsupported subscription')
        store.profile(uid)  # Never enroll a user from an incoming webhook.
        message_type = headers.get('Twitch-Eventsub-Message-Type')
        if message_type not in ('webhook_callback_verification', 'notification', 'revocation'):
            return 400, b'Unsupported lifecycle message'
        if message_type == 'webhook_callback_verification':
            challenge = body['challenge']
            if not isinstance(challenge,str) or len(challenge)>4096:
                raise ValueError('Invalid challenge')
            if not store.accept_subscription(sub, message_type):
                return 400, b'Unexpected subscription'
            return 200, challenge.encode()
        if not store.accept_subscription(sub, message_type):
            return 400, b'Unexpected subscription'
        if message_type == 'notification':
            store.receive_event(uid, sub['type'], mid, body['event'])
            return 204, b''
        return 204, b''
    except (ValueError, TypeError, KeyError, AttributeError):
        return 400, b'Invalid event'
