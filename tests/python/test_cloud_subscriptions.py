"""Subscription reconciliation with a fake provider; never calls Twitch."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

try:
    from cryptography.fernet import Fernet
except ImportError:
    Fernet = None
if Fernet:
    from squat_capture.cloud.store import Store
    from squat_capture.cloud.subscriptions import SubscriptionService, EventSubAPI, SCOPES
    from squat_capture.cloud.oauth import TwitchOAuth
    from squat_capture.cloud.server import Settings


@unittest.skipUnless(Fernet, 'Install requirements-cloud.txt')
class SubscriptionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.key = Fernet.generate_key()
        self.store = Store(Path(self.tmp.name)/'cloud.sqlite3', self.key)
        for uid in ('11','22'):
            self.store.login({'user_id':uid,'login':'test'+uid}, {'access_token':'fake','scopes':list(SCOPES.values())})
        self.rules = {**self.store.rules('11'), 'sub_reps':5}
        self.store.save_rules('11',self.rules)
        self.store.enable_listener('11',True)
        self.callback = 'https://example.test/eventsub'
        self.api, self.tokens = Mock(), Mock()
        self.tokens.check.return_value = 'connected'
        self.api.list.return_value = []
        self.api.create.side_effect = lambda uid,kind,*args: self.remote(uid,kind)
        self.service = SubscriptionService(self.store,self.tokens,self.api,self.callback,'test-secret')

    def remote(self, uid='11', kind='channel.subscribe', status='webhook_callback_verification_pending', remote_id='remote-1'):
        return {'id':remote_id,'type':kind,'status':status,'version':'1',
                'condition':{'broadcaster_user_id':uid},'transport':{'method':'webhook','callback':self.callback}}

    def test_create_then_restart_adopts_without_duplicate(self):
        self.service.tick()
        self.api.create.assert_called_once()
        self.assertEqual(self.store.listener('11')['message'],'pending_or_attention')
        self.api.list.return_value = [self.remote(status='enabled')]
        self.service.tick()
        self.api.create.assert_called_once()
        self.assertEqual(self.store.listener('11')['message'],'listening')
        self.assertFalse(self.store.listener('22')['enabled'])

    def test_callback_before_create_response_preserves_enabled(self):
        def create(*args):
            self.assertTrue(self.store.accept_subscription(self.remote(),'webhook_callback_verification'))
            return self.remote()
        self.api.create.side_effect = create
        self.service.tick()
        self.assertEqual(self.store.listener('11')['message'],'listening')

    def test_stop_deletes_only_owned_callback_and_user(self):
        self.service.tick()
        foreign = self.remote(remote_id='foreign'); foreign['transport']['callback'] = 'https://other.test/eventsub'
        self.api.list.return_value = [self.remote(),self.remote(uid='33'),foreign]
        self.store.enable_listener('11',False)
        self.service.tick()
        self.api.delete.assert_called_once_with('remote-1')
        self.assertEqual(self.store.subscriptions('11'),[])
        self.assertEqual(self.store.listener('11')['message'],'disabled')

    def test_inventory_failure_does_not_create_or_delete(self):
        self.api.list.side_effect = TimeoutError()
        self.service.tick()
        self.api.create.assert_not_called(); self.api.delete.assert_not_called()
        self.assertEqual(self.store.listener('11')['message'],'service_unavailable')

    def test_stop_without_subscriptions_does_not_stay_stopping(self):
        self.store.enable_listener('11',False)
        self.service.tick()
        self.api.list.assert_not_called()
        self.assertEqual(self.store.listener('11')['message'],'disabled')

    def test_missing_permissions_still_removes_disabled_rules(self):
        self.service.tick()
        self.api.list.return_value = [self.remote()]
        previous, tokens = self.store.credential_snapshot('11')
        self.store.save_credentials_if_current('11',previous,{**tokens,'scopes':[]},'connected')
        self.store.save_rules('11',{**self.rules,'sub_reps':0,'bits_reps':2})
        self.service.tick()
        self.api.delete.assert_called_once_with('remote-1')
        self.assertEqual(self.store.listener('11')['message'],'missing_permission')
        self.assertEqual(self.api.create.call_count,1)

    def test_revoked_record_not_resurrected_by_stale_inventory(self):
        self.service.tick()
        self.assertTrue(self.store.accept_subscription(self.remote(),'revocation'))
        self.api.list.return_value = [self.remote(status='enabled')]
        self.service.tick()
        self.assertEqual(self.store.subscriptions('11')[0]['status'],'revoked')
        self.assertFalse(self.store.accept_subscription(self.remote(),'notification'))

    def test_unexpected_callback_and_id_rejected(self):
        self.service.tick()
        self.assertFalse(self.store.accept_subscription(self.remote(remote_id='other'),'webhook_callback_verification'))
        sub = self.remote(); sub['transport']['callback']='https://other.test/eventsub'
        self.assertFalse(self.store.accept_subscription(sub,'webhook_callback_verification'))

    def test_existing_remote_replacement_adopted(self):
        self.service.tick()
        self.api.list.return_value = [self.remote(status='enabled',remote_id='replacement')]
        self.service.tick()
        self.assertEqual(self.store.subscriptions('11')[0]['remote_id'],'replacement')
        self.assertEqual(self.api.create.call_count,1)

    def test_opt_in_requires_https_secret_and_standard_port(self):
        for origin, dev, secret in [('http://127.0.0.1:8090',True,'x'*32),('https://example.test',False,''),('https://example.test:8090',False,'x'*32)]:
            with self.assertRaises(ValueError):
                Settings(origin,'id','secret',self.key.decode(),'unused',development=dev,eventsub_secret=secret,enable_events=True)
        Settings('https://example.test','id','secret',self.key.decode(),'unused',eventsub_secret='x'*32,enable_events=True)

    def test_event_scopes_are_explicit(self):
        oauth = TwitchOAuth('id','secret','https://example.test/auth/callback')
        self.assertNotIn('scope',parse_qs(urlsplit(oauth.authorize_url('state')).query))
        query = parse_qs(urlsplit(oauth.authorize_url('state',events=True)).query)
        self.assertEqual(set(query['scope'][0].split()),set(SCOPES.values()))

    def test_rate_limit_does_not_busy_retry(self):
        self.api.create.side_effect = HTTPError('test',429,'limited',{},None)
        self.service.tick()
        self.api.create.assert_called_once()
        self.assertEqual(self.store.listener('11')['message'],'rate_limited')

    def test_inventory_pagination_and_delete_404(self):
        api = EventSubAPI('id','secret')
        api.request = Mock(side_effect=[{'data':[1],'pagination':{'cursor':'next'}},{'data':[2]}])
        self.assertEqual(api.list(),[1,2])
        api.request.assert_called_with(query={'after':'next'})
        api.request.side_effect = HTTPError('test',404,'missing',{},None)
        api.delete('deleted')
