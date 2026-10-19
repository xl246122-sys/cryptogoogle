"""Corrected historical diagnostic, never independent promotion evidence.

Uses production evaluate and minute settlement. Quotes, latency and fills are
explicit scenarios because historical OHLC cannot establish delivery or queue fills.
"""
import argparse
import json
import sqlite3
import time
from bisect import bisect_left
from collections import Counter
from pathlib import Path

from .barriers import label_v2
from .config import V2_RISK_PER_TRADE_PCT, V2_PAPER_NOTIONAL_USDT
from .cost_model import cost_snapshot
from .engine_v2 import build_context, s5_baseline
from .evaluation import evaluate
from .input_contract import INPUT_CONTRACT
from .research_protocol import register_trial, save_once, whole_trade_metrics
from .validation import summarize_returns


def bars(db, tf, start=None, end=None, limit=None):
    sql = 'SELECT open_time,open,high,low,close,volume,close_time,taker_buy_base FROM klines WHERE symbol=? AND interval=?'
    args = ['BTCUSDT', tf]
    if start is not None:
        sql += ' AND open_time>=?'
        args.append(start)
    if end is not None:
        sql += ' AND open_time<? AND close_time<?'
        args.extend((end, end))
    sql += ' ORDER BY open_time '+('DESC LIMIT ?' if limit else 'ASC')
    if limit:
        args.append(limit)
    rows = list(db.execute(sql, args))
    if limit:
        rows.reverse()
    return [dict(zip(('time','open','high','low','close','volume','close_time','taker_buy_base'), r), is_closed=True) for r in rows]


def scenario_entry(signal, candles, earliest):
    """An escape/stop during delivery delay voids the simulated order as well."""
    for candle in candles:
        if candle['time'] >= signal['expires_at']:
            break
        if candle['time'] >= earliest and signal['entry_min'] <= candle['open'] <= signal['entry_max']:
            return candle
        if candle['high'] > signal['entry_max']*1.0025 or candle['low'] <= signal['stop_loss']:
            break
    return None


