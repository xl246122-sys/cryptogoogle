"""Transactional stage-one journal/outbox alongside the unchanged V1.12 ledger."""
import hashlib
import json
import sqlite3
import threading
import zlib

def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',',':'), allow_nan=False)

def decode_event(raw):
    return json.loads(zlib.decompress(raw) if isinstance(raw,bytes) else raw)

class EventStore:
    def __init__(self, path):
        self.lock = threading.RLock()
        self.db = sqlite3.connect(path, check_same_thread=False, timeout=10)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY, at_ms INTEGER NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS outbox(id TEXT PRIMARY KEY, payload TEXT NOT NULL, expires INTEGER NOT NULL,
            state TEXT NOT NULL DEFAULT 'PENDING', attempts INTEGER NOT NULL DEFAULT 0, due INTEGER NOT NULL DEFAULT 0,
            last_error TEXT, sent_ms INTEGER);
        CREATE TABLE IF NOT EXISTS opportunities(id TEXT PRIMARY KEY, payload TEXT NOT NULL, state TEXT NOT NULL, updated_ms INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS position_notices(id TEXT PRIMARY KEY, position_id TEXT NOT NULL,
            revision TEXT NOT NULL, payload TEXT NOT NULL, state TEXT NOT NULL, updated_ms INTEGER NOT NULL);
        ''')
        self.db.commit()

    def append(self, event_id, at_ms, kind, payload):
        text = canonical(payload)
        raw = zlib.compress(text.encode(), 3) if kind == 'EVALUATION' else text
        with self.lock, self.db:
            old = self.db.execute('SELECT payload,kind FROM events WHERE id=?',(event_id,)).fetchone()
            if old:
                if old != (raw,kind): raise ValueError('Event ID content conflict')
                return False
            self.db.execute('INSERT INTO events VALUES(?,?,?,?)',(event_id,at_ms,kind,raw))
            return True

    def record_evaluation(self, snapshot, decision):
        raw = canonical(snapshot)
        digest = hashlib.sha256(raw.encode()).hexdigest()
        self.append('evaluation:'+digest,snapshot['atMs'],'EVALUATION',{'input':snapshot,'decision':decision})
        # Immutable first shadow candidate per variant/confirmation; never enqueue.
        with self.lock, self.db:
            for row in decision.get('research',[]):
                candidate=row.get('candidate')
                if row.get('mode')=='SHADOW' and row.get('status')=='SHADOW_CANDIDATE' and candidate:
                    self.db.execute('INSERT OR IGNORE INTO events VALUES(?,?,?,?)',
                        ('research:'+candidate['id'],snapshot['atMs'],'RESEARCH_CANDIDATE',canonical(row)))
        return digest

    def enqueue(self, event_id, signal):
        # First immutable contract wins; retries cannot extend TTL or replace its target.
        with self.lock, self.db:
            self.db.execute('INSERT OR IGNORE INTO outbox(id,payload,expires) VALUES(?,?,?)',
                            (event_id,canonical(signal),signal['expires_at']))

    def opportunity(self, event_id, signal):
        with self.lock, self.db:
            row=self.db.execute('SELECT state FROM opportunities WHERE id=?',(event_id,)).fetchone()
            if row: return row[0]
            self.db.execute('INSERT INTO opportunities VALUES(?,?,?,?)',(event_id,canonical(signal),'BUY_CANDIDATE',signal['timestamp']))
            self.db.execute('INSERT INTO events VALUES(?,?,?,?)',('opportunity:'+event_id,signal['timestamp'],'BUY_CANDIDATE',canonical({'alertId':event_id,'signal':signal})))
            return 'BUY_CANDIDATE'

    def advance_opportunities(self, now, quote):
        from .cost_risk import entry_is_valid
        with self.lock, self.db:
            rows=self.db.execute("SELECT id,payload FROM opportunities WHERE state='BUY_CANDIDATE'").fetchall()
            for event_id,raw in rows:
                signal=json.loads(raw)
                state='EXPIRED' if now>=signal['expires_at'] else 'INVALIDATED' if quote and not entry_is_valid(signal,quote,now) else None
                if state:
                    self.db.execute('UPDATE opportunities SET state=?,updated_ms=? WHERE id=?',(state,now,event_id))
                    self.db.execute('INSERT INTO events VALUES(?,?,?,?)',('terminal:'+event_id,now,state,canonical({'alertId':event_id,'atMs':now})))
                    self.db.execute("UPDATE outbox SET state=? WHERE id=? AND state IN ('PENDING','SENDING')",(state,event_id))

    def claim(self, now, cooldown_ms=0):
        with self.lock, self.db:
            self.db.execute("UPDATE outbox SET state='EXPIRED' WHERE state IN ('PENDING','SENDING') AND expires<=?",(now,))
            last_sent = self.db.execute("SELECT max(sent_ms) FROM outbox WHERE state='SENT'").fetchone()[0]
            if last_sent is not None and now-last_sent < cooldown_ms:
                return None
            row = self.db.execute("SELECT id,payload FROM outbox WHERE state IN ('PENDING','SENDING') AND due<=? ORDER BY rowid LIMIT 1",(now,)).fetchone()
            if row:
                self.db.execute("UPDATE outbox SET state='SENDING',attempts=attempts+1,due=? WHERE id=?",(now+30000,row[0]))
                return row[0],json.loads(row[1])
        return None

    def finish(self, event_id, now, status, error=None):
        if status not in ('SENT','PENDING','INVALIDATED','EXPIRED','CANCELLED'): raise ValueError('Bad delivery state')
        with self.lock, self.db:
            self.db.execute("UPDATE outbox SET state=?,due=?,last_error=?,sent_ms=? WHERE id=? AND state IN ('PENDING','SENDING')",
                            (status,now+5000,error,now if status=='SENT' else None,event_id))

    def health(self):
        with self.lock:
            return dict(self.db.execute('SELECT state,count(*) FROM outbox GROUP BY state').fetchall())

    def reconcile_positions(self, reports, now):
        """Atomic shadow journal. A quote recovery cannot acknowledge a risk notice.

        Only ledger revision/closure supersedes notices; all observations remain auditable.
        This table is deliberately separate from BUY delivery/cooldown.
        """
        current = {r['positionId']: r for r in reports}
        with self.lock, self.db:
            for event_id, position, revision in self.db.execute(
                    "SELECT id,position_id,revision FROM position_notices WHERE state='ACTIVE'").fetchall():
                report = current.get(position)
                if report is None or report['revision'] != revision or report['status'] != 'MONITORING':
                    self.db.execute("UPDATE position_notices SET state='SUPERSEDED',updated_ms=? WHERE id=?", (now,event_id))
                    self.db.execute('INSERT INTO events VALUES(?,?,?,?)',
                        ('superseded:'+event_id,now,'POSITION_NOTICE_SUPERSEDED',canonical({'noticeId':event_id,'atMs':now})))
            for report in reports:
                notice = report.get('notice')
                if not notice: continue
                old = self.db.execute('SELECT payload FROM position_notices WHERE id=?',(notice['id'],)).fetchone()
                if old:
                    report['notice'] = json.loads(old[0])
                    continue
                raw = canonical(notice)
                self.db.execute('INSERT INTO position_notices VALUES(?,?,?,?,?,?)',
                    (notice['id'],report['positionId'],report['revision'],raw,'ACTIVE',now))
                self.db.execute('INSERT INTO events VALUES(?,?,?,?)',
                    (notice['id'],now,'POSITION_EXIT_NOTICE',raw))
            for report in reports:
                report['unresolvedNotices'] = [json.loads(row[0]) for row in self.db.execute(
                    "SELECT payload FROM position_notices WHERE position_id=? AND state='ACTIVE' ORDER BY updated_ms,id",
                    (report['positionId'],)).fetchall()]
        return reports

    def review_position_notice(self, notice_id, device, now):
        """Idempotent explicit review receipt, never a fill or risk dismissal."""
        event_id = 'position-review:'+hashlib.sha256((device+'|'+notice_id).encode()).hexdigest()
        with self.lock, self.db:
            row = self.db.execute('SELECT state FROM position_notices WHERE id=?',(notice_id,)).fetchone()
            if not row: return {'ok':False,'error':'NOTICE_NOT_FOUND'}
            if row[0] != 'ACTIVE': return {'ok':False,'error':'NOTICE_SUPERSEDED'}
            old = self.db.execute('SELECT payload FROM events WHERE id=?',(event_id,)).fetchone()
            if old: return json.loads(old[0])
            receipt = {'ok':True,'eventId':event_id,'noticeId':notice_id,'serverReceivedAtMs':now,
                       'kind':'USER_REVIEWED','deviceFingerprint':device}
            self.db.execute('INSERT INTO events VALUES(?,?,?,?)',
                (event_id,now,'POSITION_NOTICE_REVIEWED',canonical(receipt)))
            return receipt

    def evaluations(self):
        with self.lock:
            rows = self.db.execute("SELECT payload FROM events WHERE kind='EVALUATION' ORDER BY at_ms,id").fetchall()
        return [decode_event(r[0]) for r in rows]

    def close(self):
        with self.lock: self.db.close()
