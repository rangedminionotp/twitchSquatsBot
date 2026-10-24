import os
import tempfile
import unittest
from unittest.mock import patch

from squat_capture.app_config import AppConfig
from squat_capture.app_stats import PersistentStats
from squat_capture.support_events import SupportService, validate_support_settings


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

    def test_bits_bundles_preview_events_and_restart(self):
        self.config.update({'bits_enabled':'1','bits_unit':'100','bits_squats':'1',
                            'bits_bundle_enabled':'1','bits_bundle_unit':'1000','bits_bundle_squats':'15',
                            'broadcaster_id':'owner'})
        self.stats.set_counters(owed=100)
        original = self.stats.path.read_bytes()
        for amount, expected in [(0,0),(99,0),(100,1),(499,4),(500,5),(999,9),
                                 (1000,15),(1099,15),(1200,17),(2000,30),(2500,35)]:
            with self.subTest(amount=amount):
                self.assertEqual(self.service.preview('bits',amount)['delta'],expected)
        self.assertEqual(self.stats.path.read_bytes(),original,'Preview must not write counts')
        event={'subscription':{'type':'channel.cheer'},'message_id':'one-cheer',
               'event':{'broadcaster_user_id':'owner','bits':1200}}
        self.service.twitch(event)
        self.service.twitch(event)
        restored=PersistentStats()
        service=SupportService(AppConfig(),restored,lambda _:None)
        service.twitch(event)
        self.assertEqual(restored.snapshot()['owed_squats'],117)
        self.assertEqual(restored.queue_snapshot()['items'],[])
        service.add('bits','separate-a',500);service.add('bits','separate-b',500)
        self.assertEqual(restored.snapshot()['owed_squats'],127,'Separate Cheers do not form a bundle')
        self.config.update({'bits_bundle_enabled':'0'})
        self.assertEqual(self.service.preview('bits',1200)['delta'],12,'Disabled bundle keeps legacy rate')

    def test_bits_bundle_settings_are_validated_before_saving(self):
        self.config.update({'bits_enabled':'1','bits_unit':'100','bits_squats':'1',
                            'bits_bundle_enabled':'1','bits_bundle_unit':'1000','bits_bundle_squats':'15'})
        original=self.config.path.read_bytes()
        for patch_values in ({'bits_bundle_unit':'100'}, {'bits_bundle_unit':'150'},
                             {'bits_bundle_unit':'1000.5'}, {'bits_bundle_squats':'0'},
                             {'bits_bundle_squats':'NaN'}, {'bits_bundle_enabled':'true'},
                             {'bits_unit':'300'}):
            with self.subTest(values=patch_values), self.assertRaises(ValueError):
                self.config.update(patch_values)
            self.assertEqual(self.config.path.read_bytes(),original)
            self.assertEqual(self.config.get('bits_unit'),'100')
        for amount in (-1, 1.5, 'Infinity', 'NaN'):
            with self.assertRaises(ValueError):self.service.preview('bits',amount)

    def test_subscription_only_settings_survive_restart(self):
        self.config.update({"subs_enabled": "1", "subs_squats": "10", "broadcaster_id": "owner",
                            "bits_enabled": "1", "streamlabs_enabled": "1", "streamelements_enabled": "1"})
        self.config.update({"bits_enabled": "0", "streamlabs_enabled": "0", "streamelements_enabled": "0"})
        self.stats.set_counters(owed=100)
        restored = PersistentStats()
        service = SupportService(AppConfig(), restored, lambda _: None)
        for kind, event in [("channel.subscribe", {"is_gift": False}),
                            ("channel.subscription.gift", {"total": 2}),
                            ("channel.cheer", {"bits": 1000})]:
            service.twitch({"subscription": {"type": kind}, "message_id": kind,
                            "event": {"broadcaster_user_id": "owner", **event}})
        for source in ("bits", "streamlabs", "streamelements"):
            self.assertEqual(service.preview(source, 100, "USD")["delta"], 0)
            service.add(source, "disabled-event", 100, "USD")
        self.assertEqual(restored.snapshot()["owed_squats"], 130)
        restored.enqueue("reward", "Viewer", "10 squats", 10)
        self.assertEqual(restored.snapshot()["owed_squats"], 130)
        self.assertEqual(restored.queue_snapshot()["items"][0]["target"], 10)

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
        from squat_capture.twitch_eventsub_websocket import TwitchService, REDEMPTION_TYPE
        self.config.update({"subs_enabled": "1"})
        service = TwitchService(self.config, lambda _: None)
        service.auth_state = "success"
        self.assertEqual(service.health()["listeners"][1]["state"], "attention")
        service.status = {"state": "connected", "message": "Listening"}
        service.listening_types = {REDEMPTION_TYPE, "channel.subscribe", "channel.subscription.gift"}
        self.assertEqual(service.health()["listeners"][1]["state"], "ready")
        service.listening_types.discard("channel.subscription.gift")
        self.assertEqual(service.health()["listeners"][1]["state"], "attention")

    def test_stream_read_refreshes_an_expired_token_once(self):
        from squat_capture.twitch_eventsub_websocket import TwitchService, TwitchHTTPError
        self.config.update_tokens("expired", "refresh-one")
        service = TwitchService(self.config, lambda _: None)
        responses = [TwitchHTTPError(401, "expired"),
                     {"access_token": "fresh", "refresh_token": "refresh-two"},
                     {"data": [{"id": "stream"}]}]
        with patch("squat_capture.twitch_eventsub_websocket._request_json", side_effect=responses) as request:
            result = service._request_with_refresh("https://api.twitch.tv/helix/streams")
        self.assertEqual(result["data"][0]["id"], "stream")
        self.assertEqual(self.config.get("twitch_access_token"), "fresh")
        self.assertEqual(self.config.get("twitch_refresh_token"), "refresh-two")
        self.assertEqual(request.call_count, 3)


if __name__ == "__main__":
    unittest.main()
