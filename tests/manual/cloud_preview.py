"""Isolated UI fixture. Fake OAuth, loopback only, ephemeral DB; NEVER deploy."""
import tempfile
from pathlib import Path
from urllib.parse import urlencode
from cryptography.fernet import Fernet
from squat_capture.cloud.store import Store
from squat_capture.cloud.server import Settings, make_handler, ThreadingHTTPServer


class FakeOAuth:
    def authorize_url(self,state):return '/auth/callback?'+urlencode({'state':state,'code':'fake-test-only'})
    def exchange(self,code):return {'user_id':'991','login':'UI_TEST_ONLY'},{'access_token':'fake-test-only'}


if __name__=='__main__':
    with tempfile.TemporaryDirectory() as directory:
        key=Fernet.generate_key()
        store=Store(Path(directory)/'ui.sqlite3',key)
        settings=Settings('http://127.0.0.1:18090','fake','fake',key.decode(),str(store.path),development=True)
        server=ThreadingHTTPServer(('127.0.0.1',18090),make_handler(settings,store,FakeOAuth()))
        print('TEST ONLY: http://127.0.0.1:18090 — fake account, ephemeral data, no platform workers',flush=True)
        try:server.serve_forever()
        except KeyboardInterrupt:pass
        finally:server.server_close()
