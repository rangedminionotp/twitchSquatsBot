"""Signed fake events; no external Twitch calls or real credentials."""
import hashlib
import hmac
import json
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

try:
    from cryptography.fernet import Fernet
except ImportError:
    Fernet = None
if Fernet:
    from squat_capture.cloud.store import Store
    from squat_capture.cloud.events import handle_event
    from squat_capture.cloud.subscriptions import SCOPES


@unittest.skipUnless(Fernet, 'Install requirements-cloud.txt')
class CloudEventTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.key = Fernet.generate_key()
        self.store = Store(Path(self.tmp.name)/'cloud.sqlite3',self.key)
        for uid in ('11','22'):
            self.store.login({'user_id':uid,'login':'test'+uid},{'access_token':'test'})
        self.rules = dict(reward_id='reward-a',reward_reps=10,sub_reps=5,gift_reps=7,bits_unit=100,bits_reps=2)
        self.store.save_rules('11',self.rules)
        self.secret = 'test-only-webhook-secret-0000000000000000'
        self.now = datetime.now(timezone.utc)
        self.store.enable_listener('11',True)
        for kind in SCOPES:
            self.store.expect_subscription('11',kind,'https://example.test/eventsub')
            self.store.save_subscription('11',kind,'sub-'+kind,'enabled')

    def signed(self, kind, event, mid='m1', uid='11', message_type='notification', stamp=None):
        body = {'subscription':{'id':'sub-'+kind,'type':kind,'version':'1','condition':{'broadcaster_user_id':uid},'transport':{'method':'webhook','callback':'https://example.test/eventsub'}},'event':event,'challenge':'challenge-value'}
        raw = json.dumps(body).encode()
        stamp = (stamp or self.now).isoformat()
        headers = {'Twitch-Eventsub-Message-Id':mid,'Twitch-Eventsub-Message-Timestamp':stamp,'Twitch-Eventsub-Message-Type':message_type}
        headers['Twitch-Eventsub-Message-Signature'] = 'sha256='+hmac.new(self.secret.encode(),mid.encode()+stamp.encode()+raw,hashlib.sha256).hexdigest()
        return headers,raw

    def deliver(self,kind,event,**kwargs):
        headers,raw = self.signed(kind,event,**kwargs)
        return handle_event(self.store,self.secret,headers,raw,now=self.now)

    def redemption(self):
        return {'broadcaster_user_id':'11','id':'redeem-1','reward':{'id':'reward-a'},'user_name':'Viewer'}

    def test_redemptions_persist_and_dedup_across_message_ids(self):
        kind = 'channel.channel_points_custom_reward_redemption.add'
        self.assertEqual(self.deliver(kind,self.redemption())[0],204)
        self.assertEqual(self.deliver(kind,self.redemption(),mid='different')[0],204)
        restored = Store(self.store.path,self.key)
        self.assertEqual(restored.profile('11')['owed'],10)
        self.assertEqual(len(restored.queue('11')),1)
        self.assertEqual(restored.queue('22'),[])
        self.assertEqual(restored.profile('22')['owed'],0)

    def test_concurrent_duplicate_is_atomic(self):
        with ThreadPoolExecutor(max_workers=5) as pool:
            results = list(pool.map(lambda _: self.store.receive_event('11','channel.channel_points_custom_reward_redemption.add','m',self.redemption()),range(10)))
        self.assertEqual(sum(results),1)
        self.assertEqual(self.store.profile('11')['owed'],10)

    def test_support_adds_owed_without_queue_and_gifts_not_doubled(self):
        self.deliver('channel.subscribe',{'broadcaster_user_id':'11','is_gift':False},mid='sub')
        self.deliver('channel.subscribe',{'broadcaster_user_id':'11','is_gift':True},mid='gift-recipient')
        self.deliver('channel.subscription.gift',{'broadcaster_user_id':'11','total':3},mid='gift')
        self.deliver('channel.subscription.gift',{'broadcaster_user_id':'11','total':3},mid='gift')
        self.deliver('channel.cheer',{'broadcaster_user_id':'11','bits':250},mid='bits')
        self.assertEqual(self.store.profile('11')['owed'],30)
        self.assertEqual(self.store.queue('11'),[])

    def test_invalid_signatures_stale_and_future_rejected(self):
        headers,raw = self.signed('channel.subscribe',{'broadcaster_user_id':'11','is_gift':False})
        self.assertEqual(handle_event(self.store,self.secret,headers,raw+b' ',self.now)[0],403)
        self.assertEqual(handle_event(self.store,'',headers,raw,self.now)[0],503)
        for stamp in (self.now-timedelta(minutes=11),self.now+timedelta(minutes=2)):
            self.assertEqual(self.deliver('channel.subscribe',{},stamp=stamp)[0],403)
        self.assertEqual(self.store.profile('11')['owed'],0)

    def test_cross_broadcaster_and_unknown_users_rejected(self):
        self.assertEqual(self.deliver('channel.subscribe',{'broadcaster_user_id':'22','is_gift':False})[0],400)
        self.assertEqual(self.deliver('channel.subscribe',{'broadcaster_user_id':'33','is_gift':False},uid='33')[0],400)
        self.assertEqual(self.store.profile('11')['owed'],0)

    def test_verification_requires_signature_and_echoes_only_challenge(self):
        self.assertEqual(self.deliver('channel.subscribe',{},message_type='webhook_callback_verification'),(200,b'challenge-value'))

    def test_disabled_unmatched_and_invalid_rules(self):
        self.assertEqual(self.store.rules('22')['sub_reps'],0)
        other = self.redemption(); other['reward']['id']='unmatched'
        self.deliver('channel.channel_points_custom_reward_redemption.add',other)
        self.assertEqual(self.store.profile('11')['owed'],0)
        for change in ({'sub_reps':True},{'bits_unit':0},{'gift_reps':-1},{'user_id':'22'}):
            with self.assertRaises(ValueError): self.store.save_rules('11',{**self.rules,**change})

    def test_revocation_and_disabled_listener_reject_notifications(self):
        self.assertEqual(self.deliver('channel.subscribe',{},message_type='revocation')[0],204)
        self.assertEqual(self.store.listener('11')['message'],'subscription_revoked')
        self.assertEqual(self.deliver('channel.subscribe',{'broadcaster_user_id':'11','is_gift':False})[0],400)
        self.store.enable_listener('11',False)
        self.assertEqual(self.deliver('channel.cheer',{'broadcaster_user_id':'11','bits':200})[0],400)
        self.assertEqual(self.store.profile('11')['owed'],0)

    def test_no_registered_subscription_cannot_verify(self):
        self.store.forget_subscription('11','channel.subscribe')
        self.assertEqual(self.deliver('channel.subscribe',{},message_type='webhook_callback_verification')[0],400)

    def test_failure_rolls_back_receipt_and_can_retry(self):
        self.store.set_owed('11',1000000000)
        self.assertEqual(self.deliver('channel.subscribe',{'broadcaster_user_id':'11','is_gift':False})[0],400)
        self.store.set_owed('11',0)
        self.assertEqual(self.deliver('channel.subscribe',{'broadcaster_user_id':'11','is_gift':False})[0],204)
        self.assertEqual(self.store.profile('11')['owed'],5)
