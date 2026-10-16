import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
try:
    from cryptography.fernet import Fernet
except ImportError:
    Fernet=None
if Fernet:
    from squat_capture.cloud.store import Store
    from squat_capture.cloud.challenges import Challenges, ChallengeConflict
    from squat_capture.cloud.twitch_data import TwitchData


@unittest.skipUnless(Fernet,'Install cloud requirements')
class StreamDataTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.store=Store(Path(self.tmp.name)/'db',Fernet.generate_key())
        for uid in ('11','22'):
            self.store.login({'user_id':uid,'login':'test'+uid},{'access_token':'fake','scopes':['channel:read:redemptions']})
        self.capture=Challenges(self.store)
        self.run=self.capture.start('11','free',free_target=4)['id']
        self.lease=self.capture.claim('11',self.run,'page')['lease']

    def test_free_set_does_not_add_debt_or_queue(self):
        self.assertEqual(self.store.profile('11')['owed'],0)
        self.assertEqual(self.store.queue('11'),[])
        self.store.set_owed('11',10)
        self.capture.progress('11',self.run,self.lease,2)
        self.assertEqual(self.store.profile('11')['owed'],8)
        self.assertEqual(self.store.profile('11')['lifetime'],2)
        self.capture.end_free('11',self.run)
        with self.assertRaises(ChallengeConflict):self.capture.progress('11',self.run,self.lease,3)
        self.assertEqual(self.capture.progress('11',self.run,self.lease,2)['accepted'],2)
        self.assertEqual(self.capture.start('11','free',4)['id'],self.run)
        self.assertNotEqual(self.capture.start('11','new',4)['id'],self.run)

    def test_mode_switch_and_owner_guards(self):
        with self.assertRaises(ChallengeConflict):self.capture.start('11','queue')
        with self.assertRaises(ChallengeConflict):self.capture.end_free('22',self.run)
        self.capture.pause('11',self.run)
        self.assertEqual(self.capture.start('11','resume',4)['id'],self.run)
        for target in (True,0,501,'5'):
            with self.assertRaises(ValueError):self.capture.start('22','invalid',target)

    def test_stream_counts_reset_only_for_new_twitch_id(self):
        a={'id':'stream-a','user_id':'11','started_at':'2026-10-11T10:00:00Z'}
        self.store.observe_stream('11',a)
        self.capture.progress('11',self.run,self.lease,1)
        self.store.observe_stream('11',a)
        self.assertEqual(self.store.stream_summary('11')['completed'],1)
        self.store.observe_stream('11',None)
        self.capture.progress('11',self.run,self.lease,2)
        self.assertEqual(self.store.stream_summary('11')['completed'],1)
        self.store.observe_stream('11',{**a,'id':'stream-b'})
        self.capture.progress('11',self.run,self.lease,3)
        self.capture.progress('11',self.run,self.lease,3)
        self.assertEqual(self.store.stream_summary('11')['completed'],1)
        self.assertEqual(self.store.profile('11')['lifetime'],3)
        self.assertEqual(self.store.stream_summary('22')['completed'],0)

    def test_stale_or_unavailable_stream_never_gets_reps(self):
        self.store.observe_stream('11',{'id':'a','user_id':'11','started_at':'date'})
        with self.store.connection() as db:db.execute('UPDATE stream_state SET checked=0')
        self.capture.progress('11',self.run,self.lease,1)
        self.assertEqual(self.store.stream_summary('11')['state'],'checking')
        self.assertEqual(self.store.stream_summary('11')['completed'],0)
        self.store.stream_unavailable('11')
        self.capture.progress('11',self.run,self.lease,2)
        self.assertEqual(self.store.stream_summary('11')['completed'],0)

    def test_rewards_bind_user_and_hide_other_fields(self):
        tokens=Mock();tokens.check.return_value='connected'
        client=TwitchData(self.store,tokens,'client')
        with patch('squat_capture.cloud.twitch_data.json_request',return_value={'data':[{'id':'r','title':'Squat','cost':10,'is_enabled':True,'private':'hidden'}]}) as request:
            self.assertEqual(client.rewards('11'),[{'id':'r','title':'Squat','cost':10,'enabled':True}])
            self.assertIn('broadcaster_id=11',request.call_args.args[0])
        tokens.check.return_value='reconnect_required'
        with self.assertRaises(ValueError):client.rewards('11')

    def test_worker_offline_failure_and_cross_user_identity(self):
        client=TwitchData(self.store,Mock(),'client')
        client.get=Mock(side_effect=[{'data':[]},TimeoutError()])
        client.tick()
        self.assertEqual(self.store.stream_summary('11')['state'],'offline')
        self.assertEqual(self.store.stream_summary('22')['state'],'unavailable')
        with self.assertRaises(ValueError):self.store.observe_stream('11',{'id':'bad','user_id':'22','started_at':'date'})
