"""Token lifecycle tests with mocked provider, fixed clock and isolated storage."""
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock
from urllib.error import HTTPError, URLError

try:
    from cryptography.fernet import Fernet
except ImportError:
    Fernet = None
if Fernet:
    from squat_capture.cloud.store import Store
    from squat_capture.cloud.tokens import TokenService


def http_error(code):
    return HTTPError('https://provider.invalid',code,'TEST ONLY',{},None)


@unittest.skipUnless(Fernet,'Install requirements-cloud.txt')
class TokenTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name)/'db.sqlite3',Fernet.generate_key())
        self.session = self.store.login({'user_id':'11','login':'alice'},dict(access_token='old-access',refresh_token='old-refresh',expires_in=3600))
        self.other = self.store.login({'user_id':'22','login':'bob'},dict(access_token='bob-access',refresh_token='bob-refresh',expires_in=3600))
        self.oauth = Mock(client_id='test-client')
        self.identity = dict(client_id='test-client',user_id='11',expires_in=7200,scopes=['channel:read:redemptions'])
        self.oauth.validate.return_value = self.identity
        self.oauth.refresh.return_value = dict(access_token='new-access',refresh_token='new-refresh',expires_in=7200)
        self.now = 100
        self.service = TokenService(self.store,self.oauth,clock=lambda:self.now)

    def test_validate_on_start_and_before_hour(self):
        self.assertEqual(self.service.check('11'),'connected')
        self.now += 3200
        self.service.check('11')
        self.assertEqual(self.oauth.validate.call_count,1)
        self.now += 100
        self.service.check('11')
        self.assertEqual(self.oauth.validate.call_count,2)
        self.oauth.refresh.assert_not_called()
        restarted = TokenService(self.store,self.oauth,clock=lambda:self.now)
        restarted.check('11')
        self.assertEqual(self.oauth.validate.call_count,3)

    def test_401_refreshes_and_persists_rotation(self):
        self.oauth.validate.side_effect = [http_error(401),self.identity]
        self.assertEqual(self.service.check('11'),'connected')
        self.oauth.refresh.assert_called_once_with('old-refresh')
        _,tokens = self.store.credential_snapshot('11')
        self.assertEqual(tokens['refresh_token'],'new-refresh')
        self.assertEqual(tokens['scopes'],self.identity['scopes'])
        self.assertIsNotNone(self.store.session(self.session))

    def test_fresh_login_invalidates_cached_validation(self):
        self.service.check('11')
        self.store.login({'user_id':'11','login':'alice'}, {'access_token':'fresh-access','refresh_token':'fresh-refresh'})
        self.service.invalidate('11')
        self.service.check('11')
        self.assertEqual(self.oauth.validate.call_count,2)
        self.oauth.validate.assert_called_with('fresh-access')

    def test_concurrent_checks_refresh_once(self):
        self.oauth.validate.side_effect = [http_error(401),self.identity]
        with ThreadPoolExecutor(max_workers=6) as pool:
            result = list(pool.map(lambda _:self.service.check('11'),range(10)))
        self.assertEqual(set(result),{'connected'})
        self.oauth.refresh.assert_called_once()

    def test_revoke_only_target_user_and_preserve_counters(self):
        self.store.set_owed('11',42)
        self.oauth.validate.side_effect = http_error(401)
        self.oauth.refresh.side_effect = http_error(400)
        self.assertEqual(self.service.check('11'),'reconnect_required')
        self.assertIsNone(self.store.session(self.session))
        self.assertIsNotNone(self.store.session(self.other))
        self.assertEqual(self.store.profile('11')['owed'],42)
        self.assertEqual(self.store.credential_snapshot('11')[1],{})
        with self.assertRaises(ValueError):
            self.store.receive_event('11','channel.subscribe','new',{'broadcaster_user_id':'11','is_gift':False})

    def test_outage_does_not_delete_credentials_or_sessions(self):
        for error in (http_error(429),http_error(500),URLError('test timeout')):
            self.oauth.validate.side_effect = error
            self.now += 61
            self.assertEqual(self.service.check('11'),'temporarily_unavailable')
            self.assertEqual(self.store.credential_snapshot('11')[1]['access_token'],'old-access')
            self.assertIsNotNone(self.store.session(self.session))
        self.oauth.refresh.assert_not_called()

    def test_refresh_outage_retry_and_no_tight_loop(self):
        self.oauth.validate.side_effect = http_error(401)
        self.oauth.refresh.side_effect = http_error(503)
        self.assertEqual(self.service.check('11'),'temporarily_unavailable')
        self.service.check('11')
        self.oauth.refresh.assert_called_once()
        self.now += 61
        self.service.check('11')
        self.assertEqual(self.oauth.refresh.call_count,2)

    def test_rotated_token_survives_validation_outage(self):
        self.oauth.validate.side_effect = [http_error(401),http_error(503)]
        self.assertEqual(self.service.check('11'),'temporarily_unavailable')
        self.assertEqual(self.store.credential_snapshot('11')[1]['refresh_token'],'new-refresh')

    def test_identity_mismatch_invalidates_without_cross_user_write(self):
        self.oauth.validate.return_value = {**self.identity,'user_id':'22'}
        self.assertEqual(self.service.check('11'),'reconnect_required')
        self.assertEqual(self.store.credential_snapshot('22')[1]['access_token'],'bob-access')

    def test_old_revocation_cannot_overwrite_new_login(self):
        fresh = []
        def invalid_refresh(_token):
            fresh.append(self.store.login({'user_id':'11','login':'alice'},dict(access_token='fresh-login',refresh_token='fresh-refresh')))
            raise http_error(400)
        self.oauth.validate.side_effect = http_error(401)
        self.oauth.refresh.side_effect = invalid_refresh
        self.assertEqual(self.service.check('11'),'checking')
        self.assertEqual(self.store.credential_snapshot('11')[1]['access_token'],'fresh-login')
        self.assertIsNotNone(self.store.session(fresh[0]))

    def test_old_refresh_cannot_overwrite_new_login(self):
        def refresh(_token):
            self.store.login({'user_id':'11','login':'alice'},dict(access_token='fresh-login',refresh_token='fresh-refresh'))
            return dict(access_token='stale-refresh',refresh_token='stale-token',expires_in=100)
        self.oauth.validate.side_effect = http_error(401)
        self.oauth.refresh.side_effect = refresh
        self.assertEqual(self.service.check('11'),'checking')
        self.assertEqual(self.store.credential_snapshot('11')[1]['access_token'],'fresh-login')
