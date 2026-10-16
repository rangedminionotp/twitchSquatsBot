"""Opt-in, single-instance EventSub reconciliation; never touches other callbacks."""
import json
import threading
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from squat_capture.cloud.oauth import json_request

REDEMPTION = 'channel.channel_points_custom_reward_redemption.add'
SCOPES = {REDEMPTION:'channel:read:redemptions','channel.subscribe':'channel:read:subscriptions',
          'channel.subscription.gift':'channel:read:subscriptions','channel.cheer':'bits:read'}


def desired(rules):
    return {kind for kind,on in [(REDEMPTION,bool(rules['reward_id'])),('channel.subscribe',rules['sub_reps']),
                                 ('channel.subscription.gift',rules['gift_reps']),('channel.cheer',rules['bits_reps'])] if on}


class EventSubAPI:
    def __init__(self, client_id, client_secret):
        self.client_id, self.client_secret = client_id, client_secret
        self.token, self.expires = '', 0

    def request(self, method='GET', query=None, body=None):
        for attempt in range(2):
            if time.monotonic() >= self.expires:
                grant = json_request('https://id.twitch.tv/oauth2/token', data={
                    'client_id':self.client_id,'client_secret':self.client_secret,'grant_type':'client_credentials'})
                self.token = grant['access_token']
                self.expires = time.monotonic()+max(1,grant['expires_in']-60)
            url = 'https://api.twitch.tv/helix/eventsub/subscriptions'
            if query:
                url += '?' + urlencode(query)
            request = Request(url,method=method,data=json.dumps(body).encode() if body is not None else None,
                              headers={'Client-ID':self.client_id,'Authorization':'Bearer '+self.token,'Content-Type':'application/json'})
            try:
                with urlopen(request,timeout=15) as response:
                    return {} if response.status == 204 else json.load(response)
            except HTTPError as error:
                if error.code == 401 and attempt == 0:
                    self.expires = 0
                    continue
                raise

    def list(self):
        result, cursor = [], None
        for _ in range(100):
            page = self.request(query={'after':cursor} if cursor else None)
            result.extend(page['data'])
            next_cursor = page.get('pagination',{}).get('cursor')
            if not next_cursor:
                return result
            if next_cursor == cursor:
                raise ValueError('Repeated pagination cursor')
            cursor = next_cursor
        raise ValueError('Subscription inventory too large')

    def create(self, uid, kind, callback, secret):
        return self.request('POST',body={'type':kind,'version':'1','condition':{'broadcaster_user_id':uid},
                            'transport':{'method':'webhook','callback':callback,'secret':secret}})['data'][0]

    def delete(self, remote_id):
        try:
            self.request('DELETE',query={'id':remote_id})
        except HTTPError as error:
            if error.code != 404:
                raise


class SubscriptionService:
    def __init__(self, store, tokens, api, callback, secret):
        self.store, self.tokens, self.api = store, tokens, api
        self.callback, self.secret = callback, secret
        self.stopping = threading.Event()
        self.thread = None

    def tick(self):
        # One complete inventory per cycle; failure must not be treated as empty.
        users = self.store.credential_users()
        if not any(self.store.listener(uid)['enabled'] or self.store.subscriptions(uid) for uid in users):
            return
        try:
            inventory = self.api.list()
        except Exception:
            for uid in users:
                if self.store.listener(uid)['enabled']:
                    self.store.listener_message(uid,'service_unavailable')
            return
        for uid in users:
            if self.stopping.is_set():
                return
            try:
                self.reconcile(uid,inventory)
            except HTTPError as error:
                self.store.listener_message(uid,{403:'missing_permission',409:'subscription_conflict',429:'rate_limited'}.get(error.code,'service_unavailable'))
                if error.code == 429:
                    return
            except Exception:
                self.store.listener_message(uid,'service_unavailable')

    def reconcile(self, uid, inventory):
        enabled = bool(self.store.listener(uid)['enabled'])
        wanted = desired(self.store.rules(uid)) if enabled else set()
        auth = self.tokens.check(uid) if enabled else 'disabled'
        if auth == 'reconnect_required':
            wanted = set()
        elif enabled and auth != 'connected':
            self.store.listener_message(uid,'authorization_unavailable')
            return
        owned = [sub for sub in inventory if sub.get('transport',{}).get('callback') == self.callback
                 and sub.get('transport',{}).get('method') == 'webhook' and sub.get('version') == '1'
                 and sub.get('condition',{}).get('broadcaster_user_id') == uid and sub.get('type') in SCOPES]
        for sub in owned:
            kind = sub['type']
            if kind not in wanted:
                self.api.delete(sub['id'])
                self.store.forget_subscription(uid,kind)
        for record in self.store.subscriptions(uid):
            if record['kind'] not in wanted:
                self.store.forget_subscription(uid,record['kind'])
        if wanted:
            _, credentials = self.store.credential_snapshot(uid)
            if not {SCOPES[kind] for kind in wanted}.issubset(set(credentials.get('scopes',[]))):
                self.store.listener_message(uid,'missing_permission')
                return
        for kind in sorted(wanted):
            matching = [sub for sub in owned if sub['type'] == kind]
            self.store.expect_subscription(uid,kind,self.callback)
            if matching:
                sub = matching[0]
                record = next(r for r in self.store.subscriptions(uid) if r['kind'] == kind)
                if record['remote_id'] and record['remote_id'] != sub['id']:
                    self.store.forget_subscription(uid,kind)
                    self.store.expect_subscription(uid,kind,self.callback)
                self.store.save_subscription(uid,kind,sub['id'],sub['status'])
                continue
            # Drop stale IDs only after the complete inventory confirms absence.
            self.store.forget_subscription(uid,kind)
            self.store.expect_subscription(uid,kind,self.callback)
            sub = self.api.create(uid,kind,self.callback,self.secret)
            self.store.save_subscription(uid,kind,sub['id'],sub['status'])
        records = self.store.subscriptions(uid)
        ready = wanted and len(records)==len(wanted) and all(r['status']=='enabled' for r in records)
        self.store.listener_message(uid,'reconnect_required' if auth=='reconnect_required' else
                                    'disabled' if not enabled else 'no_rules' if not wanted else
                                    'listening' if ready else 'pending_or_attention')

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        def run():
            while not self.stopping.is_set():
                try:
                    self.tick()
                except Exception:
                    pass
                self.stopping.wait(60)
        self.thread = threading.Thread(target=run,daemon=True,name='cloud-eventsub')
        self.thread.start()

    def stop(self):
        self.stopping.set()
        if self.thread:
            self.thread.join(timeout=2)
