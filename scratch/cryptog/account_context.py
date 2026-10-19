"""Manual equity context. Unknown/stale balance never produces precise account risk."""
import json
import math
FRESH_MS=15*60_000

class AccountContext:
    def __init__(self,store):
        self.store=store
        with store.lock,store.db:
            store.db.execute('CREATE TABLE IF NOT EXISTS account_context(id INTEGER PRIMARY KEY,payload TEXT NOT NULL)')
    def put(self,payload,now):
        equity=payload.get('equityUsdt')
        if isinstance(equity,bool) or not isinstance(equity,(int,float)) or not math.isfinite(equity) or not 0<equity<=1e12:
            raise ValueError('INVALID_EQUITY')
        if type(payload.get('allPositionsRecorded')) is not bool:raise ValueError('COVERAGE_REQUIRED')
        body={'equityUsdt':equity,'allPositionsRecorded':payload['allPositionsRecorded'],'updatedMs':now,'source':'MANUAL_UNVERIFIED'}
        with self.store.lock,self.store.db:
            self.store.db.execute('INSERT OR REPLACE INTO account_context VALUES(1,?)',(json.dumps(body),))
        return body
    def report(self,positions,now):
        with self.store.lock:
            row=self.store.db.execute('SELECT payload FROM account_context WHERE id=1').fetchone()
        account=json.loads(row[0]) if row else None
        fresh=bool(account and 0<=now-account['updatedMs']<=FRESH_MS)
        active=[p for p in positions if p.get('status')!='CLOSED']
        complete=bool(account and account['allPositionsRecorded'] and all(p.get('plannedRiskUsdt') is not None for p in active))
        risk=sum(p['plannedRiskUsdt'] for p in active) if fresh and complete else None
        return {'source':'MANUAL_UNVERIFIED','updatedMs':account['updatedMs'] if account else None,'fresh':fresh,
                'coverageComplete':complete,'knownOpenPositions':len(active),'totalPlannedRiskUsdt':risk,
                'singleTradeRiskBudgetUsdt':account['equityUsdt']*.005 if fresh and complete else None,
                'equityUsdt':account['equityUsdt'] if fresh else None,'freshnessMinutes':15,
                'note':'仅覆盖已记录的 BTC 多单；不是交易所账户余额或持仓核验'}
