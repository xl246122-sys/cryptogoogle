import json
import pathlib
import tempfile
import threading
import unittest
from cryptog.storage import EventStore
from cryptog.observations import ObservationWorker

NOW = 1792000000000

def make_bars(count=30, base=100.0, trend=0.0):
    bars = []
    for i in range(count):
        t = NOW - (count - i) * 60000
        p = base + i * trend
        bars.append({
            'time': t,
            'close_time': t + 59999,
            'open': p,
            'high': p + 0.5,
            'low': p - 0.5,
            'close': p,
            'volume': 10.0,
            'taker_buy_base': 6.0,
            'is_closed': True
        })
    return bars

class ObservationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db_path = str(pathlib.Path(self.tmp) / 'events.sqlite3')
        self.store = EventStore(self.db_path)
        self.sent = []
        self.stop = threading.Event()
        self.worker = ObservationWorker(self.store, self.stop, lambda title, body, extra: (self.sent.append((title, body, extra)) or True))

    def tearDown(self):
        self.stop.set()
        self.store.close()

    def test_silent_observation_and_preparation_lifecycle(self):
        s={'atMs':NOW,'healthy':True,'ticker':{'bid_price':100}}
        self.worker.update(s,{})
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM observation_queue').fetchone()[0],0)
        d={'research':[{'label':'candidate','preparation':{'stopLoss':99,'targetTP1':102,'waiting':'buy confirmation'}}]}
        self.worker.update(s,d)
        self.worker=ObservationWorker(self.store,self.stop,lambda *args:True)
        self.worker.update(dict(s,atMs=NOW+90001),d)
        rows=self.store.db.execute('SELECT payload,state FROM observation_queue').fetchall()
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0][1],'CANCELLED')
        self.assertEqual(json.loads(rows[0][0])['lifecycle'],'EXPIRED')
        self.worker.update(dict(s,atMs=NOW+1800001),d)
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM observation_queue').fetchone()[0],2)

    def test_observation_worker_health(self):
        self.worker.heartbeat = NOW
        h = self.worker.health(NOW + 2000)
        self.assertIn('healthy', h)
        self.assertIn('pending', h)
        self.assertIn('expired', h)
        self.assertIn('sent', h)
        self.assertIsNone(h['error'])

    def test_only_delivered_entries_get_one_invalidation_notice(self):
        with self.store.db:
            for identity,state in [('sent','SENT'),('never-sent','INVALIDATED')]:
                self.store.db.execute('INSERT INTO opportunities VALUES(?,?,?,?)',(identity,'{}','INVALIDATED',NOW))
                self.store.db.execute('INSERT INTO outbox(id,payload,expires,state) VALUES(?,?,?,?)',(identity,'{}',NOW+90000,state))
        self.worker.update({'atMs':NOW,'healthy':False},{})
        self.worker.update({'atMs':NOW+1000,'healthy':False},{})
        rows=self.store.db.execute('SELECT payload FROM observation_queue').fetchall()
        self.assertEqual(len(rows),1)
        self.assertEqual(json.loads(rows[0][0])['opportunityId'],'sent')

if __name__ == '__main__':
    unittest.main()
