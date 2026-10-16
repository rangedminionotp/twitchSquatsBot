import tempfile
import unittest
from pathlib import Path
try:
    from cryptography.fernet import Fernet
except ImportError:
    Fernet=None
if Fernet:
    from squat_capture.cloud.store import Store
    from squat_capture.cloud.challenges import Challenges
    from squat_capture.cloud.donations import Donations
    from squat_capture.cloud.http_safety import RateLimiter
    from squat_capture.cloud.backup import backup


@unittest.skipUnless(Fernet,'Install cloud requirements')
class CloudSafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name);self.key=Fernet.generate_key()
        self.store=Store(self.path/'source.sqlite3',self.key)
        self.session=self.store.login({'user_id':'11','login':'alice'},{'access_token':'fake'})
        self.store.login({'user_id':'22','login':'bob'},{'access_token':'fake'})

    def test_account_deletion_is_scoped_and_invalidates_links(self):
        capture=Challenges(self.store);donations=Donations(self.store)
        capture.start('11','free',2)
        link=self.store.rotate_overlay('11')
        self.store.observe_stream('11',None)
        donations.save('11','streamlabs',dict(enabled=False,unit='1',squats=1,currency='USD',token='fake',channel='',clear_token=False))
        self.store.delete_account('11')
        self.assertIsNone(self.store.session(self.session));self.assertIsNone(self.store.overlay(link))
        self.assertEqual(self.store.credential_users(),['22'])
        self.assertEqual(self.store.profile('22')['login'],'bob')
        with self.store.connection() as db:
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(),[])

    def test_delete_requires_subscription_cleanup(self):
        self.store.enable_listener('11',True)
        with self.assertRaises(ValueError):self.store.delete_account('11')
        self.store.enable_listener('11',False)
        self.store.expect_subscription('11','channel.subscribe','https://example.test/eventsub')
        with self.assertRaises(ValueError):self.store.delete_account('11')
        self.assertIsNotNone(self.store.session(self.session))

    def test_backup_preserves_data_and_refuses_overwrite(self):
        self.store.set_owed('11',42)
        target=self.path/'backup.sqlite3';backup(self.store.path,target)
        restored=Store(target,self.key)
        self.assertEqual(restored.profile('11')['owed'],42)
        with self.assertRaises(FileExistsError):backup(self.store.path,target)
        with self.assertRaises(ValueError):backup(self.store.path,self.store.path)

    def test_rate_limits_reset_and_have_bounded_memory(self):
        now=[0];limiter=RateLimiter(clock=lambda:now[0])
        self.assertTrue(limiter.allow('a',2));self.assertTrue(limiter.allow('a',2));self.assertFalse(limiter.allow('a',2))
        self.assertTrue(limiter.allow('b',2));now[0]=61;self.assertTrue(limiter.allow('a',2))
        for n in range(3000):limiter.allow(str(n),1)
        self.assertLessEqual(len(limiter.entries),2048)
