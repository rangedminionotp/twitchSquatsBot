import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
try:
    from cryptography.fernet import Fernet
except ImportError:
    Fernet=None
if Fernet:
    from squat_capture.cloud.store import Store
    from squat_capture.cloud.donations import Donations, DonationWorkers, TenantSupport


@unittest.skipUnless(Fernet,'Install cloud requirements')
class DonationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=Store(Path(self.tmp.name)/'db',Fernet.generate_key())
        for uid in ('11','22'):self.store.login({'user_id':uid,'login':'user'},{'access_token':'fake'})
        self.repo=Donations(self.store)
        self.config=dict(enabled=True,unit='2.50',squats=3,currency='USD',token='TEST-DONATION-TOKEN',channel='channel',clear_token=False)
        self.repo.save('11','streamlabs',self.config)
        self.revision,_=self.repo.read('11','streamlabs')

    def test_encrypted_write_only_and_token_preserved(self):
        self.assertNotIn(b'TEST-DONATION-TOKEN',self.revision)
        self.assertNotIn('token',self.repo.public('11')['streamlabs'])
        self.repo.save('11','streamlabs',{**self.config,'token':''})
        self.assertEqual(self.repo.read('11','streamlabs')[1]['token'],'TEST-DONATION-TOKEN')
        self.repo.save('11','streamlabs',{**self.config,'enabled':False,'clear_token':True})
        self.assertFalse(self.repo.public('11')['streamlabs']['token_configured'])

    def test_decimal_units_duplicate_currency_and_tenant_isolation(self):
        self.assertTrue(self.repo.receive('11','streamlabs',self.revision,'one','7.49','USD'))
        self.assertFalse(self.repo.receive('11','streamlabs',self.revision,'one','7.49','USD'))
        self.assertFalse(self.repo.receive('11','streamlabs',self.revision,'two','5','EUR'))
        self.assertFalse(self.repo.receive('22','streamlabs',self.revision,'one','5','USD'))
        self.assertEqual(self.store.profile('11')['owed'],6)
        self.assertEqual(self.store.profile('22')['owed'],0)
        self.assertEqual(self.store.queue('11'),[])

    def test_stale_worker_rejected_after_disable(self):
        self.repo.save('11','streamlabs',{**self.config,'enabled':False})
        self.assertFalse(self.repo.receive('11','streamlabs',self.revision,'one','5','USD'))

    def test_overflow_rolls_back_receipt(self):
        self.store.set_owed('11',1000000000)
        with self.assertRaises(ValueError):self.repo.receive('11','streamlabs',self.revision,'one','5','USD')
        self.store.set_owed('11',0)
        self.assertTrue(self.repo.receive('11','streamlabs',self.revision,'one','5','USD'))

    def test_provider_adapter_ignores_test_donations(self):
        worker=TenantSupport(self.repo,'11','streamlabs',self.revision,self.repo.read('11','streamlabs')[1])
        worker.streamlabs({'type':'donation','isTest':True,'message':[{'id':'a','amount':'5','currency':'USD'}]})
        worker.streamlabs({'type':'donation','message':[{'id':'b','amount':'5','currency':'USD'}]})
        self.assertEqual(self.store.profile('11')['owed'],6)

    def test_manager_reuses_and_stops_workers(self):
        manager=DonationWorkers(self.repo)
        with patch.object(TenantSupport,'start') as start,patch.object(TenantSupport,'close') as close:
            manager.tick();manager.tick();self.assertEqual(start.call_count,1)
            self.repo.save('11','streamlabs',{**self.config,'enabled':False})
            manager.tick();close.assert_called_once()
            self.assertEqual(manager.workers,{})

    def test_invalid_inputs(self):
        for values in ({'unit':'NaN'},{'unit':'0'},{'squats':True},{'currency':'dollars'},{'enabled':'true'}):
            with self.assertRaises(ValueError):self.repo.save('11','streamlabs',{**self.config,**values})
        for amount in ('NaN','Infinity','-1','bad'):
            self.assertFalse(self.repo.receive('11','streamlabs',self.revision,'bad',amount,'USD'))
