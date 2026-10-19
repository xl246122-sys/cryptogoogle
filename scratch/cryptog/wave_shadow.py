"""Isolated prospective evidence journal. Never imports production send/order APIs."""
import hashlib
import json
import math
import sqlite3
from pathlib import Path


def encoded(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False)


def finite(value):
    return isinstance(value, (float, int)) and not isinstance(value, bool) and math.isfinite(value)


def extract_quote(snapshot, observed_ms):
    ticker = snapshot.get('ticker') or {}
    bid, ask = ticker.get('bid_price'), ticker.get('ask_price')
    source, received = ticker.get('timestamp'), snapshot.get('depthReceivedAtMs')
    offset, uncertainty = snapshot.get('clockOffsetMs'), snapshot.get('clockUncertaintyMs')
    values = [bid, ask, source, received, offset, uncertainty]
    valid = all(finite(v) for v in values)
    age = observed_ms + offset - source if valid else None
    latency = received + offset - source if valid else None
    good = bool(valid and 0 < bid < ask and uncertainty <= 1000 and uncertainty >= 0
                and abs(offset) <= 5000 and 0 <= age <= 5000
                and -uncertainty <= latency <= 5000 and received <= observed_ms
                and snapshot.get('healthy') is True and (snapshot.get('book') or {}).get('is_valid') is True)
    return dict(bid=bid, ask=ask, sourceMs=source, receivedMs=received,
        observedMs=observed_ms, clockOffsetMs=offset, clockUncertaintyMs=uncertainty,
        sourceAgeMs=age, sourceToReceiveMs=latency, healthy=good,
        depthUpdateId=snapshot.get('depthUpdateId'), source='PRODUCTION_BINANCE_WS_JOURNAL')


