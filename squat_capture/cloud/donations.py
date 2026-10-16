"""Per-tenant donation connectors, reusing the local provider transport only."""
import json
import threading
import time
from decimal import Decimal, InvalidOperation
from squat_capture.support_events import SupportService, SUPPORT_DEFAULTS

PROVIDERS=('streamlabs','streamelements')


class Donations:
    def __init__(self, store):
        self.store=store
        with store.connection() as db:
            db.execute('CREATE TABLE IF NOT EXISTS donation_settings(user_id TEXT NOT NULL REFERENCES users(id),source TEXT NOT NULL,config BLOB NOT NULL,PRIMARY KEY(user_id,source))')

    def read(self, uid, source):
        if source not in PROVIDERS:raise ValueError('Unknown donation provider')
        with self.store.connection() as db:
            row=db.execute('SELECT config FROM donation_settings WHERE user_id=? AND source=?',(uid,source)).fetchone()
        if not row:return None,{'enabled':False,'unit':'1','squats':1,'currency':'USD','token':'','channel':''}
        return row['config'],json.loads(self.store.cipher.decrypt(row['config']))

    def public(self, uid):
        result={}
        for source in PROVIDERS:
            _,config=self.read(uid,source)
            result[source]={k:v for k,v in config.items() if k!='token'}
            result[source]['token_configured']=bool(config['token'])
        return result

    def save(self, uid, source, values):
        required={'enabled','unit','squats','currency','token','channel','clear_token'}
        if set(values)!=required or type(values['enabled']) is not bool or type(values['clear_token']) is not bool:raise ValueError('Invalid settings')
        if type(values['squats']) is not int or not 1<=values['squats']<=100000:raise ValueError('Invalid squat count')
        if not isinstance(values['unit'],str) or len(values['unit'])>20:raise ValueError('Invalid unit')
        try:
            unit=Decimal(values['unit'])
            if not unit.is_finite() or not Decimal('.01')<=unit<=1000000:raise ValueError('Invalid unit')
        except InvalidOperation:raise ValueError('Invalid unit') from None
        currency=values['currency']
        if not isinstance(currency,str) or len(currency)!=3 or not currency.isascii() or not currency.isalpha():raise ValueError('Invalid currency')
        for key in ('token','channel'):
            if not isinstance(values[key],str) or len(values[key])>(8192 if key=='token' else 100):raise ValueError('Invalid credential')
        _,old=self.read(uid,source)
        config={k:values[k] for k in ('enabled','unit','squats','currency','token','channel')}
        config['currency']=currency.upper()
        config['token']='' if values['clear_token'] else values['token'] or old['token']
        if config['enabled'] and (not config['token'] or source=='streamelements' and not config['channel']):raise ValueError('Provider credentials required')
        encrypted=self.store.cipher.encrypt(json.dumps(config).encode())
        with self.store.connection() as db:
            db.execute('INSERT INTO donation_settings VALUES(?,?,?) ON CONFLICT(user_id,source) DO UPDATE SET config=excluded.config',(uid,source,encrypted))
        return self.public(uid)

    def receive(self, uid, source, revision, event_id, amount, currency):
        if not isinstance(event_id,(str,int)) or not 1<=len(str(event_id))<=200:return False
        try:
            amount=Decimal(str(amount))
            if not amount.is_finite() or not 0<=amount<=1000000000:return False
        except InvalidOperation:return False
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT config FROM donation_settings WHERE user_id=? AND source=?',(uid,source)).fetchone()
            if not row or row['config']!=revision:return False  # stale worker cannot add after reconfiguration
            config=json.loads(self.store.cipher.decrypt(row['config']))
            if not config['enabled'] or currency!=config['currency']:return False
            delta=int(amount//Decimal(config['unit']))*config['squats']
            if delta>1000000000:return False
            changed=db.execute('INSERT OR IGNORE INTO event_receipts VALUES(?,?,?,?,?)',
                               (uid,source+':'+str(event_id),source,delta,time.time())).rowcount
            if not changed:return False
            if not db.execute('UPDATE users SET owed=owed+? WHERE id=? AND owed+?<=1000000000',(delta,uid,delta)).rowcount:
                raise ValueError('Counter limit reached')  # rollback receipt as well
            return True


class TenantSupport(SupportService):
    def __init__(self, repository, uid, source, revision, values):
        config=dict(SUPPORT_DEFAULTS)
        for key,value in values.items():config[source+'_'+key]=('1' if value else '0') if key=='enabled' else str(value)
        super().__init__(config,None,lambda *_:None)
        self.repository,self.uid,self.source,self.revision=repository,uid,source,revision

    def add(self, source, event_id, amount=1, currency=None):
        if source==self.source:
            self.repository.receive(self.uid,source,self.revision,event_id,amount,currency)

    def close(self):
        with self._lock:
            for _,stop in self._workers.values():stop.set()


class DonationWorkers:
    def __init__(self, repository):
        self.repository=repository;self.workers={};self.stopping=threading.Event();self.thread=None
        self.lock=threading.RLock()

    def tick(self):
        wanted=set()
        with self.lock:
            for uid in self.repository.store.credential_users():
                for source in PROVIDERS:
                    revision,config=self.repository.read(uid,source)
                    key=(uid,source);previous=self.workers.get(key)
                    if not config['enabled']:
                        continue
                    wanted.add(key)
                    if previous and previous.revision==revision:continue
                    if previous:previous.close()
                    worker=TenantSupport(self.repository,uid,source,revision,config)
                    self.workers[key]=worker;worker.start()
            for key in set(self.workers)-wanted:self.workers.pop(key).close()

    def status(self, uid):
        with self.lock:
            return {source:self.workers[(uid,source)].status[source] if (uid,source) in self.workers else 'Disabled / awaiting sync' for source in PROVIDERS}

    def start(self):
        def run():
            while not self.stopping.is_set():
                try:self.tick()
                except Exception:pass  # never log provider credentials/URLs
                self.stopping.wait(15)
        self.thread=threading.Thread(target=run,daemon=True,name='cloud-donations');self.thread.start()

    def stop(self):
        self.stopping.set()
        if self.thread:self.thread.join(timeout=2)
        with self.lock:
            for worker in self.workers.values():worker.close()
