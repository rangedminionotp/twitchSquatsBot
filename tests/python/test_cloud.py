"""Cloud security-boundary tests; no real Twitch credentials or network calls."""
import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from unittest.mock import Mock, patch

try:
    from cryptography.fernet import Fernet
except ImportError:
    Fernet = None

if Fernet:
    from squat_capture.cloud.store import Store, digest
    from squat_capture.cloud.server import Settings, make_handler, ThreadingHTTPServer
    from squat_capture.cloud.oauth import TwitchOAuth
    from squat_capture.cloud.community import Community


@unittest.skipUnless(Fernet, 'Install requirements-cloud.txt to run cloud tests')
class CloudTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.key = Fernet.generate_key()
        self.store = Store(Path(self.directory.name) / 'cloud.sqlite3', self.key)
        self.a = self.store.login({'user_id':'11','login':'alice'}, {'access_token':'TEST-ACCESS-A','refresh_token':'TEST-REFRESH-A'})
        self.b = self.store.login({'user_id':'22','login':'bob'}, {'access_token':'TEST-ACCESS-B'})
        self.settings = Settings('http://127.0.0.1:8090','test-client','test-secret',self.key.decode(),str(self.store.path),
                                 development=True,community_owner_id='11')
        self.now = [1_800_000_000.0]
        self.community = Community(self.store,'11',clock=lambda:self.now[0])
        self.oauth = Mock()
        self.oauth.authorize_url.side_effect = lambda state: 'https://id.twitch.tv/oauth2/authorize?state='+state
        self.oauth.exchange.return_value = ({'user_id':'11','login':'alice'}, {'access_token':'TEST-ACCESS-A'})
        self.server = ThreadingHTTPServer(('127.0.0.1',0), make_handler(self.settings,self.store,self.oauth,
                                                                         community=self.community))
        self.thread = threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.addCleanup(self.close_server)

    def close_server(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join()

    def call(self, path, method='GET', token=None, body=None, headers=None):
        request_headers = {'Host':'127.0.0.1:8090'}
        if token:
            request_headers['Cookie'] = 'sc_session='+token
        if body is not None:
            body = json.dumps(body)
            request_headers.update({'Content-Type':'application/json','Origin':self.settings.origin})
            if token and self.store.session(token):
                request_headers['X-CSRF-Token'] = self.store.session(token)['csrf']
        request_headers.update(headers or {})
        connection = http.client.HTTPConnection(*self.server.server_address, timeout=3)
        try:
            connection.request(method,path,body=body,headers=request_headers)
            response = connection.getresponse()
            return response.status, response.read(), response.getheaders()
        finally:
            connection.close()

    def test_login_required_and_no_local_endpoints(self):
        self.assertEqual(self.call('/api/me')[0],401)
        self.assertEqual(self.call('/api/owed','POST',body={'owed':4})[0],401)
        for path in ('/api/settings','/squat-progress','/static/../config.json','/assets/../server.py'):
            self.assertEqual(self.call(path)[0],404)

    def test_counters_isolated_and_body_cannot_choose_user(self):
        self.assertEqual(self.call('/api/owed','POST',self.a,{'owed':42})[0],200)
        self.assertEqual(self.store.profile('11')['owed'],42)
        self.assertEqual(self.store.profile('22')['owed'],0)
        self.assertEqual(self.call('/api/owed','POST',self.a,{'owed':9,'user_id':'22'})[0],400)
        self.assertEqual(json.loads(self.call('/api/me?user_id=22',token=self.a)[1])['user']['id'],'11')

    def test_csrf_and_origin_required(self):
        for headers in ({'Origin':'https://evil.invalid'},{'Origin':''},{'X-CSRF-Token':''}):
            self.assertEqual(self.call('/api/owed','POST',self.a,{'owed':9},headers)[0],403)
        self.assertEqual(self.store.profile('11')['owed'],0)

    def test_rules_api_uses_session_owner(self):
        values = dict(reward_id='r1',reward_reps=12,sub_reps=5,gift_reps=6,bits_unit=100,bits_reps=1)
        self.assertEqual(self.call('/api/rules','POST',self.a,values)[0],200)
        self.assertEqual(self.store.rules('11')['reward_id'],'r1')
        self.assertEqual(self.store.rules('22')['reward_id'],'')
        self.assertEqual(self.call('/api/rules','POST',self.a,{**values,'user_id':'22'})[0],400)
        self.assertEqual(self.call('/api/rules','POST',self.a,values,{'X-CSRF-Token':''})[0],403)
        data = json.loads(self.call('/api/me',token=self.a)[1])
        self.assertEqual(data['rules']['sub_reps'],5)
        self.assertEqual(data['queue'],[])
        self.assertFalse(data['event_listener']['enabled'])
        self.assertFalse(data['events_available'])

    def test_listener_requires_server_opt_in_and_session_owner(self):
        self.assertEqual(self.call('/api/listener','POST',self.a,{'enabled':True})[0],409)
        self.store.enable_listener('11',True)
        self.store.enable_listener('22',True)
        self.assertEqual(self.call('/api/listener','POST',self.a,{'enabled':False})[0],200)
        self.assertFalse(self.store.listener('11')['enabled'])
        self.assertTrue(self.store.listener('22')['enabled'])
        self.assertEqual(self.call('/api/listener','POST',self.a,{'enabled':0})[0],400)
        self.assertEqual(self.call('/api/listener','POST',self.a,{'enabled':False,'user_id':'22'})[0],400)

    def test_eventsub_disabled_without_server_secret(self):
        self.assertEqual(self.call('/eventsub','POST',body={})[0],503)

    def test_free_capture_donation_and_delete_http(self):
        status,raw,_=self.call('/api/capture/free','POST',self.a,{'request_id':'free','target':2})
        self.assertEqual(status,200);run=json.loads(raw)['challenge']['id']
        self.assertEqual(self.call('/api/capture/end','POST',self.b,{'run_id':run})[0],409)
        self.assertEqual(self.call('/api/capture/end','POST',self.a,{'run_id':run})[0],200)
        values=dict(enabled=False,unit='1',squats=2,currency='USD',token='TEST-PRIVATE-TOKEN',channel='',clear_token=False)
        status,raw,_=self.call('/api/donations','POST',self.a,{'source':'streamlabs','settings':values})
        self.assertEqual(status,200);self.assertNotIn(b'TEST-PRIVATE-TOKEN',raw)
        self.assertEqual(self.call('/api/account/delete','POST',self.a,{'confirm':'no'})[0],400)
        self.assertEqual(self.call('/api/account/delete','POST',self.a,{'confirm':'DELETE'},{'X-CSRF-Token':''})[0],403)
        self.assertEqual(self.call('/api/account/delete','POST',self.a,{'confirm':'DELETE'})[0],200)
        self.assertEqual(self.call('/api/me',token=self.a)[0],401)
        self.assertEqual(self.call('/api/me',token=self.b)[0],200)

    def test_challenge_http_protocol_and_tenant_boundaries(self):
        self.store.save_rules('11',{**self.store.rules('11'),'reward_id':'reward'})
        self.store.receive_event('11','channel.channel_points_custom_reward_redemption.add','redeem',
            {'id':'redeem','broadcaster_user_id':'11','reward':{'id':'reward'}})
        status, raw, _ = self.call('/api/challenge/start','POST',self.a,{'request_id':'start'})
        self.assertEqual(status,200)
        run = json.loads(raw)['challenge']['id']
        self.assertEqual(self.call('/api/capture/claim','POST',self.b,{'run_id':run,'page_id':'page'})[0],409)
        _, raw, _ = self.call('/api/capture/claim','POST',self.a,{'run_id':run,'page_id':'page'})
        lease = json.loads(raw)['lease']
        payload = {'run_id':run,'lease':lease,'count':2}
        self.assertEqual(self.call('/api/capture/progress','POST',self.a,payload,{'X-CSRF-Token':''})[0],403)
        self.assertEqual(self.call('/api/capture/progress','POST',self.a,{**payload,'user_id':'22'})[0],400)
        self.assertEqual(self.call('/api/capture/progress','POST',body=payload)[0],401)
        for _ in range(2):
            self.assertEqual(self.call('/api/capture/progress','POST',self.a,payload)[0],200)
        self.assertEqual(self.store.profile('11')['lifetime'],2)
        self.assertEqual(self.call('/api/challenge/pause','POST',self.a,{'run_id':run})[0],200)
        self.assertEqual(self.call('/api/capture/progress','POST',self.a,{**payload,'count':3})[0],409)
        data = json.loads(self.call('/api/me',token=self.a)[1])
        self.assertEqual(data['challenge']['status'],'paused')
        self.assertNotIn('lease',data['challenge'])

    def test_empty_challenge_returns_actionable_conflict(self):
        status, raw, _ = self.call('/api/challenge/start','POST',self.a,{'request_id':'empty'})
        self.assertEqual(status,409)
        self.assertIn('No queued challenge',json.loads(raw)['error'])

    def test_camera_routes_and_scoped_security_policy(self):
        self.assertEqual(self.call('/camera')[0],303)
        status, body, headers = self.call('/camera',token=self.a)
        self.assertEqual(status,200)
        self.assertIn(b'Capture challenge',body)
        camera_policy = dict(headers)['Content-Security-Policy']
        self.assertIn('wasm-unsafe-eval',camera_policy)
        self.assertNotIn("'unsafe-eval'",camera_policy)
        self.assertIn('camera=(self)',dict(headers)['Permissions-Policy'])
        _, _, headers = self.call('/')
        self.assertNotIn('cdn.jsdelivr.net',dict(headers)['Content-Security-Policy'])
        for asset in ('camera.js','capture-core.mjs','pose.mjs','camera.css','viewer.js','viewer-core.mjs','viewer.css'):
            self.assertEqual(self.call('/assets/'+asset)[0],200)
        self.assertEqual(self.call('/assets/../camera.html')[0],404)

    def test_capture_run_inspection_requires_owner(self):
        self.store.save_rules('11',{**self.store.rules('11'),'reward_id':'reward'})
        self.store.receive_event('11','channel.channel_points_custom_reward_redemption.add','inspect',
            {'id':'inspect','broadcaster_user_id':'11','reward':{'id':'reward'}})
        _, raw, _ = self.call('/api/challenge/start','POST',self.a,{'request_id':'inspect'})
        run = json.loads(raw)['challenge']['id']
        path='/api/capture/run?id='+run
        self.assertEqual(self.call(path)[0],401)
        self.assertEqual(self.call(path,token=self.b)[0],404)
        status, raw, _ = self.call(path,token=self.a)
        self.assertEqual(status,200)
        self.assertNotIn('lease',json.loads(raw)['run'])

    def test_reject_host_and_invalid_numbers(self):
        self.assertEqual(self.call('/',headers={'Host':'evil.invalid'})[0],400)
        for value in (-1,1.2,True,'42',1000000001):
            self.assertEqual(self.call('/api/owed','POST',self.a,{'owed':value})[0],400)

    def test_overlay_read_only_rotatable_and_minimal(self):
        self.store.set_owed('11',37)
        token = self.store.rotate_overlay('11')
        status, raw, _ = self.call('/api/overlay/'+token)
        self.assertEqual(status,200)
        self.assertEqual(json.loads(raw),{'owed':37,'lifetime':0,'stream':{'state':'checking','completed':0}})
        self.assertEqual(self.call('/api/owed','POST',token,{'owed':12})[0],401)
        self.assertEqual(self.call('/overlay/'+token)[0],200)
        new = self.store.rotate_overlay('11')
        self.assertEqual(self.call('/api/overlay/'+token)[0],404)
        self.assertEqual(self.call('/api/overlay/'+new)[0],200)
        bob = self.store.rotate_overlay('22')
        self.assertEqual(self.store.overlay(bob)['owed'],0)

    def test_tokens_encrypted_sessions_and_overlay_hashed(self):
        token = self.store.rotate_overlay('11')
        with self.store.connection() as db:
            encrypted = db.execute('SELECT credentials FROM users WHERE id=?',('11',)).fetchone()[0]
            self.assertNotIn(b'TEST-ACCESS-A',encrypted)
            self.assertIn(b'TEST-ACCESS-A',Fernet(self.key).decrypt(encrypted))
            self.assertEqual(db.execute('SELECT hash FROM overlays').fetchone()[0],digest(token))
            self.assertIsNotNone(db.execute('SELECT hash FROM sessions WHERE hash=?',(digest(self.a),)).fetchone())
        raw = self.store.path.read_bytes()
        for secret in ('TEST-ACCESS-A','TEST-REFRESH-A',self.a,token):
            self.assertNotIn(secret.encode(),raw)

    def test_sessions_expire_logout_and_survive_restart(self):
        restarted = Store(self.store.path,self.key)
        self.assertEqual(restarted.session(self.a)['user_id'],'11')
        self.assertEqual(self.call('/api/logout','POST',self.a,{})[0],200)
        self.assertEqual(self.call('/api/me',token=self.a)[0],401)
        with self.store.connection() as db:
            db.execute('UPDATE sessions SET expires=0')
        self.assertIsNone(self.store.session(self.b))

    def test_state_bound_single_use_and_expired(self):
        state,binding = self.store.start_oauth()
        self.assertFalse(self.store.consume_oauth(state,'wrong-browser'))
        self.assertEqual(self.store.consume_oauth(state,binding),'admin')
        self.assertFalse(self.store.consume_oauth(state,binding))
        state,binding = self.store.start_oauth('viewer')
        self.assertEqual(self.store.consume_oauth(state,binding),'viewer')
        with self.assertRaises(ValueError):
            self.store.start_oauth('unknown')
        state,binding = self.store.start_oauth()
        with self.store.connection() as db:
            db.execute('UPDATE oauth_states SET expires=0')
        self.assertFalse(self.store.consume_oauth(state,binding))

    def test_sessions_have_explicit_roles(self):
        viewer = self.store.login({'user_id':'33','login':'viewer'}, {'access_token':'TEST'}, role='viewer')
        self.assertEqual(self.store.session(self.a)['role'],'admin')
        self.assertEqual(self.store.session(viewer)['role'],'viewer')
        self.assertNotIn('33',self.store.credential_users())
        with self.assertRaisesRegex(ValueError,'no stored Twitch credentials'):
            self.store.credential_snapshot('33')
        with self.assertRaises(ValueError):
            self.store.login({'user_id':'44','login':'invalid'}, {'access_token':'TEST'}, role='owner')

    def test_viewer_login_never_overwrites_broadcaster_credentials(self):
        self.store.login({'user_id':'33','login':'viewer'}, {'access_token':'VIEWER-ONLY'}, role='viewer')
        admin = self.store.login({'user_id':'33','login':'renamed'}, {'access_token':'ADMIN'}, role='admin')
        self.assertEqual(self.store.session(admin)['role'],'admin')
        self.assertEqual(self.store.credential_snapshot('33')[1]['access_token'],'ADMIN')
        self.store.login({'user_id':'33','login':'renamed'}, {'access_token':'NEW-VIEWER'}, role='viewer')
        self.assertEqual(self.store.credential_snapshot('33')[1]['access_token'],'ADMIN')

    def test_oauth_callback_browser_binding_and_cookie(self):
        status,_,headers = self.call('/auth/twitch')
        self.assertEqual(status,303)
        state = parse_qs(urlsplit(dict(headers)['Location']).query)['state'][0]
        cookie = dict(headers)['Set-Cookie'].split(';')[0]
        path = '/auth/callback?code=test-code&state='+state
        self.assertEqual(self.call(path)[0],400)
        self.oauth.exchange.assert_not_called()
        status,_,headers = self.call(path,headers={'Cookie':cookie})
        self.assertEqual(status,303)
        self.assertEqual(dict(headers)['Location'],'/')
        session_headers = [v for k,v in headers if k=='Set-Cookie' and v.startswith('sc_session=')]
        self.assertEqual(len(session_headers),1)
        self.assertIn('HttpOnly',session_headers[0]); self.assertIn('SameSite=Lax',session_headers[0])
        self.assertEqual(self.call(path,headers={'Cookie':cookie})[0],400)

    def test_viewer_login_creates_limited_session(self):
        status,_,headers = self.call('/viewer/login')
        self.assertEqual(status,303)
        state = parse_qs(urlsplit(dict(headers)['Location']).query)['state'][0]
        oauth_cookie = dict(headers)['Set-Cookie'].split(';')[0]
        status,_,headers = self.call('/auth/callback?code=test-code&state='+state,
                                     headers={'Cookie':oauth_cookie})
        self.assertEqual(status,303)
        self.assertEqual(dict(headers)['Location'],'/viewer')
        raw_session = next(value for key,value in headers if key == 'Set-Cookie' and value.startswith('sc_session='))
        viewer_token = raw_session.split(';',1)[0].split('=',1)[1]
        self.assertEqual(self.store.session(viewer_token)['role'],'viewer')
        self.assertEqual(self.call('/api/me',token=viewer_token)[0],403)
        self.assertEqual(self.call('/api/owed','POST',viewer_token,{'owed':10})[0],403)
        self.assertEqual(self.call('/camera',token=viewer_token)[0],303)

    def test_viewer_shell_is_public_and_camera_scoped(self):
        status,body,headers = self.call('/viewer')
        self.assertEqual(status,200)
        self.assertIn(b'Video and pose landmarks stay in your browser',body)
        self.assertIn('camera=(self)',dict(headers)['Permissions-Policy'])

    def test_viewer_contribution_api_uses_session_identity(self):
        viewer = self.store.login({'user_id':'33','login':'charlie'}, {'access_token':'TEST'}, role='viewer')
        status,raw,_ = self.call('/api/viewer',token=viewer)
        self.assertEqual(status,200)
        data = json.loads(raw)
        self.assertEqual(data['user'],{'login':'charlie'})
        self.assertEqual(data['community']['daily_limit'],100)
        status,raw,_ = self.call('/api/viewer/start','POST',viewer,{})
        self.assertEqual(status,200)
        run = json.loads(raw)['run']
        self.assertEqual(run['target'],20)
        calibration = {'run_id':run['id'],'standing_angle':165,'squat_angle':95,'duration_ms':3000}
        self.assertEqual(self.call('/api/viewer/calibrate','POST',viewer,calibration)[0],200)
        self.now[0] += 1
        progress = {'run_id':run['id'],'sequence':1,'count':1,'elapsed_ms':1000}
        self.assertEqual(self.call('/api/viewer/progress','POST',viewer,progress)[0],200)
        self.assertEqual(self.call('/api/viewer/progress','POST',viewer,progress)[0],200)
        data = json.loads(self.call('/api/viewer',token=viewer)[1])
        self.assertEqual(data['community']['today'],1)
        self.assertEqual(json.loads(self.call('/api/community')[1])['community_total'],1)
        self.assertEqual(self.call('/api/owed','POST',viewer,{'owed':10})[0],403)

    def test_viewer_api_rejects_unexpected_fields_and_impossible_speed(self):
        viewer = self.store.login({'user_id':'33','login':'charlie'}, {'access_token':'TEST'}, role='viewer')
        _,raw,_ = self.call('/api/viewer/start','POST',viewer,{})
        run = json.loads(raw)['run']
        calibration = {'run_id':run['id'],'standing_angle':165,'squat_angle':95,'duration_ms':3000}
        self.assertEqual(self.call('/api/viewer/calibrate','POST',viewer,calibration)[0],200)
        self.now[0] += 1
        too_fast = {'run_id':run['id'],'sequence':1,'count':2,'elapsed_ms':500}
        self.assertEqual(self.call('/api/viewer/progress','POST',viewer,too_fast)[0],409)
        flags = json.loads(self.call('/api/community/admin',token=self.a)[1])['flags']
        self.assertEqual(flags[0]['viewer'],'charlie')
        self.assertEqual(flags[0]['hits'],1)
        self.assertEqual(self.call('/api/viewer/progress','POST',viewer,{**too_fast,'user_id':'22'})[0],400)

    def test_owner_can_review_and_revoke_viewer_contribution(self):
        viewer = self.store.login({'user_id':'33','login':'charlie'}, {'access_token':'TEST'}, role='viewer')
        _,raw,_ = self.call('/api/viewer/start','POST',viewer,{})
        run = json.loads(raw)['run']
        calibration = {'run_id':run['id'],'standing_angle':165,'squat_angle':95,'duration_ms':3000}
        self.call('/api/viewer/calibrate','POST',viewer,calibration)
        self.now[0] += 1
        self.call('/api/viewer/progress','POST',viewer,{'run_id':run['id'],'sequence':1,'count':1,'elapsed_ms':1000})
        status,raw,_ = self.call('/api/community/admin',token=self.a)
        self.assertEqual(status,200)
        contribution = json.loads(raw)['contributions'][0]
        self.assertEqual(contribution['viewer'],'charlie')
        status,raw,_ = self.call('/api/community/revoke','POST',self.a,{'contribution_id':contribution['id']})
        self.assertEqual(status,200)
        self.assertEqual(json.loads(raw)['community_total'],0)
        self.assertEqual(json.loads(self.call('/api/viewer',token=viewer)[1])['community']['today'],0)
        self.assertEqual(self.call('/api/community/revoke','POST',viewer,{'contribution_id':contribution['id']})[0],403)

    def test_profile_and_response_security_headers(self):
        status,body,headers = self.call('/api/me',token=self.a)
        self.assertEqual(status,200)
        self.assertNotIn(b'TEST-ACCESS',body)
        self.assertNotIn(b'credentials',body)
        self.assertEqual(dict(headers)['Cache-Control'],'no-store')
        self.assertEqual(dict(headers)['Referrer-Policy'],'no-referrer')

    def test_static_routes_are_allowlisted(self):
        for path,mime in [('/', 'text/html'),('/assets/cloud.js','text/javascript'),('/assets/cloud.css','text/css')]:
            status,body,headers = self.call(path)
            self.assertEqual(status,200)
            self.assertTrue(body)
            self.assertTrue(dict(headers)['Content-Type'].startswith(mime))
        self.assertEqual(self.call('/assets/server.py')[0],404)

    def test_broadcaster_page_includes_community_moderation(self):
        status,body,_ = self.call('/')
        self.assertEqual(status,200)
        self.assertIn(b'id="communityAdmin"',body)
        self.assertIn(b'/viewer',body)

    def test_oauth_failures_do_not_leak_provider_response(self):
        state,binding = self.store.start_oauth()
        self.oauth.exchange.side_effect = RuntimeError('TEST-SENSITIVE-PROVIDER-RESPONSE')
        status,body,_ = self.call('/auth/callback?state='+state+'&code=test',headers={'Cookie':'sc_oauth='+binding})
        self.assertEqual(status,502)
        self.assertNotIn(b'TEST-SENSITIVE',body)

    def test_settings_require_tls_and_explicit_secrets(self):
        for origin,dev in [('http://public.invalid',False),('http://public.invalid',True),('https://example.com/',False)]:
            with self.assertRaises(ValueError):
                Settings(origin,'id','secret',self.key.decode(),'unused',development=dev)
        with self.assertRaises(ValueError):
            Settings('https://example.com','id','','','unused')

    def test_exchange_validates_client_before_trusting_identity(self):
        token_response = {'access_token':'test','refresh_token':'refresh','expires_in':10}
        identity_response = {'client_id':'wrong','user_id':'11','login':'alice'}
        with patch('squat_capture.cloud.oauth.json_request',side_effect=[token_response,identity_response]):
            with self.assertRaises(ValueError):
                TwitchOAuth('expected','secret','https://example.com/auth/callback').exchange('code')


if __name__ == '__main__':
    unittest.main()
