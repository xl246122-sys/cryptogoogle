"""Spot-only AI trade contracts. No dependency on baseline strategies."""
import math
from datetime import datetime, timezone, timedelta

MODULES = {
    'FLASH_DROP_REBOUND': ('暴跌反弹', 1., 6., 1., 2.5, 30, 240),
    'RANGE_SUPPORT_BOUNCE': ('区间震荡', 1., 4., .8, 1.5, 10, 240),
    'TREND_BREAKOUT_CONFIRM': ('上涨大趋势', None, None, None, None, 120, 720),
}

def rolling_windows(snapshot):
    result = {}
    for minutes in (10, 30, 60, 120, 240):
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

def trade_plan(decision, snapshot, ask):
    module = decision.get('scenario')
    if module not in MODULES:
        raise ValueError('UNKNOWN_MODULE')
    name, pmin, pmax, smin, smax, hmin, hmax = MODULES[module]
    hold = decision.get('hold_minutes')
    if type(hold) is not int or not hmin <= hold <= hmax:
        raise ValueError('HOLD_TIME_OUTSIDE_MODULE')
    reason = decision.get('summary_zh')
    if not isinstance(reason,str) or not 1 <= len(reason.strip()) <= 25:
        raise ValueError('REASON_MUST_BE_1_TO_25_CHARACTERS')
    tp, stop = decision['target_tp1'], decision['stop_loss']
    if not all(type(v) in (int,float) and math.isfinite(v) and v>0 for v in (ask,tp,stop)):
        raise ValueError('INVALID_PRICE')
    profit, risk = (tp/ask-1)*100, (1-stop/ask)*100
    if pmin is not None and not pmin-1e-8 <= profit <= pmax+1e-8:
        raise ValueError('TARGET_OUTSIDE_MODULE')
    if smin is not None and not smin-1e-8 <= risk <= smax+1e-8:
        raise ValueError('STOP_OUTSIDE_MODULE')
    # Require an actual supplied closed candle as the structural anchor.
    tf, anchor = decision.get('anchor_timeframe'), decision.get('anchor_time_ms')
    if tf not in ('1m','5m','15m','1h','4h') or type(anchor) is not int:
        raise ValueError('MISSING_STRUCTURE_ANCHOR')
    bar = next((b for b in snapshot.get('series',{}).get(tf,[]) if b['time']==anchor and b.get('is_closed')), None)
    if not bar or not stop < bar['low'] < ask:
        raise ValueError('STOP_NOT_BELOW_CONFIRMED_STRUCTURE')
    return {'module':module,'scenarioNameZh':name,'holdMinutes':hold,
        'timeHorizon':f'{hold}分钟','summaryZh':reason.strip(),
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
    if now_ms >= out['atMs'] + out['holdMinutes']*60000:
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
