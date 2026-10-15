import unittest
import tempfile
from pathlib import Path
from cryptog.positions import project_positions
from cryptog.storage import EventStore

NOW=1700000000000
def fill(event='buy',side='BUY',quantity=1,at=NOW,**extra):
    return {'recordType':'MANUAL_FILL','eventId':event,'alertId':'alert','fill':dict(fillId=event,positionId='p',side=side,quantity=quantity,executedAtMs=at,commission=0,commissionAsset='USDT',timeApproximate=False,**extra)}
TRACK={'alert':{'signalSnapshot':dict(stop_loss=98,invalidation_price=99,target_tp1=102,target_tp2=104,tp1_fraction=.5,max_hold_minutes=90)}}
def check(rows,bid=102,now=NOW+1000,quote=None):
    return project_positions(rows,TRACK,now,bid,now if quote is None else quote)[0]

class PositionTests(unittest.TestCase):
    def test_review_is_idempotent_device_scoped_and_does_not_close_position(self):
        store=EventStore(':memory:')
        try:
            report=store.reconcile_positions([check([fill()],97)],NOW+1000)[0]
            notice=report['notice']['id']
            receipt=store.review_position_notice(notice,'device-a',NOW+2000)
            self.assertEqual(receipt,store.review_position_notice(notice,'device-a',NOW+3000))
            self.assertNotEqual(receipt['eventId'],store.review_position_notice(notice,'device-b',NOW+3000)['eventId'])
            self.assertEqual(store.db.execute('SELECT state FROM position_notices WHERE id=?',(notice,)).fetchone()[0],'ACTIVE')
            self.assertFalse(store.review_position_notice('missing','device-a',NOW)['ok'])
            store.reconcile_positions([check([fill(),fill('s','SELL',1,NOW+1)])],NOW+4000)
            self.assertEqual(store.review_position_notice(notice,'device-a',NOW+5000)['error'],'NOTICE_SUPERSEDED')
        finally:store.close()
    def test_notice_survives_restart_and_quote_recovery_without_duplicate(self):
        with tempfile.TemporaryDirectory() as directory:
            path=str(Path(directory)/'events.sqlite3')
            store=EventStore(path)
            first=store.reconcile_positions([check([fill()],97)],NOW+1000)[0]['notice']
            store.close();store=EventStore(path)
            try:
                again=store.reconcile_positions([check([fill()],97,now=NOW+2000)],NOW+2000)[0]
                self.assertEqual(again['notice'],first)
                recovered=store.reconcile_positions([check([fill()],100)],NOW+3000)[0]
                self.assertEqual(recovered['unresolvedNotices'],[first])
                self.assertEqual(store.db.execute("SELECT count(*) FROM events WHERE kind='POSITION_EXIT_NOTICE'").fetchone()[0],1)
            finally:store.close()

    def test_correction_and_close_supersede_old_notice_without_erasing_history(self):
        store=EventStore(':memory:')
        try:
            first=store.reconcile_positions([check([fill()])],NOW+1000)[0]['notice']
            correction=fill('c',quantity=.4);correction['replacesEventId']='buy'
            current=store.reconcile_positions([check([fill(),correction])],NOW+2000)[0]
            self.assertEqual(len(current['unresolvedNotices']),1)
            self.assertEqual(current['unresolvedNotices'][0]['quantity'],.2)
            self.assertEqual(store.db.execute('SELECT state FROM position_notices WHERE id=?',(first['id'],)).fetchone()[0],'SUPERSEDED')
            closed=store.reconcile_positions([check([fill(),correction,fill('s','SELL',.4,NOW+1)])],NOW+3000)[0]
            self.assertEqual(closed['unresolvedNotices'],[])
            self.assertEqual(store.db.execute("SELECT count(*) FROM events WHERE kind='POSITION_EXIT_NOTICE'").fetchone()[0],2)
        finally:store.close()

    def test_partial_exit_uses_remaining_target_not_repeated_half(self):
        r=check([fill()]);self.assertEqual(r['notice']['quantity'],.5)
        r=check([fill(),fill('s','SELL',.2,NOW+1)]);self.assertAlmostEqual(r['notice']['quantity'],.3)
        r=check([fill(),fill('s','SELL',.5,NOW+1)]);self.assertIsNone(r['notice'])
    def test_full_close_no_notice(self):
        self.assertEqual(check([fill(),fill('s','SELL',1,NOW+1)])['status'],'CLOSED')
    def test_stop_and_invalidation_and_second_target(self):
        for price,kind in [(97,'STOP_EXIT'),(98.5,'INVALIDATION_EXIT'),(105,'TP2_EXIT')]:
            self.assertEqual(check([fill()],price)['notice']['kind'],kind)
    def test_time_exit_still_runs_without_quote(self):
        r=check([fill()],None,NOW+90*60000);self.assertEqual(r['notice']['kind'],'TIME_EXIT');self.assertIsNone(r['notice']['observedBid'])
    def test_old_quote_does_not_trigger_price_exit(self):
        r=check([fill()],97,NOW+20000,NOW);self.assertIsNone(r['notice']);self.assertEqual(r['reason'],'QUOTE_UNAVAILABLE')
    def test_correction_changes_revision_and_inventory(self):
        corrected=fill('corrected',quantity=.4);corrected['replacesEventId']='buy'
        before=check([fill()]);after=check([fill(),corrected])
        self.assertEqual(after['remainingQuantity'],.4);self.assertEqual(after['notice']['quantity'],.2)
        self.assertNotEqual(before['revision'],after['revision'])
    def test_stable_notice_id_on_repeated_evaluations(self):
        self.assertEqual(check([fill()])['notice']['id'],check([fill()],now=NOW+2000)['notice']['id'])
    def test_unknown_btc_fee_blocks_quantity_but_unknown_usdt_fee_does_not(self):
        a=fill();a['fill'].update(commission=None,commissionAsset='BTC')
        self.assertEqual(check([a])['reason'],'BTC_FEE_UNKNOWN')
        a['fill']['commissionAsset']='USDT';self.assertEqual(check([a])['remainingQuantity'],1)
    def test_unlinked_position_not_automatically_assigned_plan(self):
        self.assertEqual(project_positions([fill()],{},NOW+1000,102,NOW)[0]['reason'],'NO_VERIFIED_EXIT_PLAN')
    def test_reopening_starts_new_deadline(self):
        rows=[fill(),fill('s','SELL',1,NOW+1),fill('b2','BUY',1,NOW+60000)]
        self.assertEqual(check(rows,now=NOW+60001)['deadlineMs'],NOW+60000+90*60000)
    def test_unknown_time_is_visible_on_deadline_notice(self):
        a=fill();a['fill']['timeApproximate']=True
        self.assertEqual(check([a],None,NOW+90*60000)['notice']['kind'],'TIME_EXIT_APPROXIMATE')

if __name__=='__main__':unittest.main()
