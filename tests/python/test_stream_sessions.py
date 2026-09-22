import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from squat_capture.app_stats import PersistentStats


class StreamSessionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"SQUAT_CAPTURE_DATA_DIR": self.temp.name})
        self.env.start()
        self.stats = PersistentStats()
        self.stats.set_counters(owed=100)

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def test_same_stream_survives_restart_and_replay(self):
        self.stats.observe_stream("user:123", "live")
        self.stats.record_count("camera", 8)
        restored = PersistentStats()
        restored.observe_stream("user:123", "live")
        restored.record_count("camera", 8)
        self.assertEqual(restored.snapshot()["completed_squats"], 8)
        self.assertEqual(restored.snapshot()["owed_squats"], 92)

    def test_next_stream_resets_only_session(self):
        self.stats.observe_stream("user:123", "live")
        self.stats.record_count("camera", 8)
        self.stats.observe_stream(None, "offline")
        self.assertEqual(self.stats.snapshot()["completed_squats"], 8)
        self.stats.observe_stream("user:456", "live")
        self.stats.record_count("camera", 10)
        self.assertEqual(self.stats.snapshot()["completed_squats"], 2)
        self.assertEqual(self.stats.snapshot()["owed_squats"], 90)
        self.assertEqual(self.stats.snapshot()["lifetime_squats"], 10)

    def test_offline_and_unknown_do_not_count_as_live(self):
        self.stats.observe_stream("user:123", "live")
        self.stats.record_count("camera", 3)
        self.stats.observe_stream(None, "unknown")
        self.stats.record_count("camera", 6)
        self.stats.observe_stream(None, "offline")
        self.stats.record_count("camera", 9)
        self.assertEqual(self.stats.snapshot()["completed_squats"], 3)
        self.assertEqual(self.stats.snapshot()["owed_squats"], 91)

    def test_old_total_preserved_without_claiming_current_session(self):
        self.stats.path.write_text(json.dumps({"schema_version": 2, "owed_squats": 774, "completed_squats": 500}))
        restored = PersistentStats()
        self.assertEqual(restored.snapshot()["lifetime_squats"], 500)
        self.assertEqual(restored.snapshot()["completed_squats"], 0)
        restored.observe_stream("user:123", "live")
        self.assertEqual(restored.snapshot()["owed_squats"], 774)

    def test_manual_session_correction_keeps_lifetime(self):
        self.stats.observe_stream("user:123", "live")
        self.stats.record_count("camera", 3)
        self.stats.set_counters(completed=9)
        self.assertEqual(self.stats.snapshot()["completed_squats"], 9)
        self.assertEqual(self.stats.snapshot()["lifetime_squats"], 3)


if __name__ == '__main__':
    unittest.main()
