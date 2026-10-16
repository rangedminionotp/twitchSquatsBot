"""Tenant-scoped challenge execution and cumulative camera acknowledgments.

Camera frames stay in the browser. A lease is coordination, not proof of exercise.
"""
import secrets
import time


class ChallengeConflict(Exception):
    pass


class Challenges:
    def __init__(self, store, clock=time.time):
        self.store, self.clock = store, clock
        with store.connection() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS capture_runs (
                    id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
                    challenge_seq INTEGER NOT NULL UNIQUE REFERENCES challenges(seq),
                    status TEXT NOT NULL, accepted INTEGER NOT NULL DEFAULT 0,
                    page_id TEXT NOT NULL DEFAULT '', lease TEXT NOT NULL DEFAULT '',
                    lease_until REAL NOT NULL DEFAULT 0);
                CREATE UNIQUE INDEX IF NOT EXISTS one_live_capture ON capture_runs(user_id)
                    WHERE status IN ('active','paused');
                CREATE TABLE IF NOT EXISTS capture_commands (
                    user_id TEXT NOT NULL REFERENCES users(id), request_id TEXT NOT NULL,
                    run_id TEXT NOT NULL REFERENCES capture_runs(id),
                    PRIMARY KEY(user_id,request_id));
            ''')

    @staticmethod
    def identifier(value):
        if not isinstance(value,str) or not 1 <= len(value) <= 100:
            raise ValueError('Invalid identifier')
        return value

    def snapshot(self, db, uid, run_id=None):
        query = ("SELECT r.id,r.status,r.accepted,r.lease_until,c.seq,c.viewer,c.target,c.done,CASE WHEN c.event_key LIKE 'free:%' THEN 'free' ELSE 'queue' END AS mode "
                 'FROM capture_runs r JOIN challenges c ON c.seq=r.challenge_seq WHERE r.user_id=? ')
        row = db.execute(query + ('AND r.id=?' if run_id else "AND r.status IN ('active','paused')"),
                         (uid,run_id) if run_id else (uid,)).fetchone()
        if not row:
            return None
        result = dict(row)
        result['camera_connected'] = result.pop('lease_until') > self.clock()
        return result

    def state(self, uid):
        with self.store.connection() as db:
            return self.snapshot(db,uid)

    def start(self, uid, request_id, free_target=None):
        self.identifier(request_id)
        if free_target is not None and (type(free_target) is not int or not 1 <= free_target <= 500):
            raise ValueError('Free capture target must be 1–500')
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            prior = db.execute('SELECT run_id FROM capture_commands WHERE user_id=? AND request_id=?',
                               (uid,request_id)).fetchone()
            if prior:
                return self.snapshot(db,uid,prior['run_id'])
            run = self.snapshot(db,uid)
            if run:
                if (free_target is not None) != (run['mode']=='free'):
                    raise ChallengeConflict('Finish the current challenge or end the free set before switching modes.')
                run_id = run['id']
                db.execute("UPDATE capture_runs SET status='active' WHERE id=?",(run_id,))
            else:
                challenge = db.execute("SELECT seq FROM challenges WHERE user_id=? AND done<target AND event_key NOT LIKE 'free:%' ORDER BY seq LIMIT 1",
                                       (uid,)).fetchone()
                if free_target is not None:
                    row = db.execute('INSERT INTO challenges(user_id,event_key,viewer,target) VALUES(?,?,?,?)',
                                     (uid,'free:'+secrets.token_urlsafe(32),'Free capture',free_target))
                    challenge = {'seq':row.lastrowid}
                if not challenge:
                    raise ChallengeConflict('No queued challenge. Wait for a matching redemption.')
                run_id = secrets.token_urlsafe(32)
                db.execute("INSERT INTO capture_runs(id,user_id,challenge_seq,status) VALUES(?,?,?,'active')",
                           (run_id,uid,challenge['seq']))
            db.execute('INSERT INTO capture_commands VALUES(?,?,?)',(uid,request_id,run_id))
            return self.snapshot(db,uid,run_id)

    def end_free(self, uid, run_id):
        self.identifier(run_id)
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            run = self.snapshot(db,uid,run_id)
            if not run or run['mode']!='free':
                raise ChallengeConflict('Only a free capture set can be ended early.')
            db.execute("UPDATE capture_runs SET status='stopped',lease='',lease_until=0 WHERE user_id=? AND id=? AND status IN ('active','paused')",(uid,run_id))
            return self.snapshot(db,uid,run_id)

    def pause(self, uid, run_id):
        self.identifier(run_id)
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            if not self.snapshot(db,uid,run_id):
                raise ChallengeConflict('Challenge not found for this account.')
            # Invalidate the lease: a resumed page must acquire a fresh token.
            db.execute("UPDATE capture_runs SET status='paused',lease='',lease_until=0 WHERE user_id=? AND id=? AND status='active'",
                       (uid,run_id))
            return self.snapshot(db,uid,run_id)

    def claim(self, uid, run_id, page_id):
        self.identifier(run_id); self.identifier(page_id)
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            run = db.execute('SELECT * FROM capture_runs WHERE user_id=? AND id=?',(uid,run_id)).fetchone()
            if not run or run['status'] != 'active':
                raise ChallengeConflict('Start or resume this challenge first.')
            now = self.clock()
            if run['lease_until'] > now and run['page_id'] != page_id:
                raise ChallengeConflict('Another camera page owns this challenge. Close it and wait 15 seconds.')
            lease = run['lease'] if run['page_id'] == page_id and run['lease_until'] > now else secrets.token_urlsafe(32)
            db.execute('UPDATE capture_runs SET page_id=?,lease=?,lease_until=? WHERE id=?',
                       (page_id,lease,now+15,run_id))
            return {'run':self.snapshot(db,uid,run_id),'lease':lease,'lease_seconds':15}

    def progress(self, uid, run_id, lease, count):
        self.identifier(run_id); self.identifier(lease)
        if type(count) is not int or not 0 <= count <= 100000:
            raise ValueError('Count must be a bounded nonnegative integer')
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            run = db.execute('SELECT * FROM capture_runs WHERE user_id=? AND id=?',(uid,run_id)).fetchone()
            if not run:
                raise ChallengeConflict('Challenge not found for this account.')
            # Lost acknowledgments can safely retry, even after completion or pause.
            if count <= run['accepted']:
                return {'accepted':run['accepted'],'run':self.snapshot(db,uid,run_id)}
            if run['status'] != 'active' or run['lease_until'] <= self.clock() or not secrets.compare_digest(lease,run['lease']):
                raise ChallengeConflict('Camera lease expired or challenge paused. Reconcile before counting.')
            challenge = db.execute('SELECT target,done FROM challenges WHERE seq=?',(run['challenge_seq'],)).fetchone()
            delta = count-run['accepted']
            if delta > challenge['target']-challenge['done']:
                raise ValueError('Count exceeds remaining challenge')
            changed = db.execute('UPDATE users SET owed=MAX(0,owed-?),lifetime=lifetime+? WHERE id=? AND lifetime+?<=1000000000',
                                 (delta,delta,uid,delta)).rowcount
            if not changed:
                raise ChallengeConflict('Lifetime counter limit reached.')
            db.execute('UPDATE challenges SET done=done+? WHERE seq=?',(delta,run['challenge_seq']))
            # Only attribute reps to a recently observed live Twitch session.
            db.execute("UPDATE stream_sessions SET completed=completed+? WHERE user_id=? AND stream_id=(SELECT stream_id FROM stream_state WHERE user_id=? AND state='live' AND checked>?)",
                       (delta,uid,uid,time.time()-120))
            status = 'completed' if challenge['done']+delta == challenge['target'] else 'active'
            db.execute('UPDATE capture_runs SET accepted=?,status=? WHERE id=?',(count,status,run_id))
            return {'accepted':count,'run':self.snapshot(db,uid,run_id)}
