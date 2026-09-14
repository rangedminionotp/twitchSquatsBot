import os
import tempfile
import unittest
from unittest.mock import patch

from app_config import AppConfig
from app_stats import PersistentStats
from support_events import SupportService, validate_support_settings


class SupportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"SQUAT_CAPTURE_DATA_DIR": self.temp.name})
        self.env.start()
        self.config = AppConfig()
        self.stats = PersistentStats()
        self.service = SupportService(self.config, self.stats, lambda _: None)

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def test_opt_in_and_independent_rules(self):
        self.service.add("bits", "disabled", 100)
        self.assertEqual(self.stats.snapshot()["owed_squats"], 0)
        self.config.update({"bits_enabled": "1", "bits_unit": "100", "bits_squats": "3",
                            "streamlabs_enabled": "1", "streamlabs_unit": "2.50", "streamlabs_squats": "4"})
        self.service.add("bits", "a", 250)
        self.service.add("streamlabs", "b", "5.01", "USD")
        self.service.add("streamlabs", "c", "100", "EUR")
        self.assertEqual(self.stats.snapshot()["owed_squats"], 14)
        self.assertEqual(self.stats.snapshot()["completed_squats"], 0)

    def test_durable_dedup_and_manual_edits(self):
        self.config.update({"subs_enabled": "1", "subs_squats": "5"})
        self.service.add("subs", "same")
        self.stats.set_counters(owed=1)
        reloaded = PersistentStats()
        SupportService(self.config, reloaded, lambda _: None).add("subs", "same")
        self.assertEqual(reloaded.snapshot()["owed_squats"], 1)

    def test_gifts_are_not_counted_twice(self):
        self.config.update({"subs_enabled": "1", "broadcaster_id": "owner"})
        for kind, event in [("channel.subscribe", {"is_gift": True}),
                            ("channel.subscription.gift", {"total": 10}),
                            ("channel.subscribe", {"is_gift": False})]:
            self.service.twitch({"subscription": {"type": kind}, "message_id": kind,
                                 "event": {"broadcaster_user_id": "owner", **event}})
        self.assertEqual(self.stats.snapshot()["owed_squats"], 11)

    def test_provider_payloads(self):
        self.config.update({"streamlabs_enabled": "1", "streamelements_enabled": "1", "streamelements_channel": "room"})
        sl = {"type": "donation", "message": [{"id": 42, "amount": "3.50", "currency": "USD"}]}
        se = {"type": "message", "topic": "channel.tips", "data": {"_id": "tip", "channel": "room",
              "status": "success", "donation": {"amount": 4.2, "currency": "USD"}}}
        for _ in range(2):
            self.service.streamlabs(sl)
            self.service.streamelements(se)
        self.service.streamlabs({**sl, "for": "twitch_account"})
        self.service.streamelements({**se, "data": {**se["data"], "_id": "pending", "status": "pending"}})
        self.assertEqual(self.stats.snapshot()["owed_squats"], 7)

    def test_invalid_settings_are_atomic_and_tokens_masked(self):
        for value in ("NaN", "Infinity", "-1", "0", "1.5"):
            with self.assertRaises(ValueError):
                self.config.update({"subs_enabled": "1", "subs_squats": value})
            self.assertEqual(self.config.get("subs_enabled"), "0")
        self.config.update({"streamlabs_token": "test-secret"})
        self.assertEqual(self.config.public()["streamlabs_token"], "configured")
        self.config.update({"streamlabs_token": "configured"})
        self.assertEqual(self.config.get("streamlabs_token"), "test-secret")

    def test_zero_and_malformed_amounts(self):
        self.config.update({"bits_enabled": "1"})
        for amount in ("NaN", "Infinity", "-1", None, "bad", 0, 99):
            self.service.add("bits", str(amount), amount)
        self.service.add("bits", None, 100)
        self.assertEqual(self.stats.snapshot()["owed_squats"], 0)

    def test_failed_write_can_retry(self):
        with patch.object(self.stats, "_save", side_effect=OSError("disk")):
            with self.assertRaises(OSError):
                self.stats.add_support("x", 3)
        self.stats.add_support("x", 3)
        self.assertEqual(self.stats.snapshot()["owed_squats"], 3)

    def test_preview_never_changes_real_data(self):
        self.config.update({"subs_enabled": "1", "subs_squats": "10"})
        self.stats.set_counters(owed=774)
        before = self.stats.path.read_bytes()
        self.assertEqual(self.service.preview("subs", 5)["delta"], 50)
        self.assertEqual(self.stats.path.read_bytes(), before)
        self.assertEqual(self.service.diagnostics(), [])
        with self.assertRaises(ValueError):
            self.service.preview("unknown", 1)

    def test_activity_persistence_and_duplicate_diagnostics(self):
        self.config.update({"subs_enabled": "1"})
        self.service.add("subs", "secret-event-id")
        self.service.add("subs", "secret-event-id")
        restored = PersistentStats()
        self.assertEqual(len(restored.activity()), 1)
        self.assertEqual(restored.activity()[0]["amount"], 1)
        self.assertNotIn("secret-event-id", str(restored.activity()))
        self.assertEqual(self.service.diagnostics()[0]["reason"], "Ignored: duplicate event")

    def test_health_does_not_confuse_login_with_listening(self):
        from twitch_eventsub_websocket import TwitchService, REDEMPTION_TYPE
        self.config.update({"subs_enabled": "1"})
        service = TwitchService(self.config, lambda _: None)
        service.auth_state = "success"
        self.assertEqual(service.health()["listeners"][1]["state"], "attention")
        service.status = {"state": "connected", "message": "Listening"}
        service.listening_types = {REDEMPTION_TYPE, "channel.subscribe", "channel.subscription.gift"}
        self.assertEqual(service.health()["listeners"][1]["state"], "ready")
        service.listening_types.discard("channel.subscription.gift")
        self.assertEqual(service.health()["listeners"][1]["state"], "attention")


if __name__ == "__main__":
    unittest.main()
