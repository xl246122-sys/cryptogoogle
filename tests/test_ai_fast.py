import copy
import unittest
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch
from test_ai_engine import make_snapshot, NOW, MockCache
from cryptog.ai_engine import AIEngine
from cryptog.storage import EventStore
from cryptog.ai_fast import fast_setup, AIFastWorker
from cryptog.ai_policy import trade_plan


def fixture():
    s=make_snapshot()
    # A contiguous ten-second crash followed by executed buying, not spoofed depth.
    prices=[68400,68200,67900,67600,67200,66950,66970,67000,67020,67040,67080]
    s['ticker'].update(ask_price=67085.,bid_price=67080.)
    s['recentTrades']=[dict(id=i,atMs=NOW-10000+i*1000,price=p,quantity=10.,buyerMaker=i<8) for i,p in enumerate(prices)]
    return s


class FastTests(unittest.TestCase):
    def test_reversal_has_real_target_stop_and_ten_second_window(self):
        s=fixture(); e=fast_setup(s)
        self.assertTrue(all(e['gates']))
        self.assertEqual(e['windowSeconds'],10)
        plan=trade_plan(e['decision'],s,s['ticker']['ask_price'])
        self.assertEqual(plan['holdSeconds'],600)
        self.assertGreaterEqual(plan['grossProfitPercent1'],.7)
        self.assertLess(e['decision']['stop_loss'],min(t['price'] for t in s['recentTrades']))

    def test_stale_gapped_partial_or_future_trades_do_not_trigger(self):
        for kind in ('stale','gap','partial','future'):
            s=fixture()
            if kind=='stale': s['atMs']+=3000
            if kind=='gap': s['recentTrades'][5]['id']=999
            if kind=='partial': s['recentTrades']=s['recentTrades'][3:]
            if kind=='future': s['recentTrades'][-1]['atMs']+=1
            self.assertIsNone(fast_setup(s),kind)

    def test_falling_knife_only_reports_event(self):
        s=fixture()
        for i,t in enumerate(s['recentTrades']):
            t.update(price=68400-i*150,buyerMaker=True)
        e=fast_setup(s)
        self.assertEqual(e['stage'],'MARKET_EVENT')
        self.assertNotIn('decision',e)

    def test_wide_spread_or_missing_resistance_cannot_buy(self):
        for kind in ('spread','resistance'):
            s=fixture()
            if kind=='spread': s['ticker']['bid_price']-=100
            else: s['series']['5m'][-4]['high']=67020
            self.assertNotIn('decision',fast_setup(s))

    def test_event_identity_survives_clock_bucket_boundary(self):
        with tempfile.TemporaryDirectory() as directory:
            store=EventStore(str(Path(directory)/'events.db'))
            try:
                s=fixture(); cache=MockCache(s); cache.fast_snapshot=lambda now:s
                stop=threading.Event();ai=AIEngine(store,cache,lambda *args:True,stop)
                with patch('cryptog.ai_fast.time.time',return_value=NOW/1000):
                    AIFastWorker(ai,stop).step()
                s['atMs']+=100
                with patch('cryptog.ai_fast.time.time',return_value=(NOW+100)/1000):
                    AIFastWorker(ai,stop).step()
                self.assertEqual(store.db.execute('SELECT count(*) FROM ai_stages').fetchone()[0],0)
                self.assertEqual(store.db.execute('SELECT count(*) FROM ai_signals').fetchone()[0],0)
            finally: store.close()


if __name__=='__main__': unittest.main()
