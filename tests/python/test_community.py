"""Community contribution ledger tests."""
import tempfile
import unittest
from pathlib import Path

from cryptography.fernet import Fernet

from squat_capture.cloud.community import Community, CommunityConflict
from squat_capture.cloud.store import Store


class CommunityTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.store = Store(Path(self.directory.name) / 'community.sqlite3', Fernet.generate_key())
        self.store.login({'user_id':'11','login':'streamer'}, {'access_token':'OWNER'})
        self.store.login({'user_id':'22','login':'viewer'}, {'access_token':'VIEWER'}, role='viewer')
        self.now = [1_800_000_000.0]
        self.community = Community(self.store, '11', clock=lambda: self.now[0])

    def advance(self, seconds):
        self.now[0] += seconds

    def calibrated_run(self):
        run = self.community.start('22')
        self.advance(3)
        return self.community.calibrate('22',run['id'],165,95,3000)

    def test_run_requires_plausible_calibration(self):
        run = self.community.start('22')
        with self.assertRaises(ValueError):
            self.community.calibrate('22',run['id'],130,120,3000)
        with self.assertRaises(CommunityConflict):
            self.community.progress('22',run['id'],1,1,1000)
        ready = self.community.calibrate('22',run['id'],165,95,3000)
        self.assertEqual(ready['status'],'active')
        self.assertEqual(self.community.start('22')['id'],run['id'])

    def test_cumulative_progress_is_idempotent_and_counted_once(self):
        run = self.calibrated_run()
        self.advance(1)
        first = self.community.progress('22',run['id'],1,1,1000)
        self.assertEqual(first['accepted'],1)
        self.assertEqual(self.community.progress('22',run['id'],1,1,1000),first)
        self.advance(2)
        result = self.community.progress('22',run['id'],2,3,3000)
        self.assertEqual(result['accepted'],3)
        status = self.community.viewer('22')
        self.assertEqual(status['today'],3)
        self.assertEqual(status['community_total'],3)
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT SUM(amount) FROM community_contributions').fetchone()[0],3)

    def test_rejects_reordered_impossible_or_cross_viewer_progress(self):
        self.store.login({'user_id':'33','login':'other'}, {'access_token':'OTHER'}, role='viewer')
        run = self.calibrated_run()
        self.advance(1)
        with self.assertRaises(CommunityConflict):
            self.community.progress('33',run['id'],1,1,1000)
        with self.assertRaises(CommunityConflict):
            self.community.progress('22',run['id'],2,1,1000)
        with self.assertRaises(CommunityConflict):
            self.community.progress('22',run['id'],1,2,1500)
        self.assertEqual(self.community.admin('11')['flags'][0]['hits'],1)
        self.assertEqual(self.community.admin('11')['community_total'],0)
        self.community.progress('22',run['id'],1,1,1000)
        self.advance(1)
        with self.assertRaises(CommunityConflict):
            self.community.progress('22',run['id'],3,2,2000)

    def test_daily_limit_is_enforced_across_runs(self):
        for batch in range(5):
            run = self.calibrated_run()
            self.advance(20)
            result = self.community.progress('22',run['id'],1,20,20000)
            self.assertEqual(result['status'],'completed')
        status = self.community.viewer('22')
        self.assertEqual(status['today'],100)
        self.assertEqual(status['remaining_today'],0)
        self.assertEqual(status['community_total'],100)
        with self.assertRaises(CommunityConflict):
            self.community.start('22')

    def test_new_local_day_resets_viewer_allowance_not_total(self):
        run = self.calibrated_run()
        self.advance(2)
        self.community.progress('22',run['id'],1,2,2000)
        self.advance(24 * 60 * 60)
        fresh = self.community.start('22')
        status = self.community.viewer('22')
        self.assertEqual(status['today'],0)
        self.assertEqual(status['community_total'],2)
        self.assertEqual(fresh['target'],20)

    def test_owner_can_revoke_a_contribution_once(self):
        run = self.calibrated_run()
        self.advance(2)
        self.community.progress('22',run['id'],1,2,2000)
        recent = self.community.admin('11')
        self.assertEqual(recent['community_total'],2)
        contribution = recent['contributions'][0]
        self.assertEqual(contribution['viewer'],'viewer')
        revoked = self.community.revoke('11',contribution['id'])
        self.assertEqual(revoked['community_total'],0)
        self.assertTrue(revoked['contributions'][0]['revoked'])
        self.assertEqual(self.community.viewer('22')['today'],0)
        self.assertEqual(self.community.revoke('11',contribution['id'])['community_total'],0)
        with self.assertRaises(CommunityConflict):
            self.community.progress('22',run['id'],2,3,3000)
        self.assertNotEqual(self.community.start('22')['id'],run['id'])

    def test_non_owner_cannot_moderate_channel(self):
        with self.assertRaises(CommunityConflict):
            self.community.admin('22')
        with self.assertRaises(CommunityConflict):
            self.community.revoke('22',1)

    def test_viewer_deletion_reconciles_total_and_preserves_broadcaster_accounts(self):
        run = self.calibrated_run()
        self.advance(2)
        self.community.progress('22',run['id'],1,2,2000)
        self.store.delete_viewer_data('22','11')
        self.assertEqual(self.community.public()['community_total'],0)
        with self.assertRaises(ValueError):
            self.store.profile('22')

        self.store.login({'user_id':'33','login':'dual-role'}, {'access_token':'ADMIN'})
        run = self.community.start('33')
        self.advance(3)
        self.community.calibrate('33',run['id'],165,95,3000)
        self.advance(1)
        self.community.progress('33',run['id'],1,1,1000)
        self.store.delete_viewer_data('33','11')
        self.assertEqual(self.community.public()['community_total'],0)
        self.assertEqual(self.store.profile('33')['login'],'dual-role')
        self.assertEqual(self.store.credential_snapshot('33')[1]['access_token'],'ADMIN')


if __name__ == '__main__':
    unittest.main()
