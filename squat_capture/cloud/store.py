"""Transactional tenant storage. Public links and sessions store only token hashes."""
import hashlib
import json
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from cryptography.fernet import Fernet
from squat_capture.support_events import bits_squats

SESSION_SECONDS = 12 * 60 * 60


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


class Store:
    def __init__(self, path, encryption_key):
        self.cipher = Fernet(encryption_key)
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY, login TEXT NOT NULL, credentials BLOB NOT NULL,
                    owed INTEGER NOT NULL DEFAULT 0, lifetime INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS sessions (
                    hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
                    csrf TEXT NOT NULL, expires REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS oauth_states (
                    hash TEXT PRIMARY KEY, binding TEXT NOT NULL, expires REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS overlays (
                    hash TEXT PRIMARY KEY, user_id TEXT NOT NULL UNIQUE REFERENCES users(id));
                CREATE TABLE IF NOT EXISTS rules (
                    user_id TEXT PRIMARY KEY REFERENCES users(id),
                    reward_id TEXT NOT NULL DEFAULT '', reward_reps INTEGER NOT NULL DEFAULT 10,
                    sub_reps INTEGER NOT NULL DEFAULT 0, gift_reps INTEGER NOT NULL DEFAULT 0,
                    bits_unit INTEGER NOT NULL DEFAULT 100, bits_reps INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS event_receipts (
                    user_id TEXT NOT NULL REFERENCES users(id), event_key TEXT NOT NULL,
                    kind TEXT NOT NULL, amount INTEGER NOT NULL, created REAL NOT NULL,
                    PRIMARY KEY(user_id,event_key));
                CREATE TABLE IF NOT EXISTS challenges (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL REFERENCES users(id),
                    event_key TEXT NOT NULL, viewer TEXT NOT NULL, target INTEGER NOT NULL,
                    done INTEGER NOT NULL DEFAULT 0, UNIQUE(user_id,event_key));
                CREATE TABLE IF NOT EXISTS auth_health (
                    user_id TEXT PRIMARY KEY REFERENCES users(id), state TEXT NOT NULL,
                    checked REAL NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS listeners (
                    user_id TEXT PRIMARY KEY REFERENCES users(id), enabled INTEGER NOT NULL DEFAULT 0,
                    message TEXT NOT NULL DEFAULT 'disabled', checked REAL NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS subscriptions (
                    user_id TEXT NOT NULL REFERENCES users(id), kind TEXT NOT NULL,
                    remote_id TEXT NOT NULL DEFAULT '', callback TEXT NOT NULL,
                    status TEXT NOT NULL, updated REAL NOT NULL,
                    PRIMARY KEY(user_id,kind));
                CREATE TABLE IF NOT EXISTS stream_sessions (
                    user_id TEXT NOT NULL REFERENCES users(id), stream_id TEXT NOT NULL,
                    started TEXT NOT NULL, completed INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY(user_id,stream_id));
                CREATE TABLE IF NOT EXISTS stream_state (
                    user_id TEXT PRIMARY KEY REFERENCES users(id), stream_id TEXT,
                    state TEXT NOT NULL, checked REAL NOT NULL);
            ''')
            # Additive migration: existing tenants retain their single-rate rule.
            columns = {row['name'] for row in db.execute('PRAGMA table_info(rules)')}
            if 'bits_bundle_unit' not in columns:
                db.execute('ALTER TABLE rules ADD COLUMN bits_bundle_unit INTEGER NOT NULL DEFAULT 1000')
            if 'bits_bundle_reps' not in columns:
                db.execute('ALTER TABLE rules ADD COLUMN bits_bundle_reps INTEGER NOT NULL DEFAULT 0')

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            with db:
                yield db
        finally:
            db.close()

    def start_oauth(self):
        state, binding = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        with self.connection() as db:
            db.execute('DELETE FROM oauth_states WHERE expires <= ?', (time.time(),))
            db.execute('INSERT INTO oauth_states VALUES (?, ?, ?)',
                       (digest(state), digest(binding), time.time() + 600))
        return state, binding

    def consume_oauth(self, state, binding):
        if not state or not binding:
            return False
        with self.connection() as db:
            row = db.execute('DELETE FROM oauth_states WHERE hash=? AND binding=? AND expires>? RETURNING hash',
                             (digest(state), digest(binding), time.time())).fetchone()
            return row is not None

    def login(self, identity, tokens):
        uid, name = identity['user_id'], identity['login']
        if not isinstance(uid, str) or not uid.isdecimal() or not isinstance(name, str) or not name:
            raise ValueError('Invalid Twitch identity')
        encrypted = self.cipher.encrypt(json.dumps(tokens).encode())
        session, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        with self.connection() as db:
            db.execute('INSERT INTO users(id,login,credentials) VALUES(?,?,?) '
                       'ON CONFLICT(id) DO UPDATE SET login=excluded.login,credentials=excluded.credentials',
                       (uid, name, encrypted))
            db.execute('DELETE FROM sessions WHERE expires <= ?', (time.time(),))
            db.execute('INSERT INTO auth_health VALUES(?,?,?) ON CONFLICT(user_id) '
                       'DO UPDATE SET state=excluded.state,checked=excluded.checked',
                       (uid,'connected',time.time()))
            # Browser sessions remain short; background token maintenance does
            # not extend browser login or recreate logged-out sessions.
            db.execute('INSERT INTO sessions VALUES(?,?,?,?)',
                       (digest(session), uid, csrf, time.time() + SESSION_SECONDS))
        return session

    def credential_snapshot(self, uid):
        with self.connection() as db:
            row = db.execute('SELECT credentials FROM users WHERE id=?',(uid,)).fetchone()
            if not row:
                raise ValueError('Unknown user')
            blob = row['credentials']
        return blob, json.loads(self.cipher.decrypt(blob))

    def credential_users(self):
        with self.connection() as db:
            return [row[0] for row in db.execute('SELECT id FROM users')]

    def listener(self, uid):
        with self.connection() as db:
            row = db.execute('SELECT enabled,message,checked FROM listeners WHERE user_id=?',(uid,)).fetchone()
            result = dict(row) if row else {'enabled':0,'message':'disabled','checked':0}
            result['subscriptions'] = [dict(r) for r in db.execute('SELECT kind,status,updated FROM subscriptions WHERE user_id=? ORDER BY kind',(uid,))]
            return result

    def enable_listener(self, uid, enabled):
        if type(enabled) is not bool:
            raise ValueError('Expected boolean')
        with self.connection() as db:
            pending = db.execute('SELECT 1 FROM subscriptions WHERE user_id=? LIMIT 1',(uid,)).fetchone()
            db.execute('INSERT INTO listeners(user_id,enabled,message) VALUES(?,?,?) '
                       'ON CONFLICT(user_id) DO UPDATE SET enabled=excluded.enabled,message=excluded.message',
                       (uid,int(enabled),'sync_pending' if enabled else 'stopping' if pending else 'disabled'))

    def listener_message(self, uid, message):
        with self.connection() as db:
            db.execute('INSERT INTO listeners(user_id,message,checked) VALUES(?,?,?) '
                       'ON CONFLICT(user_id) DO UPDATE SET message=excluded.message,checked=excluded.checked',
                       (uid,message,time.time()))

    def subscriptions(self, uid):
        with self.connection() as db:
            return [dict(row) for row in db.execute('SELECT * FROM subscriptions WHERE user_id=?',(uid,))]

    def expect_subscription(self, uid, kind, callback):
        with self.connection() as db:
            db.execute('INSERT OR IGNORE INTO subscriptions VALUES(?,?,?,?,?,?)',
                       (uid,kind,'',callback,'creating',time.time()))

    def save_subscription(self, uid, kind, remote_id, status):
        with self.connection() as db:
            # A verification callback may arrive before the create response.
            # Never replace its newer enabled state with pending from create.
            db.execute("UPDATE subscriptions SET remote_id=?,status=CASE WHEN status='revoked' THEN status WHEN status=? AND ?=? "
                       'THEN status ELSE ? END,updated=? WHERE user_id=? AND kind=? AND (remote_id=? OR remote_id=?)',
                       (remote_id,'enabled',status,'webhook_callback_verification_pending',status,time.time(),uid,kind,'',remote_id))

    def forget_subscription(self, uid, kind):
        with self.connection() as db:
            db.execute('DELETE FROM subscriptions WHERE user_id=? AND kind=?',(uid,kind))

    def accept_subscription(self, sub, message_type):
        uid, kind, remote = sub['condition']['broadcaster_user_id'], sub['type'], sub['id']
        if not isinstance(remote,str) or not remote:
            return False
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM subscriptions WHERE user_id=? AND kind=?',(uid,kind)).fetchone()
            preference = db.execute('SELECT enabled FROM listeners WHERE user_id=?',(uid,)).fetchone()
            if not row or row['callback'] != sub['transport'].get('callback'):
                return False
            if row['remote_id'] and row['remote_id'] != remote:
                return False
            if message_type == 'revocation':
                if row['remote_id'] != remote:
                    return False
                db.execute('UPDATE subscriptions SET status=?,updated=? WHERE user_id=? AND kind=?',
                           ('revoked',time.time(),uid,kind))
                db.execute('UPDATE listeners SET message=? WHERE user_id=?',('subscription_revoked',uid))
                return True
            if not preference or not preference['enabled'] or row['status'] == 'revoked':
                return False
            auth = db.execute('SELECT state FROM auth_health WHERE user_id=?',(uid,)).fetchone()
            if auth and auth['state'] == 'reconnect_required':
                return False
            if message_type == 'webhook_callback_verification':
                db.execute('UPDATE subscriptions SET remote_id=?,status=?,updated=? WHERE user_id=? AND kind=?',
                           (remote,'enabled',time.time(),uid,kind))
                return True
            return row['remote_id'] == remote and row['status'] == 'enabled'

    def auth_health(self, uid):
        with self.connection() as db:
            row = db.execute('SELECT state,checked FROM auth_health WHERE user_id=?',(uid,)).fetchone()
            result = dict(row) if row else {'state':'checking','checked':0}
            if result['state'] == 'connected' and time.time() - result['checked'] > 3600:
                result['state'] = 'checking'
            return result

    def save_credentials_if_current(self, uid, previous, tokens, state):
        """CAS prevents an old refresh/revocation overwriting a newer login."""
        encrypted = self.cipher.encrypt(json.dumps(tokens).encode())
        with self.connection() as db:
            changed = db.execute('UPDATE users SET credentials=? WHERE id=? AND credentials=?',
                                 (encrypted,uid,previous)).rowcount
            if changed:
                db.execute('INSERT INTO auth_health VALUES(?,?,?) ON CONFLICT(user_id) '
                           'DO UPDATE SET state=excluded.state,checked=excluded.checked',
                           (uid,state,time.time()))
                if state == 'reconnect_required':
                    db.execute('DELETE FROM sessions WHERE user_id=?',(uid,))
            return bool(changed)

    def session(self, token):
        with self.connection() as db:
            row = db.execute('SELECT user_id,csrf FROM sessions WHERE hash=? AND expires>?',
                             (digest(token), time.time())).fetchone()
            return dict(row) if row else None

    def logout(self, token):
        with self.connection() as db:
            db.execute('DELETE FROM sessions WHERE hash=?', (digest(token),))

    def delete_account(self, uid):
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT 1 FROM subscriptions WHERE user_id=?',(uid,)).fetchone() or db.execute('SELECT 1 FROM listeners WHERE user_id=? AND enabled=1',(uid,)).fetchone():
                raise ValueError('Stop Twitch listening and wait for remote subscription cleanup before deletion.')
            tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            for table in ('capture_commands','capture_runs','donation_settings','stream_state','stream_sessions','sessions','overlays','rules','event_receipts','challenges','auth_health','listeners'):
                if table in tables:db.execute(f'DELETE FROM {table} WHERE user_id=?',(uid,))
            db.execute('DELETE FROM users WHERE id=?',(uid,))

    def profile(self, uid):
        with self.connection() as db:
            row = db.execute('SELECT id,login,owed,lifetime FROM users WHERE id=?', (uid,)).fetchone()
            if not row:
                raise ValueError('Unknown user')
            return dict(row)

    def observe_stream(self, uid, stream):
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            if stream is not None:
                if stream.get('user_id') != uid or not isinstance(stream.get('id'),str) or not stream['id'] or not isinstance(stream.get('started_at'),str):
                    raise ValueError('Invalid stream identity')
                db.execute('INSERT OR IGNORE INTO stream_sessions(user_id,stream_id,started) VALUES(?,?,?)',
                           (uid,stream['id'],stream['started_at']))
                db.execute("INSERT INTO stream_state VALUES(?,?,'live',?) ON CONFLICT(user_id) DO UPDATE SET stream_id=excluded.stream_id,state='live',checked=excluded.checked",(uid,stream['id'],time.time()))
            else:
                db.execute("INSERT INTO stream_state VALUES(?,NULL,'offline',?) ON CONFLICT(user_id) DO UPDATE SET state='offline',checked=excluded.checked",(uid,time.time()))

    def stream_unavailable(self, uid):
        with self.connection() as db:
            db.execute("INSERT INTO stream_state VALUES(?,NULL,'unavailable',?) ON CONFLICT(user_id) DO UPDATE SET state='unavailable',checked=excluded.checked",(uid,time.time()))

    def stream_summary(self, uid):
        with self.connection() as db:
            row = db.execute('SELECT s.state,s.checked,r.started,COALESCE(r.completed,0) AS completed FROM stream_state s LEFT JOIN stream_sessions r ON r.user_id=s.user_id AND r.stream_id=s.stream_id WHERE s.user_id=?',(uid,)).fetchone()
            result = dict(row) if row else {'state':'checking','checked':0,'started':None,'completed':0}
            if time.time()-result['checked']>120:
                result['state']='checking'
            return result

    def set_owed(self, uid, value):
        if type(value) is not int or not 0 <= value <= 1000000000:
            raise ValueError('Owed must be a whole number between 0 and 1000000000')
        with self.connection() as db:
            db.execute('UPDATE users SET owed=? WHERE id=?', (value, uid))
        return self.profile(uid)

    def rotate_overlay(self, uid):
        token = secrets.token_urlsafe(32)
        with self.connection() as db:
            db.execute('INSERT INTO overlays(hash,user_id) VALUES(?,?) '
                       'ON CONFLICT(user_id) DO UPDATE SET hash=excluded.hash', (digest(token), uid))
        return token

    def overlay(self, token, include_stream=False):
        with self.connection() as db:
            row = db.execute('SELECT users.id,owed,lifetime FROM users JOIN overlays ON users.id=overlays.user_id '
                             'WHERE overlays.hash=?', (digest(token),)).fetchone()
            if not row:
                return None
            result = {'owed':row['owed'],'lifetime':row['lifetime']}
            if include_stream:
                summary = self.stream_summary(row['id'])
                result['stream'] = {key:summary[key] for key in ('state','completed')}
            return result

    def rules(self, uid):
        with self.connection() as db:
            db.execute('INSERT OR IGNORE INTO rules(user_id) VALUES(?)', (uid,))
            row = dict(db.execute('SELECT * FROM rules WHERE user_id=?', (uid,)).fetchone())
            row.pop('user_id')
            return row

    def save_rules(self, uid, values):
        expected = {'reward_id','reward_reps','sub_reps','gift_reps','bits_unit','bits_reps'}
        bundles = {'bits_bundle_unit','bits_bundle_reps'}
        if not expected <= set(values) or set(values) - expected - bundles:
            raise ValueError('Unexpected rule fields')
        # Old clients may omit bundle fields; do not silently erase a saved rule.
        saved = self.rules(uid)
        values = {**{key: saved[key] for key in bundles}, **values}
        if not isinstance(values['reward_id'], str) or len(values['reward_id']) > 100:
            raise ValueError('Invalid reward ID')
        for key in (expected | bundles) - {'reward_id'}:
            minimum = 1 if key in ('reward_reps','bits_unit','bits_bundle_unit') else 0
            if type(values[key]) is not int or not minimum <= values[key] <= 100000:
                raise ValueError('Invalid rule value')
        bits_squats(0, values['bits_unit'], values['bits_reps'], values['bits_bundle_unit'], values['bits_bundle_reps'])
        with self.connection() as db:
            db.execute('UPDATE rules SET reward_id=?,reward_reps=?,sub_reps=?,gift_reps=?,bits_unit=?,bits_reps=?,bits_bundle_unit=?,bits_bundle_reps=? WHERE user_id=?',
                       tuple(values[k] for k in ('reward_id','reward_reps','sub_reps','gift_reps','bits_unit','bits_reps','bits_bundle_unit','bits_bundle_reps')) + (uid,))
        return self.rules(uid)

    def queue(self, uid):
        with self.connection() as db:
            return [dict(row) for row in db.execute("SELECT seq,viewer,target,done FROM challenges WHERE user_id=? AND done<target AND event_key NOT LIKE 'free:%' ORDER BY seq", (uid,))]

    def receive_event(self, uid, kind, message_id, event):
        """Commit a receipt with either support debt or a queued challenge."""
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            if not db.execute('SELECT id FROM users WHERE id=?', (uid,)).fetchone():
                raise ValueError('Unknown broadcaster')
            auth = db.execute('SELECT state FROM auth_health WHERE user_id=?',(uid,)).fetchone()
            if auth and auth['state'] == 'reconnect_required':
                raise ValueError('Broadcaster authorization revoked')
            if event.get('broadcaster_user_id') != uid:
                raise ValueError('Broadcaster mismatch')
            db.execute('INSERT OR IGNORE INTO rules(user_id) VALUES(?)', (uid,))
            rule = dict(db.execute('SELECT * FROM rules WHERE user_id=?', (uid,)).fetchone())
            target = 0
            key = kind + ':' + message_id
            amount = 0
            if kind == 'channel.channel_points_custom_reward_redemption.add':
                if not isinstance(event.get('id'), str) or not event['id']:
                    raise ValueError('Missing redemption ID')
                key = 'redemption:' + event['id']
                if rule['reward_id'] and event.get('reward', {}).get('id') == rule['reward_id']:
                    # Channel Points schedule reps, not additional future debt.
                    target = rule['reward_reps']
            elif kind == 'channel.subscribe':
                if type(event.get('is_gift')) is not bool:
                    raise ValueError('Missing gift flag')
                # Gift recipients also produce subscribe events; count gifts only
                # from subscription.gift, never twice.
                amount = 0 if event['is_gift'] else rule['sub_reps']
            elif kind in ('channel.subscription.gift','channel.cheer'):
                quantity = event.get('total' if kind.endswith('.gift') else 'bits')
                if type(quantity) is not int or not 1 <= quantity <= 10000000:
                    raise ValueError('Invalid event quantity')
                amount = quantity * rule['gift_reps'] if kind.endswith('.gift') else bits_squats(
                    quantity, rule['bits_unit'], rule['bits_reps'], rule['bits_bundle_unit'], rule['bits_bundle_reps'])
            else:
                raise ValueError('Unsupported event')
            if amount > 1000000000:
                raise ValueError('Event exceeds counter limit')
            receipt = db.execute('INSERT OR IGNORE INTO event_receipts VALUES(?,?,?,?,?)',
                                 (uid,key,kind,amount,time.time()))
            if not receipt.rowcount:
                return False
            updated = db.execute('UPDATE users SET owed=owed+? WHERE id=? AND owed+?<=1000000000', (amount,uid,amount))
            if not updated.rowcount:
                raise ValueError('Counter limit reached')
            if target:
                db.execute('INSERT INTO challenges(user_id,event_key,viewer,target) VALUES(?,?,?,?)',
                           (uid,key,str(event.get('user_name','Viewer'))[:100],target))
            return True