class ShadowStore:
    def __init__(self, path):
        self.db = sqlite3.connect(path, timeout=10)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS quotes(id TEXT PRIMARY KEY,at_ms INTEGER NOT NULL,payload TEXT NOT NULL);
          CREATE INDEX IF NOT EXISTS quote_time ON quotes(at_ms);
          CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY,feature_ms INTEGER NOT NULL,decision_ms INTEGER NOT NULL,payload TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS delivery(id TEXT PRIMARY KEY,payload TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS issues(id INTEGER PRIMARY KEY,at_ms INTEGER NOT NULL,kind TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS candidates(id TEXT PRIMARY KEY,due_ms INTEGER NOT NULL,payload TEXT NOT NULL,state TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS accounts(id TEXT PRIMARY KEY,cash REAL NOT NULL);
          CREATE TABLE IF NOT EXISTS positions(account TEXT PRIMARY KEY,payload TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS trades(id TEXT PRIMARY KEY,payload TEXT NOT NULL);
        ''')

    def set(self, key, value):
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO meta VALUES(?,?)', (key, encoded(value)))

    def get(self, key, default=None):
        row = self.db.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def issue(self, now, kind):
        with self.db:
            self.db.execute('INSERT INTO issues(at_ms,kind) VALUES(?,?)', (now, kind))

    def quote(self, identity, snapshot, observed_ms):
        quote = extract_quote(snapshot, observed_ms)
        with self.db:
            added = self.db.execute('INSERT OR IGNORE INTO quotes VALUES(?,?,?)',
                (identity, observed_ms, encoded(quote))).rowcount
        return quote, bool(added)

    def event(self, identity, feature_ms, decision_ms, payload, start_ms):
        if feature_ms > decision_ms or feature_ms < start_ms:
            raise ValueError('OUTSIDE_CAUSAL_WINDOW')
        payload = dict(payload, tradeEligible=False, featureMs=feature_ms, decisionMs=decision_ms,
            decisionLagMs=decision_ms-feature_ms, evidenceClass='PROSPECTIVE_SHADOW_OBSERVATION')
        with self.db:
            return bool(self.db.execute('INSERT OR IGNORE INTO events VALUES(?,?,?,?)',
                (identity, feature_ms, decision_ms, encoded(payload))).rowcount)

    def register_plan(self, identity, plan, feature_ms, decision_ms):
        # Freeze all 63 scenarios, never select a winner from observed outcomes.
        with self.db:
            for cost in [.24, .40, .60]:
                for delay in [0, 1, 2]:
                    key = f'{identity}:{cost}:{delay}'
                    payload = dict(plan, costPct=cost, delayMinutes=delay, featureMs=feature_ms,
                        decisionMs=decision_ms, account=f"{plan['group']}:{cost}:{delay}")
                    self.db.execute('INSERT OR IGNORE INTO candidates VALUES(?,?,?,?)',
                        (key, feature_ms+delay*60000, encoded(payload), 'PENDING'))

    def step_positions(self, quote):
        if not quote['healthy']:
            return
        now = quote['observedMs']
        with self.db:
            for account, text in self.db.execute('SELECT account,payload FROM positions').fetchall():
                p = json.loads(text)
                reason = ('STOP' if quote['bid'] <= p['stop'] else
                          'TARGET' if quote['bid'] >= p['target'] else
                          'EXHAUSTION' if p.get('exitDueMs') and now >= p['exitDueMs'] else
                          'TIME' if now >= p['openedMs']+p['holdMinutes']*60000 else None)
                if not reason:
                    continue
                net = (quote['bid']/p['entry']-1)*100-p['costPct']
                result = dict(p, closedMs=now, exit=quote['bid'], netPct=net, reason=reason,
                    eligibleForValidation=False, execution='SAMPLED_QUOTE_MODEL_NOT_ACTUAL_FILL',
                    costConvention='ASK_TO_BID_PLUS_FULL_REGISTERED_COST_CONSERVATIVE')
                self.db.execute('INSERT INTO trades VALUES(?,?)', (p['candidateId'], encoded(result)))
                self.db.execute('UPDATE accounts SET cash=cash+? WHERE id=?',
                    (p['notional']*(1+net/100), account))
                self.db.execute('DELETE FROM positions WHERE account=?', (account,))
            for identity, due, text in self.db.execute("SELECT id,due_ms,payload FROM candidates WHERE state='PENDING' AND due_ms<=? ORDER BY due_ms,id", (now,)).fetchall():
                p = json.loads(text)
                ask, cost = quote['ask'], p['costPct']
                risk = (1-p['stop']/ask)*100
                net = (p['target']/ask-1)*100-cost
                account = p['account']
                reason = ('LATE_OR_GAP' if now-due>10000 else
                    'ENTRY_BAND' if not p['entryLow']<=ask<=p['entryHigh'] else
                    'STOP_DISTANCE' if not .35-1e-9<=risk<=1.2+1e-9 else
                    'NET_SPACE' if net<p['minNet'] or (p['window']>15 and net<=p['minNet']) else
                    'NET_RR' if net/(risk+cost)<1.2 else
                    'ACCOUNT_OCCUPIED' if self.db.execute('SELECT 1 FROM positions WHERE account=?',(account,)).fetchone() else None)
                self.db.execute('UPDATE candidates SET state=? WHERE id=?', (reason or 'MODEL_OPENED', identity))
                if reason:
                    continue
                self.db.execute('INSERT OR IGNORE INTO accounts VALUES(?,500)', (account,))
                cash = self.db.execute('SELECT cash FROM accounts WHERE id=?',(account,)).fetchone()[0]
                notional = min(cash, cash*.5/(risk+cost))
                p.update(candidateId=identity, entry=ask, openedMs=now, notional=notional,
                         quoteSourceMs=quote['sourceMs'], quoteReceivedMs=quote['receivedMs'])
                self.db.execute('UPDATE accounts SET cash=cash-? WHERE id=?',(notional,account))
                self.db.execute('INSERT INTO positions VALUES(?,?)',(account,encoded(p)))

    def collect_delivery(self, source, since_ms):
        # Read only timing columns. Never read device identities, tokens or notice contents.
        rows = source.execute('''SELECT a.delivery_id,a.attempt,a.started_ms,a.finished_ms,a.result,
             r.kind,r.client_ms,r.server_ms FROM exit_attempts a LEFT JOIN exit_receipts r
             ON r.delivery_id=a.delivery_id WHERE a.started_ms>=?''', (since_ms,)).fetchall()
        with self.db:
            for identity, attempt, start, finish, result, kind, client, received in rows:
                key = hashlib.sha256(f'{identity}:{attempt}:{kind}'.encode()).hexdigest()
                payload = dict(attempt=attempt, sendStartedMs=start, sendFinishedMs=finish,
                    transportResult=result, receiptKind=kind, clientAtMs=client, serverReceiptMs=received,
                    platformDurationMs=finish-start if finish is not None and finish>=start else None,
                    receiptRoundTripMs=received-start if received is not None and received>=start else None,
                    oneWayDeliveryMs=None, displayConfirmed=False,
                    attribution='EXISTING_BASELINE_TRANSPORT_NOT_NEW_WAVE',
                    limitation='Client clock unsynchronized; OPENED measures click, not delivery; retries ambiguous')
                self.db.execute('INSERT OR REPLACE INTO delivery VALUES(?,?)',(key,encoded(payload)))

    def report(self):
        result = {name:self.db.execute(f'SELECT count(*) FROM {name}').fetchone()[0]
                  for name in ['quotes','events','delivery','issues','candidates','positions','trades']}
        result.update(tradeEligible=False, phoneDeliveryOfNewWave='NOT_SENT',
            status=self.get('status'), heartbeatMs=self.get('heartbeatMs'),
            latestDecisionMs=self.get('latestDecisionMs'), startMs=self.get('startMs'))
        result['candidateStates'] = dict(self.db.execute('SELECT state,count(*) FROM candidates GROUP BY state'))
        row=self.db.execute('SELECT payload FROM quotes ORDER BY at_ms DESC LIMIT 1').fetchone()
        result['latestQuote']=json.loads(row[0]) if row else None
        row=self.db.execute('SELECT at_ms,kind FROM issues ORDER BY id DESC LIMIT 1').fetchone()
        result['lastIssue']=dict(atMs=row[0],kind=row[1]) if row else None
        result['prospectiveQuoteCount']=self.db.execute('SELECT count(*) FROM quotes WHERE at_ms>=?',
            (self.get('startMs',2**63-1),)).fetchone()[0]
        result['receiptKinds']=dict(self.db.execute("SELECT json_extract(payload,'$.receiptKind'),count(*) FROM delivery GROUP BY json_extract(payload,'$.receiptKind')"))
        return result
