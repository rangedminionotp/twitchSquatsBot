"""Server-side ledger for privacy-preserving viewer squat contributions."""
import secrets
import time
from datetime import datetime
from zoneinfo import ZoneInfo


class CommunityConflict(Exception):
    """The request is valid JSON but conflicts with the run or daily ledger."""


class Community:
    DAILY_LIMIT = 100
    RUN_TARGET = 20
    MIN_CLIENT_REP_MS = 750
    MIN_SERVER_REP_SECONDS = 0.55

    def __init__(self, store, owner_id, timezone='America/Los_Angeles', clock=time.time):
        self.store = store
        self.owner_id = owner_id.strip() if isinstance(owner_id, str) else ''
        try:
            self.timezone = ZoneInfo(timezone)
        except Exception as error:
            raise ValueError('Invalid community timezone') from error
        self.clock = clock
        with self.store.connection() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS community_channels (
                    owner_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                    total INTEGER NOT NULL DEFAULT 0,
                    daily_limit INTEGER NOT NULL DEFAULT 100,
                    run_target INTEGER NOT NULL DEFAULT 20);
                CREATE TABLE IF NOT EXISTS community_viewer_daily (
                    owner_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    viewer_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    day TEXT NOT NULL, accepted INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY(owner_id,viewer_id,day));
                CREATE TABLE IF NOT EXISTS community_runs (
                    id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    viewer_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    day TEXT NOT NULL, target INTEGER NOT NULL,
                    calibrated INTEGER NOT NULL DEFAULT 0,
                    standing_angle REAL, squat_angle REAL, calibrated_at REAL,
                    accepted INTEGER NOT NULL DEFAULT 0, seq INTEGER NOT NULL DEFAULT 0,
                    client_elapsed_ms INTEGER NOT NULL DEFAULT 0,
                    started REAL NOT NULL, updated REAL NOT NULL,
                    status TEXT NOT NULL DEFAULT 'calibrating');
                CREATE UNIQUE INDEX IF NOT EXISTS community_one_active_run
                    ON community_runs(owner_id,viewer_id)
                    WHERE status IN ('calibrating','active');
                CREATE TABLE IF NOT EXISTS community_contributions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    viewer_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    run_id TEXT NOT NULL REFERENCES community_runs(id) ON DELETE CASCADE,
                    seq INTEGER NOT NULL, day TEXT NOT NULL, amount INTEGER NOT NULL,
                    created REAL NOT NULL, revoked INTEGER NOT NULL DEFAULT 0,
                    UNIQUE(run_id,seq));
            ''')

    def _day(self, now):
        return datetime.fromtimestamp(now, self.timezone).date().isoformat()

    def _channel(self, db):
        if not self.owner_id:
            raise CommunityConflict('Community channel is not configured')
        owner = db.execute('SELECT login FROM users WHERE id=?', (self.owner_id,)).fetchone()
        if not owner:
            raise CommunityConflict('Community channel owner has not logged in yet')
        db.execute('INSERT OR IGNORE INTO community_channels(owner_id,daily_limit,run_target) VALUES(?,?,?)',
                   (self.owner_id, self.DAILY_LIMIT, self.RUN_TARGET))
        channel = db.execute('SELECT * FROM community_channels WHERE owner_id=?', (self.owner_id,)).fetchone()
        return owner['login'], channel

    @staticmethod
    def _run(row):
        if not row:
            return None
        result = {key: row[key] for key in ('id','target','accepted','seq','status','calibrated')}
        result['elapsed_ms'] = row['client_elapsed_ms']
        return result

    def _daily(self, db, viewer_id, day):
        row = db.execute('SELECT accepted FROM community_viewer_daily WHERE owner_id=? AND viewer_id=? AND day=?',
                         (self.owner_id, viewer_id, day)).fetchone()
        return row['accepted'] if row else 0

    def public(self):
        now = self.clock()
        with self.store.connection() as db:
            login, channel = self._channel(db)
            return {'channel': login, 'community_total': channel['total'],
                    'daily_limit': channel['daily_limit'], 'run_target': channel['run_target'],
                    'day': self._day(now)}

    def viewer(self, viewer_id):
        now, day = self.clock(), None
        with self.store.connection() as db:
            login, channel = self._channel(db)
            day = self._day(now)
            accepted = self._daily(db, viewer_id, day)
            run = db.execute("SELECT * FROM community_runs WHERE owner_id=? AND viewer_id=? AND day=? "
                             "AND status IN ('calibrating','active') ORDER BY started DESC LIMIT 1",
                             (self.owner_id, viewer_id, day)).fetchone()
            return {'channel': login, 'community_total': channel['total'], 'today': accepted,
                    'daily_limit': channel['daily_limit'],
                    'remaining_today': max(0, channel['daily_limit'] - accepted),
                    'run_target': channel['run_target'], 'day': day, 'run': self._run(run)}

    def start(self, viewer_id):
        now, day = self.clock(), None
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            _login, channel = self._channel(db)
            if not db.execute('SELECT 1 FROM users WHERE id=?', (viewer_id,)).fetchone():
                raise ValueError('Unknown viewer')
            day = self._day(now)
            db.execute("UPDATE community_runs SET status='expired',updated=? WHERE owner_id=? AND viewer_id=? "
                       "AND day<>? AND status IN ('calibrating','active')", (now,self.owner_id,viewer_id,day))
            current = db.execute("SELECT * FROM community_runs WHERE owner_id=? AND viewer_id=? AND day=? "
                                 "AND status IN ('calibrating','active') ORDER BY started DESC LIMIT 1",
                                 (self.owner_id,viewer_id,day)).fetchone()
            if current:
                return self._run(current)
            accepted = self._daily(db, viewer_id, day)
            remaining = channel['daily_limit'] - accepted
            if remaining <= 0:
                raise CommunityConflict('Daily contribution limit reached')
            run_id = secrets.token_urlsafe(24)
            target = min(channel['run_target'], remaining)
            db.execute('INSERT INTO community_runs(id,owner_id,viewer_id,day,target,started,updated) '
                       'VALUES(?,?,?,?,?,?,?)', (run_id,self.owner_id,viewer_id,day,target,now,now))
            return self._run(db.execute('SELECT * FROM community_runs WHERE id=?',(run_id,)).fetchone())

    def calibrate(self, viewer_id, run_id, standing_angle, squat_angle, duration_ms):
        numbers = (standing_angle, squat_angle)
        if any(type(value) not in (int,float) for value in numbers) or type(duration_ms) is not int:
            raise ValueError('Invalid calibration values')
        if not 135 <= standing_angle <= 180 or not 45 <= squat_angle <= 150:
            raise ValueError('Calibration angles outside plausible range')
        if standing_angle - squat_angle < 25 or not 2500 <= duration_ms <= 30000:
            raise ValueError('Calibration motion is incomplete')
        now = self.clock()
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM community_runs WHERE id=? AND owner_id=? AND viewer_id=?',
                             (run_id,self.owner_id,viewer_id)).fetchone()
            if not row or row['day'] != self._day(now):
                raise CommunityConflict('Contribution run not found or expired')
            if row['status'] not in ('calibrating','active'):
                raise CommunityConflict('Contribution run is no longer active')
            if not row['calibrated']:
                db.execute("UPDATE community_runs SET calibrated=1,standing_angle=?,squat_angle=?,"
                           "calibrated_at=?,client_elapsed_ms=0,status='active',updated=? WHERE id=?",
                           (standing_angle,squat_angle,now,now,run_id))
            return self._run(db.execute('SELECT * FROM community_runs WHERE id=?',(run_id,)).fetchone())

    def progress(self, viewer_id, run_id, sequence, count, elapsed_ms):
        if any(type(value) is not int for value in (sequence,count,elapsed_ms)):
            raise ValueError('Progress values must be whole numbers')
        if sequence < 1 or count < 1 or elapsed_ms < 0:
            raise ValueError('Invalid progress values')
        now = self.clock()
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            _login, channel = self._channel(db)
            row = db.execute('SELECT * FROM community_runs WHERE id=? AND owner_id=? AND viewer_id=?',
                             (run_id,self.owner_id,viewer_id)).fetchone()
            if not row or row['day'] != self._day(now):
                raise CommunityConflict('Contribution run not found or expired')
            if (sequence == row['seq'] and count == row['accepted'] and
                    elapsed_ms == row['client_elapsed_ms']):
                return self._run(row)
            if row['status'] != 'active' or not row['calibrated']:
                raise CommunityConflict('Calibrate before contributing')
            if sequence != row['seq'] + 1 or count <= row['accepted']:
                raise CommunityConflict('Progress sequence or cumulative count is invalid')
            if count > row['target'] or elapsed_ms <= row['client_elapsed_ms']:
                raise CommunityConflict('Progress exceeds this run')
            if elapsed_ms < count * self.MIN_CLIENT_REP_MS:
                raise CommunityConflict('Reported movement is too fast')
            if now - row['calibrated_at'] < count * self.MIN_SERVER_REP_SECONDS:
                raise CommunityConflict('Contribution arrived too quickly')
            delta = count - row['accepted']
            today = self._daily(db, viewer_id, row['day'])
            if today + delta > channel['daily_limit']:
                raise CommunityConflict('Daily contribution limit reached')
            status = 'completed' if count == row['target'] or today + delta == channel['daily_limit'] else 'active'
            db.execute('UPDATE community_runs SET accepted=?,seq=?,client_elapsed_ms=?,status=?,updated=? WHERE id=?',
                       (count,sequence,elapsed_ms,status,now,run_id))
            db.execute('INSERT INTO community_viewer_daily(owner_id,viewer_id,day,accepted) VALUES(?,?,?,?) '
                       'ON CONFLICT(owner_id,viewer_id,day) DO UPDATE SET accepted=accepted+excluded.accepted',
                       (self.owner_id,viewer_id,row['day'],delta))
            db.execute('UPDATE community_channels SET total=total+? WHERE owner_id=?',(delta,self.owner_id))
            db.execute('INSERT INTO community_contributions(owner_id,viewer_id,run_id,seq,day,amount,created) '
                       'VALUES(?,?,?,?,?,?,?)',(self.owner_id,viewer_id,run_id,sequence,row['day'],delta,now))
            return self._run(db.execute('SELECT * FROM community_runs WHERE id=?',(run_id,)).fetchone())