def run(db, start, end, friction=.24, delay_ms=60000, cadence_ms=300000):
    if friction < .24 or delay_ms < 0 or cadence_ms < 60000 or cadence_ms % 60000:
        raise ValueError('Invalid scenario')
    series = {tf: bars(db, tf, end=end) for tf in ('5m', '15m', '1h', '4h', '1d')}
    closes = {tf: [b['close_time'] for b in seq] for tf, seq in series.items()}
    def window(tf, now, count):
        at = bisect_left(closes[tf], now)
        return series[tf][max(0, at-count):at]
    seen, observed = set(), {}
    trades, active, curve = [], [], []
    cash = V2_PAPER_NOTIONAL_USDT
    counters = Counter()
    context, context_at = None, None
    started = time.time()
    for index, now in enumerate(range(start, end, cadence_ms)):
        # Only proceeds settled by this decision time may finance another trade.
        remaining = []
        for position in active:
            if position['closedMs'] <= now:
                cash += position['notional']*(1+position['netPct']/100)
            else:
                remaining.append(position)
        active = remaining
        boundary = now//900000*900000
        if boundary != context_at:
            context_at = boundary
            context = build_context(window('1d', now, 299), window('4h', now, 299),
                                    window('1h', now, 299), window('15m', now, 300), now)
            if context:
                context['s5VolumeBaseline'] = s5_baseline(window('15m', now, 30*96))
        recent = {tf: window(tf, now, count) for tf, count in INPUT_CONTRACT['windows'].items() if tf != '1m'}
        recent['1m'] = bars(db, '1m', end=now, limit=47)
        if not context or len(recent['1m']) < 47:
            counters['insufficientWarmup'] += 1
            continue
        price = recent['1m'][-1]['close']
        ticker = dict(symbol='BTCUSDT', timestamp=now, price=price, ask_price=price*1.00005,
                      bid_price=price*.99995, high24h=price, low24h=price, change24h=0)
        cost = cost_snapshot(now, {'frictionPct': friction})
        snapshot = dict(atMs=now, healthy=True, issues=[], series=recent, context=context,
                        inputContract=INPUT_CONTRACT, ticker=ticker,
                        book=dict(is_valid=True, spread=.01, imbalance=0, bid_vol=1, ask_vol=1), costSnapshot=cost)
        result = evaluate(snapshot)
        counters[result['status']] += 1
        for item in result.get('shortHorizonV2', {}).get('candidates', []):
            key = item.get('candidateId')
            if key:
                observed.setdefault(key, dict(module=item['module'], firstMs=now, issue=item.get('issue')))
        signal = result.get('signal')
        if not signal or signal['alert_id'] in seen:
            continue
        seen.add(signal['alert_id'])
        if any(p['module'] == signal['module'] for p in active):
            counters['moduleOverlap'] += 1
            continue
        # An open price strictly after the assumed delivery delay is a model,
        # not a claim that a limit merely touching inside OHLC filled.
        earliest = ((now+delay_ms+59999)//60000)*60000
        entries = bars(db, '1m', start=now, end=min(end, signal['expires_at']))
        entry = scenario_entry(signal, entries, earliest)
        if entry is None:
            counters['unfilled'] += 1
            continue
        risk = (1-signal['stop_loss']/entry['open'])*100
        equity = cash+sum(p['notional'] for p in active)
        notional = equity*V2_RISK_PER_TRADE_PCT/(risk+cost['frictionPct'])
        if notional > cash or risk <= 0:
            counters['cashConstraint'] += 1
            continue
        signal = dict(signal, entry_price=entry['open'], filledAt=entry['time'])
        horizon = min(end, entry['time']+360*60000)
        path = bars(db, '1m', start=entry['time'], end=horizon)
        trail = bars(db, '15m', start=entry['time']-130*900000, end=horizon)
        label = label_v2(signal, path, trail)
        if label.get('closedAt') is None:
            counters['unsettled'] += 1
            continue
        trade = dict(candidateId=signal['alert_id'], module=signal['module'], openedMs=entry['time'],
                     closedMs=label['closedAt'], netPct=label['pnlPct'], r=label['r'], notional=notional,
                     outcome=label['outcome'], eligibleForValidation=label.get('eligibleForValidation') is True,
                     uncertaintyReasons=label.get('uncertaintyReasons'), conservativePnlPct=label.get('conservativePnlPct'),
                     legs=label['legs'])
        cash -= notional
        active.append(trade)
        trades.append(trade)
        curve.append(dict(atMs=now, availableCash=cash, reservedNotional=sum(p['notional'] for p in active)))
        if index % 1000 == 0:
            print(f'replay {index} checkpoints, {len(trades)} trades', flush=True)
    final_cash = cash+sum(p['notional']*(1+p['netPct']/100) for p in active)
    modules = {}
    for module in ('S1','S2','S3','S4'):
        rows = [r for r in trades if r['module'] == module]
        stats = summarize_returns([r['netPct'] for r in rows if r['eligibleForValidation']], end-start)
        # summarize_returns defaults to one trial for legacy callers. That is
        # not evidence of this project's complete experiment history.
        stats.update(nTrials=None, dsr=None, selectionCorrectionStatus='UNKNOWN_TRIAL_HISTORY')
        if stats['profitFactor'] == float('inf'):
            stats['profitFactor'] = None
            stats['noLosses'] = True
        modules[module] = dict(**whole_trade_metrics(rows), diagnosticStatistics=stats,
                               promotion={'passes': False, 'reason': 'Previously viewed history; synthetic execution assumptions'})
    return dict(status='DIAGNOSTIC_ONLY', startMs=start, endMs=end, elapsedSeconds=time.time()-started,
                scenario=dict(frictionPct=friction, delayMs=delay_ms, cadenceMs=cadence_ms, spreadPct=.01,
                              latencyMeasured=False, historicalBookAvailable=False),
                limitations=['5m decision sampling can miss intrabar opportunities' if cadence_ms == 300000 else 'minute sampling can miss tick opportunities',
                             'synthetic quotes and fills; no independent OOS claim',
                             'full notional reserved to final exit; partial-sale cash is not reused',
                             'capital curve is cash/reserved capital, not mark-to-market drawdown'],
                counters=dict(counters), candidates=list(observed.values()), modules=modules,
                trades=trades, capital=dict(initial=500, finalScenarioCash=final_cash, curve=curve))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--db', required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--trial-id', required=True)
    parser.add_argument('--manifest-sha256', required=True)
    parser.add_argument('--days', type=int, default=30)
    parser.add_argument('--friction', type=float, default=.24)
    parser.add_argument('--delay-ms', type=int, default=60000)
    args = parser.parse_args()
    folder = Path(args.out)
    register_trial(folder, args.trial_id, args.manifest_sha256, vars(args), int(time.time()*1000))
    db = sqlite3.connect(Path(args.db).resolve().as_uri()+'?mode=ro', uri=True)
    try:
        end = db.execute("SELECT max(close_time)+1 FROM klines WHERE symbol='BTCUSDT' AND interval='1m'").fetchone()[0]
        report = run(db, end-args.days*86400000, end, args.friction, args.delay_ms)
        save_once(folder/(args.trial_id+'.result.json'), report)
        print(json.dumps(dict(status=report['status'], counters=report['counters'], modules=report['modules']), ensure_ascii=False))
    finally:
        db.close()


if __name__ == '__main__':
    main()
