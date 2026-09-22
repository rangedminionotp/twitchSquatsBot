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
        self.s.enqueue('a','A','2 squats',2);self.s.enqueue('a','A','2 squats',2)
        self.s.enqueue('b','B','3 squats',3)
        self.s.add_support('subs:x',10)
        run=self.s.set_queue_active(True)['run']
        self.s.record_count('camera:a',3,run);self.s.record_count('camera:a',3,run)
        self.assertEqual(self.s.snapshot()['owed_squats'],12)
        self.assertEqual(self.s.queue_snapshot()['items'][0]['done'],1)
        self.assertEqual(len(self.s.queue_snapshot()['items']),1)

    def test_pause_restart_and_free_capture(self):
        self.s.enqueue('a','A','5 squats',5)
        run=self.s.set_queue_active(True)['run'];self.s.record_count('camera:a',2,run)
        self.s.set_queue_active(False);self.s.record_count('camera:free',1)
        reloaded=PersistentStats()
        self.assertFalse(reloaded.queue_snapshot()['active'])
        self.assertEqual(reloaded.queue_snapshot()['items'][0]['done'],2)
        self.assertEqual(reloaded.snapshot()['owed_squats'],2)

    def test_write_failure_retry(self):
        with patch.object(self.s,'_save',side_effect=OSError):
            with self.assertRaises(OSError):self.s.enqueue('a','A','Squats',3)
        self.s.enqueue('a','A','Squats',3)
        run=self.s.set_queue_active(True)['run']
        with patch.object(self.s,'_save',side_effect=OSError):
            with self.assertRaises(OSError):self.s.record_count('camera:a',3,run)
        self.s.record_count('camera:a',3,run)
        self.assertEqual(self.s.snapshot()['owed_squats'],0)
        self.assertEqual(self.s.queue_snapshot()['items'],[])
        self.assertFalse(self.s.queue_snapshot()['active'])
