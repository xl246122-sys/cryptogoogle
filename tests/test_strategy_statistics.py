import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

spec=importlib.util.spec_from_file_location('history_validation',Path(__file__).resolve().parents[1]/'scripts/validate_strategy_history.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


class StatisticsTests(unittest.TestCase):
    def test_invalidated_candidate_never_reenters_and_cost_is_applied(self):
        with tempfile.TemporaryDirectory() as folder:
            path=str(Path(folder)/'history.sqlite3')
            with sqlite3.connect(path) as db:
                db.executescript('CREATE TABLE events(id TEXT,at_ms INTEGER,kind TEXT,payload TEXT); CREATE TABLE ai_evaluations(is_buy INTEGER);')
                sig=dict(timestamp=1000,expires_at=91000,max_hold_minutes=1,entry_min=99,entry_max=101,
                         stop_loss=98,invalidation_price=99,target_tp1=104,target_tp2=104,
                         strategy='TEST',rule_version='fixture',tp1_fraction=1.)
                db.execute('INSERT INTO events VALUES(?,?,?,?)',('candidate',1000,'BUY_CANDIDATE',json.dumps(dict(alertId='x',signal=sig))))
                db.execute('INSERT INTO events VALUES(?,?,?,?)',('terminal',11000,'INVALIDATED',json.dumps(dict(alertId='x'))))
                for at,bid,ask in [(1000,99.99,100),(6000,99.99,100),(11000,98.9,99),(16000,100,100.01),(21000,104,104.01)]:
                    p=dict(input=dict(healthy=True,ticker=dict(bid_price=bid,ask_price=ask,timestamp=at)))
                    db.execute('INSERT INTO events VALUES(?,?,?,?)',(str(at),at,'EVALUATION',json.dumps(p)))
            db.close()
            result=module.validate(path)
            self.assertEqual(result['trials'][2]['state'],'INVALIDATED_BEFORE_ENTRY')
            first=result['trials'][0]
            self.assertEqual(first['exitReason'],'STRUCTURE_EXIT')
            self.assertAlmostEqual(first['netPctByCost']['0.11'],-1.21)
            self.assertEqual(result['evidenceVerdict'],'INSUFFICIENT_FOR_STRATEGY_VALIDATION')


if __name__=='__main__': unittest.main()
