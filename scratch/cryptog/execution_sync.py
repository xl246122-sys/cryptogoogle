"""Replay the durable user journal into research, including append-only corrections."""
import json
from .funnel import stage

SCHEMA='''CREATE TABLE IF NOT EXISTS action_mirrors(event_id TEXT PRIMARY KEY,state TEXT NOT NULL,error TEXT,updated_ms INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS fill_corrections(old_fill_id TEXT PRIMARY KEY,new_fill_id TEXT NOT NULL,position_id TEXT NOT NULL,at_ms INTEGER NOT NULL);'''


def mirror(ledger,row,bars_1m=None,bars_15m=None):
    event=row['eventId'];now=int(row.get('receivedAtMs') or row['actedAtMs'])
    with ledger.lock:
        done=ledger.store.db.execute("SELECT state FROM action_mirrors WHERE event_id=?",(event,)).fetchone()
        if done and done[0]=='DONE':return True
        try:
            f=row.get('fill')
            if f:
                original=row.get('replacesFillId')
                if original:
                    with ledger.store.db:
                        ledger.store.db.execute('INSERT OR IGNORE INTO fill_corrections VALUES(?,?,?,?)',(original,f['fillId'],f['positionId'],now))
                summary=row.get('executionSummary') or {}
                ledger.on_fill(f,signal_id=row.get('alertId'),latency=row.get('entryLatency'),
                               inventory_closed=summary.get('closed',False),bars_1m=bars_1m,bars_15m=bars_15m)
                paper=ledger._position('paper:'+f['positionId'])
                if paper and summary:
                    body=paper['state_payload'];body.update(executionSummary=summary,userNetPct=summary.get('wholeTradeNetPct'),accountingVersion='actual-cashflow-v2.1')
                    with ledger.store.db:
                        ledger.store.db.execute('UPDATE shadow_positions SET state=?,closed_ms=?,payload=? WHERE id=?',('CLOSED' if summary.get('closed') else 'OPEN',paper.get('closed_ms') if summary.get('closed') else None,json.dumps(body,ensure_ascii=False),paper['id']))
            stage(ledger,row['alertId'],row['actedAtMs'],row['recordType'],payload={'serverReceivedAtMs':now,'recordSource':row.get('recordSource'),'executionSummary':row.get('executionSummary')},event_id='action:'+event)
            with ledger.store.db:ledger.store.db.execute('INSERT OR REPLACE INTO action_mirrors VALUES(?,?,?,?)',(event,'DONE',None,now))
            return True
        except Exception as exc:
            with ledger.store.db:ledger.store.db.execute('INSERT OR REPLACE INTO action_mirrors VALUES(?,?,?,?)',(event,'ERROR',type(exc).__name__,now))
            return False


def reconcile(ledger,rows):
    by_id={r['eventId']:r for r in rows}
    for row in sorted(rows,key=lambda r:(r.get('receivedAtMs',r['actedAtMs']),r['eventId'])):
        if row.get('replacesEventId'):
            old=by_id.get(row['replacesEventId']) or {}
            row=dict(row,replacesFillId=(old.get('fill') or {}).get('fillId'))
        mirror(ledger,row)


def health(ledger):
    with ledger.lock:return dict(ledger.store.db.execute('SELECT state,count(*) FROM action_mirrors GROUP BY state'))
