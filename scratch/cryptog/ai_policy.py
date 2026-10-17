"""Spot-only AI trade contracts. No dependency on baseline strategies."""
import math
from datetime import datetime, timezone, timedelta

MODULES = {
    'FLASH_DROP_REBOUND': ('暴跌反弹', .7, 4., 0., 2.5, 10, 360),
    'FLASH_REBOUND_FAST': ('急跌瞬时回弹', .7, 4., 0., 1., 0, 30),
    'RANGE_SUPPORT_BOUNCE': ('区间震荡', .7, 2., 0., 1.5, 5, 360),
    'TREND_BREAKOUT_CONFIRM': ('上涨大趋势', .7, None, 0., 1.2, 10, 360),
}

def rolling_windows(snapshot):
    result = {}
    for minutes in (10, 30, 60, 120, 240, 360):
        tf, step = ('1m', 60000) if minutes <= 30 else ('5m', 300000)
        count = minutes * 60000 // step
        bars = snapshot.get('series', {}).get(tf, [])[-count:]
        if len(bars) != count or any(not b.get('is_closed') for b in bars):
            result[str(minutes)] = {'available': False}
            continue
        if any(b['time']-a['time'] != step for a,b in zip(bars,bars[1:])):
            result[str(minutes)] = {'available': False}
            continue
        low, high = min(b['low'] for b in bars), max(b['high'] for b in bars)
        result[str(minutes)] = {'available': True, 'low': low, 'high': high,
            'changePct': (bars[-1]['close']/bars[0]['open']-1)*100,
            'lowAtMs': next(b['time'] for b in bars if b['low']==low),
            'highAtMs': next(b['time'] for b in bars if b['high']==high)}
    return result

def target_evidence(snapshot, ask, tp1, tp2, module=None):
    """Independent AI policy: confirmed swing highs bound targets, never raise them."""
    if not all(type(v) in (int,float) and math.isfinite(v) and v > 0 for v in (ask,tp1,tp2)) or not ask < tp1 <= tp2:
        raise ValueError('INVALID_TARGET_PRICES')
    levels = []
    frames = ('1m','5m') if module == 'FLASH_REBOUND_FAST' else ('5m','15m') if module == 'RANGE_SUPPORT_BOUNCE' else ('15m','1h','4h') if module == 'TREND_BREAKOUT_CONFIRM' else ('5m','15m','1h')
    for tf in frames:
        bars = snapshot.get('series', {}).get(tf, [])[-48:]
        for left, pivot, right in zip(bars, bars[1:], bars[2:]):
            if not all(b.get('is_closed') for b in (left, pivot, right)):
                continue
            if any(b.get('close_time', snapshot['atMs']) >= snapshot['atMs'] for b in (left,pivot,right)):
                continue
            step = {'1m':60000,'5m':300000,'15m':900000,'1h':3600000,'4h':14400000}[tf]
            if pivot['time']-left['time'] != step or right['time']-pivot['time'] != step:
                continue
            high = pivot['high']
            # Ignore a high only after two subsequent closes have confirmed a break.
            later = [b for b in bars if b['time'] > pivot['time'] and b.get('is_closed') and b['close_time'] < snapshot['atMs']]
            broken = any(b['time']-a['time']==step and a['close'] > high*1.0005 and b['close'] > high*1.0005 for a,b in zip(later,later[1:]))
            prominence = (high-max(left['low'],right['low']))/high*100 if high > 0 else 0
            if broken or prominence < .10:
                continue
            if math.isfinite(high) and high > ask and high > max(left['high'], right['high']):
                levels.append((high, tf, pivot['time']))
    levels = sorted(set(levels))
    if not levels:
        raise ValueError('NO_CONFIRMED_TARGET_RESISTANCE')
    distinct = sorted(set(x[0] for x in levels))
    first, second = distinct[0], distinct[min(1, len(distinct)-1)]
    if tp1 > math.floor(first*.9995*100)/100 or tp2 > math.floor(second*.9995*100)/100:
        raise ValueError('TARGET_CROSSES_CONFIRMED_RESISTANCE')
    return {'targetPolicyVersion':'ai-resistance-v2', 'targetResistance1':first,
            'targetResistance2':second, 'targetAnchorTimeframe':levels[0][1],
            'targetAnchorTimeMs':levels[0][2]}


