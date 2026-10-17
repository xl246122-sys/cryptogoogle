"""Actual manual-fill projections. Notices never change inventory or execute orders."""
import hashlib
import json
import math
from decimal import Decimal
from .ai_review import decorate_exit_message
from .stop_monitor import classify_exit

def _average_entry(rows, fallback):
    num = den = Decimal(0)
    for row in rows:
        fill = row['fill']
        if fill['side'] != 'BUY' or fill.get('price') is None:
            continue
        qty = Decimal(str(fill['quantity']))
        num += Decimal(str(fill['price'])) * qty
        den += qty
    return float(num / den) if den else fallback

def v2_notice(contract, rows, bought, disposed, inventory, entry_at, now_ms, bid, fresh, series):
    """Exit reminder for a short-horizon-v2 plan. Returns (kind, quantity, message)."""
    entry = _average_entry(rows, contract.get('entry_price'))
    stop, tp1, tp2 = contract['stop_loss'], contract['target_tp1'], contract['target_tp2']
    invalidation = contract['invalidation_price']
    sold = disposed >= bought * Decimal(str(contract['tp1_fraction'])) - Decimal('0.00000001')
    bars = series or {}
    found = classify_exit(
        bid, now_ms, entry, entry_at, stop, tp1, tp2, invalidation, contract.get('reclaim_price'),
        contract.get('breakeven_price'), sold, contract['max_hold_minutes'],
        contract.get('time_stop_minutes') or 90, contract.get('time_stop_progress_r') or 0.3,
        bars.get('1m'), bars.get('15m'), bars.get('1h'), fresh)
    if found is None:
        return None, inventory, None
    kind, message = found
    message = decorate_exit_message(kind, message, contract)
    if kind == 'TP1_PARTIAL_EXIT':
        quantity = min(inventory, max(Decimal(0), bought * Decimal(str(contract['tp1_fraction'])) - disposed))
        if quantity <= 0:
            return None, inventory, None
        return kind, quantity, message
    return kind, inventory, message

def project_positions(actions, tracks, now_ms, bid=None, quote_at=None, series=None):
    replaced={r.get('replacesEventId') for r in actions if r.get('replacesEventId')}
    groups={}
    for row in actions:
        if row.get('recordType')=='MANUAL_FILL' and row.get('fill') and row['eventId'] not in replaced:
            groups.setdefault(row['fill']['positionId'],[]).append(row)
    reports=[]
    fresh = isinstance(bid,(float,int)) and not isinstance(bid,bool) and math.isfinite(bid) and bid>0 and isinstance(quote_at,(int,float)) and 0<=now_ms-quote_at<=10000
    for position,rows in sorted(groups.items()):
        rows.sort(key=lambda r:(r['fill']['executedAtMs'],r['fill']['fillId']))
        revision=hashlib.sha256(json.dumps(rows,sort_keys=True,allow_nan=False).encode()).hexdigest()
        alert_ids={r['alertId'] for r in rows}
        report={'positionId':position,'revision':revision,'source':'MANUAL_UNVERIFIED','atMs':now_ms,
                'remainingQuantity':None,'notice':None,'status':'UNMANAGED','reason':None}
        if len(alert_ids)!=1:
            report['reason']='POSITION_LINK_CONFLICT';reports.append(report);continue
        alert_id=next(iter(alert_ids));report['alertId']=alert_id
        contract=tracks.get(alert_id,{}).get('signalSnapshot',{})
        inventory=bought=disposed=Decimal(0);entry_at=None;approximate=False;unknown=False;bad=False
        for row in rows:
            f=row['fill'];qty=Decimal(str(f['quantity']));fee=f.get('commission')
            if f['executedAtMs']>now_ms: bad=True;break
            # Unknown quote/BNB fee affects P&L, but not BTC inventory.
            if f.get('commissionAsset')=='BTC' and fee is None: unknown=True
            base=Decimal(str(fee or 0)) if f.get('commissionAsset')=='BTC' else Decimal(0)
            if f['side']=='BUY':
                if inventory==0:
                    entry_at=f['executedAtMs'];bought=disposed=Decimal(0);approximate=f.get('timeApproximate',False)
                inventory+=qty-base;bought+=qty-base
            else:
                inventory-=qty+base;disposed+=qty+base
                if inventory < Decimal('-0.0000000001'): bad=True;break
                if abs(inventory)<Decimal('0.0000000001'): inventory=Decimal(0)
        if bad or unknown:
            report.update(reason='INVALID_INVENTORY' if bad else 'BTC_FEE_UNKNOWN');reports.append(report);continue
        report['remainingQuantity']=float(inventory)
        if inventory==0:
            report['status']='CLOSED';reports.append(report);continue
        keys=('stop_loss','invalidation_price','target_tp1','target_tp2','tp1_fraction','max_hold_minutes')
        if not all(isinstance(contract.get(k),(int,float)) and math.isfinite(contract[k]) and contract[k]>0 for k in keys):
            report['reason']='NO_VERIFIED_EXIT_PLAN';reports.append(report);continue
        if not contract['stop_loss']<=contract['invalidation_price']<contract['target_tp1']<=contract['target_tp2'] or contract['tp1_fraction']>1:
            report['reason']='INVALID_EXIT_PLAN';reports.append(report);continue
        deadline=entry_at+contract['max_hold_minutes']*60000
        report.update(status='MONITORING',deadlineMs=deadline,timeApproximate=approximate)
        kind=None;quantity=inventory;message=None
        if contract.get('rule_version') == 'short-horizon-v2':
            kind, quantity, message = v2_notice(contract, rows, bought, disposed, inventory, entry_at, now_ms, bid, fresh, series)
            if kind is None and not fresh:
                report['reason'] = 'QUOTE_UNAVAILABLE'
        elif now_ms>=deadline: kind='TIME_EXIT_APPROXIMATE' if approximate else 'TIME_EXIT'
        elif fresh:
            if bid<=contract['stop_loss']: kind='STOP_EXIT'
            elif bid<=contract['invalidation_price']: kind='INVALIDATION_EXIT'
            elif bid>=contract['target_tp2']: kind='TP2_EXIT'
            elif bid>=contract['target_tp1']:
                quantity=min(inventory,max(Decimal(0),bought*Decimal(str(contract['tp1_fraction']))-disposed))
                if quantity>0: kind='TP1_PARTIAL_EXIT'
        else: report['reason']='QUOTE_UNAVAILABLE'
        if kind:
            identity=hashlib.sha256((position+'|'+revision+'|'+kind).encode()).hexdigest()
            report['notice']={'id':'exit-'+identity,'eventType':'POSITION_EXIT_NOTICE','positionId':position,
                'alertId':alert_id,'revision':revision,'kind':kind,'quantity':float(quantity),'atMs':now_ms,
                'observedBid':bid if fresh else None,'quoteAtMs':quote_at if fresh else None,
                'timeApproximate':approximate,'message':message or '按记录的退出规则核对剩余持仓；提醒不代表已成交，系统未自动卖出。'}
        reports.append(report)
    return reports

def monitor_positions(library,store,now_ms,bid=None,quote_at=None,series=None):
    # Copy under the legacy ledger lock; do not hold it while SQLite writes.
    import copy
    with library.LIBRARY_LOCK:
        library._library_ensure()
        actions=copy.deepcopy(list(library.ACTION_EVENTS.values()))
        tracks=copy.deepcopy(library.OPEN_TRACKS)
    reports=project_positions(actions,tracks,now_ms,bid,quote_at,series)
    return store.reconcile_positions(reports,now_ms)
