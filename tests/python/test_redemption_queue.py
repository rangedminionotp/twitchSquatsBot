import tempfile
import unittest
from unittest.mock import patch
from squat_capture.app_stats import PersistentStats


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.env=patch.dict('os.environ',{'SQUAT_CAPTURE_DATA_DIR':self.tmp.name});self.env.start()
        self.s=PersistentStats()

    def tearDown(self):
        self.env.stop();self.tmp.cleanup()

    def test_dedup_fifo_and_single_deduction(self):
        self.s.add_support('subs:x',10)
        self.s.enqueue('a','A','2 squats',2);self.s.enqueue('a','A','2 squats',2)
        self.s.enqueue('b','B','3 squats',3)
        self.assertEqual(self.s.snapshot()['owed_squats'],10)
        run=self.s.set_queue_active(True)['run']
        self.s.record_count('camera:a',3,run);self.s.record_count('camera:a',3,run)
        self.assertEqual(self.s.snapshot()['owed_squats'],7)
        self.assertEqual(self.s.snapshot()['lifetime_squats'],3)
        self.assertEqual(self.s.queue_snapshot()['items'][0]['done'],1)
        self.assertEqual(len(self.s.queue_snapshot()['items']),1)

    def test_pause_restart_and_free_capture(self):
        self.s.add_support('bits:x',10)
        self.s.enqueue('a','A','5 squats',5)
        run=self.s.set_queue_active(True)['run'];self.s.record_count('camera:a',2,run)
        self.s.set_queue_active(False);self.s.record_count('camera:free',1)
        reloaded=PersistentStats()
        self.assertFalse(reloaded.queue_snapshot()['active'])
        self.assertEqual(reloaded.queue_snapshot()['items'][0]['done'],2)
        self.assertEqual(reloaded.snapshot()['owed_squats'],7)

    def test_write_failure_retry(self):
        self.s.set_counters(owed=5)
        with patch.object(self.s,'_save',side_effect=OSError):
            with self.assertRaises(OSError):self.s.enqueue('a','A','Squats',3)
        self.s.enqueue('a','A','Squats',3)
        run=self.s.set_queue_active(True)['run']
        with patch.object(self.s,'_save',side_effect=OSError):
            with self.assertRaises(OSError):self.s.record_count('camera:a',3,run)
        self.s.record_count('camera:a',3,run)
        self.assertEqual(self.s.snapshot()['owed_squats'],2)
        self.assertEqual(self.s.queue_snapshot()['items'],[])
        self.assertFalse(self.s.queue_snapshot()['active'])

    def test_redemption_persists_without_adding_debt(self):
        self.s.set_counters(owed=100)
        self.s.enqueue('a','Viewer','10 squats',10)
        restored=PersistentStats()
        restored.enqueue('a','Viewer','10 squats',10)
        self.assertEqual(restored.snapshot()['owed_squats'],100)
        self.assertEqual(restored.snapshot()['lifetime_squats'],0)
        self.assertEqual(len(restored.queue_snapshot()['items']),1)
        self.assertEqual(restored.queue_snapshot()['items'][0]['target'],10)
        self.assertEqual(restored.activity()[0]['reason'],'Challenge queued; total owed unchanged')

    def test_challenge_still_completes_after_owed_reaches_zero(self):
        self.s.set_counters(owed=2)
        self.s.observe_stream('stream-a','live')
        self.s.enqueue('a','Viewer','5 squats',5)
        run=self.s.set_queue_active(True)['run']
        self.s.record_count('camera:a',3,run)
        self.assertEqual(self.s.snapshot()['owed_squats'],0)
        self.assertEqual(self.s.queue_snapshot()['items'][0]['done'],3)
        self.s.record_count('camera:a',5,run)
        self.s.record_count('camera:a',4,run)
        self.assertEqual(self.s.snapshot()['owed_squats'],0)
        self.assertEqual(self.s.snapshot()['completed_squats'],5)
        self.assertEqual(self.s.snapshot()['lifetime_squats'],5)
        self.assertEqual(self.s.queue_snapshot()['items'],[])

    def test_existing_saved_totals_are_not_recalculated(self):
        # Old releases included queued reps in owed. Preserve that saved value;
        # past manual corrections make an automatic subtraction ambiguous.
        self.s.enqueue('old','Viewer','10 squats',10)
        self.s.set_counters(owed=774)
        restored=PersistentStats()
        restored.enqueue('new','Viewer','5 squats',5)
        self.assertEqual(restored.snapshot()['owed_squats'],774)
        self.assertEqual(len(restored.queue_snapshot()['items']),2)

    def test_notification_routing_keeps_challenges_separate_from_support_debt(self):
        from squat_capture import twitch_eventsub_listener as listener
        from squat_capture.support_events import SupportService
        config={'broadcaster_id':'11','broadcaster_login':'owner','target_reward_id':'reward',
                'subs_enabled':'1','subs_squats':'5','bits_enabled':'1','bits_unit':'100','bits_squats':'2',
                'streamlabs_enabled':'1','streamlabs_unit':'1','streamlabs_squats':'1','streamlabs_currency':'USD'}
        support=SupportService(config,self.s,lambda _:None)
        self.s.set_counters(owed=100)
        redemption={'subscription':{'type':'channel.channel_points_custom_reward_redemption.add'},
                    'event':{'id':'redeem','broadcaster_user_id':'11','broadcaster_user_login':'owner',
                             'user_name':'Viewer','reward':{'id':'reward','title':'10 squats'}}}
        with patch.object(listener,'APP_CONFIG',config), patch.object(listener,'APP_STATS',self.s), \
             patch.object(listener,'SUPPORT_SERVICE',support), patch.object(listener.OVERLAY_STATE,'publish') as publish:
            listener.process_eventsub_notification(redemption)
            listener.process_eventsub_notification(redemption)
            self.assertEqual(publish.call_args.args[0]['owed_squats'],100)
            for kind,event in [('channel.subscribe',{'is_gift':False}),('channel.cheer',{'bits':100})]:
                listener.process_eventsub_notification({'subscription':{'type':kind},'message_id':kind,
                    'event':{'broadcaster_user_id':'11',**event}})
        support.streamlabs({'type':'donation','message':[{'id':'tip','amount':'3','currency':'USD'}]})
        self.assertEqual(self.s.snapshot()['owed_squats'],110)
        self.assertEqual(len(self.s.queue_snapshot()['items']),1)
        self.assertEqual(self.s.queue_snapshot()['items'][0]['target'],10)
        run=self.s.set_queue_active(True)['run']
        self.s.record_count('camera:routing',3,run)
        self.assertEqual(self.s.snapshot()['owed_squats'],107)
        self.assertEqual(self.s.queue_snapshot()['items'][0]['done'],3)