def trade_plan(decision, snapshot, ask):
    module = decision.get('scenario')
    if module not in MODULES:
        raise ValueError('UNKNOWN_MODULE')
    if module == 'FLASH_DROP_REBOUND':
        bars=[b for b in snapshot.get('series',{}).get('5m',[]) if b.get('is_closed') and snapshot['atMs']-21600000 <= b['time'] and b['close_time']<snapshot['atMs']]
        peak=0.; drop=0.
        for b in bars:
            # Use previous bars' peaks: OHLC cannot prove intrabar high/low ordering.
            if peak: drop=max(drop,(peak-b['low'])/peak*100)
            peak=max(peak,b['high'])
        if len(bars)<3 or not 1<=drop<=10 or bars[-1]['low']<bars[-2]['low'] or ask<min(b['low'] for b in bars)*1.0015:
            raise ValueError('DROP_OR_STABILIZATION_NOT_CONFIRMED')
    name, pmin, pmax, smin, smax, hmin, hmax = MODULES[module]
    hold = decision.get('hold_minutes')
    if type(hold) is not int or not hmin <= hold <= hmax:
        raise ValueError('HOLD_TIME_OUTSIDE_MODULE')
    if module == 'FLASH_REBOUND_FAST' and (type(decision.get('hold_seconds')) is not int or not 10 <= decision['hold_seconds'] <= 1800):
        raise ValueError('FAST_HOLD_SECONDS_REQUIRED')
    reason = decision.get('summary_zh')
    if not isinstance(reason,str) or not 1 <= len(reason.strip()) <= 25:
        raise ValueError('REASON_MUST_BE_1_TO_25_CHARACTERS')
    tp, stop = decision['target_tp1'], decision['stop_loss']
    if not all(type(v) in (int,float) and math.isfinite(v) and v>0 for v in (ask,tp,stop)):
        raise ValueError('INVALID_PRICE')
    profit, risk = (tp/ask-1)*100, (1-stop/ask)*100
    if pmin is not None and not pmin-1e-8 <= profit <= (pmax+1e-8 if pmax is not None else float('inf')):
        raise ValueError('TARGET_OUTSIDE_MODULE')
    if smin is not None and not smin-1e-8 <= risk <= smax+1e-8:
        raise ValueError('STOP_OUTSIDE_MODULE')
    # Require an actual supplied closed candle as the structural anchor.
    tf, anchor = decision.get('anchor_timeframe'), decision.get('anchor_time_ms')
    if tf not in ('1m','5m','15m','1h','4h') or type(anchor) is not int:
        raise ValueError('MISSING_STRUCTURE_ANCHOR')
    bar = next((b for b in snapshot.get('series',{}).get(tf,[]) if b['time']==anchor and b.get('is_closed')), None)
    if not bar or bar.get('close_time',snapshot['atMs']) >= snapshot['atMs'] or not stop < bar['low'] < ask:
        raise ValueError('STOP_NOT_BELOW_CONFIRMED_STRUCTURE')
    evidence = target_evidence(snapshot, ask, tp, decision.get('target_tp2', tp), module)
    return {**evidence, 'module':module,'scenarioNameZh':name,'holdMinutes':hold,
        'holdSeconds':decision.get('hold_seconds',hold*60),
        'timeHorizon':f"{decision['hold_seconds']}秒" if module=='FLASH_REBOUND_FAST' else f'{hold}分钟','summaryZh':reason.strip(),
        'grossProfitPercent1':round(profit,4),'anchorTimeframe':tf,
        'anchorTimeMs':anchor,'structureLow':bar['low'],
        'trailingEnabled':module=='TREND_BREAKOUT_CONFIRM'}

def same_opportunity(old, new):
    if old.get('module') != new.get('module'):
        return False
    overlap = max(old['entryMin'],new['entryMin']) <= min(old['entryMax'],new['entryMax'])
    near_structure = abs(old.get('structureLow',0)-new.get('structureLow',0))/new['entryPrice'] <= .002
    return overlap and near_structure

def alert_card(sig):
    at = datetime.fromtimestamp(sig['atMs']/1000, timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M')
    return '\n'.join((f'【触发信号时间】{at} 北京时间',
        f"【买入机会】{sig['scenarioNameZh']} ${sig['entryMin']:.2f}~${sig['entryMax']:.2f}",
        f"【买入理由】{sig['summaryZh']}",
        f"【止盈点位】${sig['targetTP1']:.2f}（毛收益+{sig['grossProfitPercent1']:.2f}%，净收益+{sig['profitPercent1']:.2f}%）",
        f"【止损点位】${sig['stopLoss']:.2f}（-{sig['stopLossPercent']:.2f}%）",
        f"【建议持有时间】{sig['timeHorizon']}"))

def advance_plan(plan, snapshot, now_ms):
    """Observe a proposed trade, never infer an actual fill or a user position."""
    out = dict(plan)
    out.setdefault('trackingMode', 'PLAN_ONLY')
    out.setdefault('trackingState', 'WATCHING')
    out.setdefault('trailingStop', out['stopLoss'])
    if out['trackingState'] != 'WATCHING':
        return out
    if now_ms >= out['atMs'] + out.get('holdSeconds',out['holdMinutes']*60)*1000:
        out['trackingState'] = 'HORIZON_ENDED'
        return out
    if not snapshot.get('healthy'):
        out['trackingHealth'] = 'QUOTE_UNAVAILABLE'
        return out
    out['trackingHealth'] = 'HEALTHY'
    bid = snapshot['ticker']['bid_price']
    out['trackingAtMs'] = now_ms
    if bid <= out['trailingStop']:
        out['trackingState'] = 'STRUCTURE_BROKEN'
    elif bid >= out['targetTP2']:
        out['trackingState'] = 'TARGET_REACHED'
    elif out.get('trailingEnabled'):
        bars = snapshot.get('series',{}).get('5m',[])
        if len(bars) >= 3:
            left, pivot, right = bars[-3:]
            # Confirmed higher swing low; the proposed stop only moves up.
            if all(b.get('is_closed') for b in (left,pivot,right)) and pivot['time'] > out['atMs'] and pivot['low'] < min(left['low'],right['low']):
                candidate = pivot['low'] * .9995
                if out['trailingStop'] < candidate < bid:
                    out['trailingStop'] = candidate
    return out
