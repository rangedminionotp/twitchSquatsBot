"""Single-instance, tenant-scoped Twitch token validation and refresh worker."""
import threading
import time
from urllib.error import HTTPError


class TokenService:
    def __init__(self, store, oauth, clock=time.monotonic):
        self.store, self.oauth, self.clock = store, oauth, clock
        self.lock = threading.Lock()
        self.user_locks = {}
        self.next_check = {}
        self.stopping = threading.Event()
        self.thread = None

    def user_lock(self, uid):
        with self.lock:
            return self.user_locks.setdefault(uid, threading.Lock())

    def check(self, uid):
        with self.user_lock(uid):
            if self.clock() < self.next_check.get(uid, 0):
                return self.store.auth_health(uid)['state']
            previous = None
            tokens = None
            try:
                previous, tokens = self.store.credential_snapshot(uid)
                if not tokens.get('access_token'):
                    self.next_check[uid] = self.clock() + 60
                    return 'reconnect_required'
                try:
                    identity = self.oauth.validate(tokens['access_token'])
                except HTTPError as error:
                    if error.code != 401:
                        raise
                    # Refresh only after an explicit invalid-access-token reply.
                    if not tokens.get('refresh_token'):
                        return self.revoke(uid, previous)
                    try:
                        refreshed = self.oauth.refresh(tokens['refresh_token'])
                    except HTTPError as refresh_error:
                        if refresh_error.code in (400,401):
                            return self.revoke(uid, previous)
                        raise
                    if not isinstance(refreshed.get('access_token'),str) or not refreshed['access_token']:
                        raise ValueError('Invalid token response')
                    if not isinstance(refreshed.get('refresh_token'),str) or not refreshed['refresh_token']:
                        raise ValueError('Missing rotated refresh token')
                    tokens = {**tokens, **{key:refreshed[key] for key in ('access_token','refresh_token','expires_in')}}
                    # Persist rotated credentials before validation; a transient
                    # validation outage must not lose the new refresh token.
                    if not self.store.save_credentials_if_current(uid,previous,tokens,'checking'):
                        self.next_check[uid] = 0
                        return 'checking'
                    previous, tokens = self.store.credential_snapshot(uid)
                    try:
                        identity = self.oauth.validate(tokens['access_token'])
                    except HTTPError as validation_error:
                        if validation_error.code == 401:
                            return self.revoke(uid, previous)
                        raise
                if identity.get('client_id') != self.oauth.client_id or identity.get('user_id') != uid:
                    return self.revoke(uid, previous)
                expires = identity.get('expires_in')
                scopes = identity.get('scopes')
                if type(expires) is not int or expires < 0 or not isinstance(scopes,list) or not all(isinstance(s,str) for s in scopes):
                    raise ValueError('Invalid validation response')
                tokens['scopes'] = scopes
                tokens['expires_in'] = expires
                if not self.store.save_credentials_if_current(uid,previous,tokens,'connected'):
                    self.next_check[uid] = 0
                    return 'checking'
                # Check before an hour elapses; retry near expiration but do not
                # proactively rotate a token that Twitch still says is valid.
                self.next_check[uid] = self.clock() + min(3300,max(30,expires))
                return 'connected'
            except Exception:
                # Network/provider/storage failure is not proof of revocation.
                # Never echo exception text: it may contain credentials.
                if previous is not None and tokens is not None:
                    try:
                        self.store.save_credentials_if_current(uid,previous,tokens,'temporarily_unavailable')
                    except Exception:
                        pass
                self.next_check[uid] = self.clock() + 60
                return 'temporarily_unavailable'

    def invalidate(self, uid):
        # A fresh authorization must not inherit the old token's check delay.
        with self.user_lock(uid):
            self.next_check.pop(uid, None)

    def revoke(self, uid, previous):
        if not self.store.save_credentials_if_current(uid,previous,{},'reconnect_required'):
            self.next_check[uid] = 0
            return 'checking'
        self.next_check[uid] = self.clock() + 60
        return 'reconnect_required'

    def tick(self):
        for uid in self.store.credential_users():
            if self.stopping.is_set():
                break
            self.check(uid)

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stopping.clear()
        def run():
            while not self.stopping.is_set():
                try:
                    self.tick()
                except Exception:
                    pass  # Retry store outages without leaking SQL/credential data.
                self.stopping.wait(30)
        self.thread = threading.Thread(target=run,daemon=True,name='cloud-token-validation')
        self.thread.start()

    def stop(self):
        self.stopping.set()
        if self.thread:
            self.thread.join(timeout=2)
