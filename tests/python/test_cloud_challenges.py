"""Real SQLite transactions; fake camera clients and time, no external calls."""
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

try:
    from cryptography.fernet import Fernet
except ImportError:
    Fernet = None
if Fernet:
    from squat_capture.cloud.store import Store
    from squat_capture.cloud.challenges import Challenges, ChallengeConflict


@unittest.skipUnless(Fernet,'Install requirements-cloud.txt')
class ChallengeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.key = Fernet.generate_key()
        self.store = Store(Path(self.tmp.name)/'db.sqlite3',self.key)
        for uid in ('11','22'):
            self.store.login({'user_id':uid,'login':'test'+uid},{'access_token':'fake'})
            self.store.save_rules(uid,{**self.store.rules(uid),'reward_id':'reward','reward_reps':3,'sub_reps':5})
        for event_id in ('one','two'):
            self.store.receive_event('11','channel.channel_points_custom_reward_redemption.add',event_id,
                {'id':event_id,'broadcaster_user_id':'11','reward':{'id':'reward'},'user_name':event_id})
        self.now = 1000
        self.service = Challenges(self.store,clock=lambda:self.now)
        self.run = self.service.start('11','start-one')['id']
        self.lease = self.service.claim('11',self.run,'camera-a')['lease']

    def progress(self, count):
        return self.service.progress('11',self.run,self.lease,count)

    def test_cumulative_progress_duplicates_and_reordering(self):
        self.assertEqual(self.progress(2)['accepted'],2)
        self.assertEqual(self.progress(2)['accepted'],2)
        self.assertEqual(self.progress(1)['accepted'],2)
        self.assertEqual(self.store.profile('11')['owed'],4)
        self.assertEqual(self.store.profile('11')['lifetime'],2)
        self.assertEqual(self.store.queue('11')[0]['done'],2)
        self.assertEqual(self.store.profile('22')['lifetime'],0)

    def test_completion_waits_for_manual_next_and_start_retry_is_safe(self):
        self.assertEqual(self.progress(3)['run']['status'],'completed')
        self.assertIsNone(self.service.state('11'))
        self.assertEqual(self.service.start('11','start-one')['id'],self.run)
        self.assertIsNone(self.service.state('11'))
        next_run = self.service.start('11','start-two')
        self.assertNotEqual(next_run['id'],self.run)
        self.assertEqual(next_run['viewer'],'two')
        self.assertEqual(self.progress(3)['accepted'],3)
        self.assertEqual(self.store.profile('11')['lifetime'],3)

    def test_pause_resume_invalidates_old_lease(self):
        self.progress(1)
        self.service.pause('11',self.run)
        self.assertEqual(self.progress(1)['accepted'],1)
        with self.assertRaises(ChallengeConflict): self.progress(2)
        self.assertEqual(self.service.start('11','resume')['id'],self.run)
        with self.assertRaises(ChallengeConflict): self.progress(2)
        self.lease = self.service.claim('11',self.run,'camera-a')['lease']
        self.assertEqual(self.progress(2)['accepted'],2)

    def test_lease_exclusive_and_expiry_fences_old_camera(self):
        with self.assertRaises(ChallengeConflict): self.service.claim('11',self.run,'camera-b')
        self.assertEqual(self.service.claim('11',self.run,'camera-a')['lease'],self.lease)
        self.now += 16
        with self.assertRaises(ChallengeConflict): self.progress(1)
        fresh = self.service.claim('11',self.run,'camera-b')
        self.assertNotEqual(fresh['lease'],self.lease)
        with self.assertRaises(ChallengeConflict): self.progress(1)
        self.service.progress('11',self.run,fresh['lease'],1)

    def test_foreign_account_cannot_claim_pause_or_count(self):
        for call in (lambda:self.service.claim('22',self.run,'camera-a'),
                     lambda:self.service.pause('22',self.run),
                     lambda:self.service.progress('22',self.run,self.lease,1),
                     lambda:self.service.start('22','start-one')):
            with self.assertRaises(ChallengeConflict): call()
        self.assertEqual(self.store.profile('11')['lifetime'],0)

    def test_restart_preserves_accepted_counts(self):
        self.progress(2)
        restored = Challenges(Store(self.store.path,self.key),clock=lambda:self.now)
        self.assertEqual(restored.progress('11',self.run,self.lease,2)['accepted'],2)
        self.assertEqual(restored.state('11')['done'],2)
        self.assertEqual(self.store.profile('11')['lifetime'],2)

    def test_concurrent_duplicate_commits_once(self):
        with ThreadPoolExecutor(max_workers=6) as pool:
            replies = list(pool.map(lambda _:self.progress(2),range(12)))
        self.assertTrue(all(r['accepted']==2 for r in replies))
        self.assertEqual(self.store.profile('11')['lifetime'],2)

    def test_concurrent_start_does_not_take_two_challenges(self):
        with ThreadPoolExecutor(max_workers=6) as pool:
            runs = list(pool.map(lambda n:self.service.start('11',str(n)),range(12)))
        self.assertEqual({r['id'] for r in runs},{self.run})

    def test_invalid_counts_never_change_totals(self):
        for count in (True,-1,1.5,'1',4,100001):
            with self.assertRaises(ValueError): self.progress(count)
        self.assertEqual(self.store.profile('11')['lifetime'],0)

    def test_owed_never_negative_and_support_never_queues(self):
        self.store.set_owed('11',0)
        self.progress(1)
        self.assertEqual(self.store.profile('11')['owed'],0)
        self.store.receive_event('11','channel.subscribe','sub',{'broadcaster_user_id':'11','is_gift':False})
        self.progress(2)
        self.assertEqual(self.store.profile('11')['owed'],4)
        self.assertEqual(len(self.store.queue('11')),2)

    def test_counter_limit_rolls_back_everything(self):
        with self.store.connection() as db:
            db.execute('UPDATE users SET lifetime=1000000000 WHERE id=?',('11',))
        with self.assertRaises(ChallengeConflict): self.progress(1)
        self.assertEqual(self.service.state('11')['accepted'],0)
        self.assertEqual(self.store.profile('11')['owed'],6)
        self.assertEqual(self.store.queue('11')[0]['done'],0)

    def test_public_overlay_contains_no_run_or_lease(self):
        link = self.store.rotate_overlay('11')
        self.progress(1)
        self.assertEqual(self.store.overlay(link),{'owed':5,'lifetime':1})
        self.assertNotIn('lease',self.service.state('11'))
        self.assertNotIn('page_id',self.service.state('11'))
