"""Read-only, tenant-bound Helix data. No browser-supplied broadcaster IDs."""
import threading
from urllib.parse import urlencode
from squat_capture.cloud.oauth import json_request


class TwitchData:
    def __init__(self, store, tokens, client_id):
        self.store, self.tokens, self.client_id = store, tokens, client_id
        self.stopping = threading.Event()
        self.thread = None

    def get(self, uid, endpoint, query, scope=None):
        if self.tokens.check(uid) != 'connected':
            raise ValueError('Reconnect Twitch or wait for authorization verification.')
        _, credentials = self.store.credential_snapshot(uid)
        if scope and scope not in credentials.get('scopes',[]):
            raise ValueError('Authorize event permissions before loading rewards.')
        return json_request('https://api.twitch.tv/helix/'+endpoint+'?'+urlencode(query),
                            headers={'Client-ID':self.client_id,'Authorization':'Bearer '+credentials['access_token']})

    def rewards(self, uid):
        rows = self.get(uid,'channel_points/custom_rewards',{'broadcaster_id':uid},'channel:read:redemptions')['data']
        return [{'id':r['id'],'title':r['title'],'cost':r['cost'],'enabled':r['is_enabled']} for r in rows]

    def tick(self):
        for uid in self.store.credential_users():
            if self.stopping.is_set():
                return
            try:
                rows = self.get(uid,'streams',{'user_id':uid})['data']
                self.store.observe_stream(uid,rows[0] if rows else None)
            except Exception:
                self.store.stream_unavailable(uid)

    def start(self):
        def run():
            while not self.stopping.is_set():
                try:
                    self.tick()
                except Exception:
                    pass
                self.stopping.wait(60)
        self.thread=threading.Thread(target=run,daemon=True,name='cloud-stream-state')
        self.thread.start()

    def stop(self):
        self.stopping.set()
        if self.thread:
            self.thread.join(timeout=2)
