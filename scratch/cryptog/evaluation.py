"""The only live/replay strategy entry point. Inputs and evaluation time are explicit."""
import copy
import math
from .clock import at_time
from .input_contract import INPUT_CONTRACT
from .cost_model import cost_snapshot
from .diagnostics import capture
from .config import ENGINE_VERSION, RULE_VERSION, TRADE_POLICIES, FRICTION_PCT, V2_ENGINE_VERSION, V2_FRICTION_PCT, V2_RULE_VERSION
from .features import TechnicalIndicators
from .market_state import diagnose_macro_trend, live_hourly_reading
from .strategy import scan_symbol
from .market import INTERVALS

def _stamp_live_hour(macro, bars, ticker):
    if not isinstance(macro, dict):
        return macro
    reading = live_hourly_reading(bars, ticker.get('price') if isinstance(ticker, dict) else None)
    if not reading:
        return macro
    shown = dict(macro)
    shown.update(reading)
    return shown


def evaluate(snapshot):
    s = copy.deepcopy(snapshot)
    now = s['atMs']
    result = {'atMs':now, 'engineVersion':ENGINE_VERSION, 'ruleVersion':RULE_VERSION,
              'indicatorVersion':'simple-window-rsi14-atr14-v112', 'status':'BLOCK_ENTRY',
              'signal':None, 'reasons':list(s.get('issues',[])), 'macro':None, 'volatility':None, 'research':[],
              'policies':copy.deepcopy(TRADE_POLICIES), 'assumedFrictionPct':FRICTION_PCT}
    if not s.get('healthy'):
        if not result['reasons']: result['reasons'] = ['MARKET_UNHEALTHY']
        return result
    try:
        if s.get('inputContract') is not None and s['inputContract'] != INPUT_CONTRACT:
            raise ValueError('INPUT_CONTRACT_MISMATCH')
        ticker, book = s['ticker'], s['book']
        if ticker.get('symbol') != 'BTCUSDT' or not book.get('is_valid'):
            raise ValueError('VENUE_OR_BOOK_INVALID')
        if not 0 <= now-ticker['timestamp'] <= 10000:
            raise ValueError('QUOTE_STALE')
        if not all(math.isfinite(ticker[k]) and ticker[k]>0 for k in ('price','ask_price','bid_price','high24h','low24h')):
            raise ValueError('QUOTE_INVALID')
        if ticker['ask_price'] <= ticker['bid_price'] or not math.isfinite(ticker['change24h']):
            raise ValueError('CROSSED_QUOTE')
        if not all(math.isfinite(book[k]) for k in ('spread','imbalance','bid_vol','ask_vol')) or book['spread'] < 0 or not -1 <= book['imbalance'] <= 1:
            raise ValueError('BOOK_INVALID')
        for interval,step in INTERVALS.items():
            bars = s['series'][interval]
            if len(bars)<(64 if interval=='15m' else 32) or not 0 <= now-bars[-1]['close_time']<=step+10000:
                raise ValueError('BARS_MISSING_OR_STALE:'+interval)
            if any(b['time']-a['time'] != step for a,b in zip(bars,bars[1:])):
                raise ValueError('BAR_GAP:'+interval)
            for c in bars:
                if c['close_time'] >= now or not c.get('is_closed'): raise ValueError('FUTURE_OR_FORMING_BAR')
                if not all(math.isfinite(c[k]) and c[k] > 0 for k in ('open','high','low','close')):
                    raise ValueError('INVALID_PRICE')
                if c['high'] < max(c['open'],c['close']) or c['low'] > min(c['open'],c['close']):
                    raise ValueError('INVALID_OHLC')
                if not 0 <= c['taker_buy_base'] <= c['volume'] or not math.isfinite(c['volume']):
                    raise ValueError('INVALID_VOLUME')
        with at_time(now), capture() as reasons:
            # V1.12 REST limits include the forming bar: freeze the corresponding
            # closed windows so a growing websocket cache cannot alter EMA/peaks.
            limits = INPUT_CONTRACT['windows']
            bars = {k:v[-limits[k]:] for k,v in s['series'].items()}
            ticker = s['ticker']
            if 'context' in s:
                from .engine_v2 import scan
                signal, reasons, view = scan(
                    bars['15m'], bars['5m'], bars['1m'], ticker['ask_price'], book,
                    s.get('context'), now, s.get('breaker'), s.get('derivatives'), s.get('costSnapshot'))
                result.update(engineVersion=V2_ENGINE_VERSION, ruleVersion=V2_RULE_VERSION,
                              assumedFrictionPct=cost_snapshot(now, s.get("costSnapshot"))["frictionPct"], costSnapshot=cost_snapshot(now, s.get("costSnapshot")), signal=signal,
                              status='BUY_CANDIDATE' if signal else 'WAIT_CONFIRMATION',
                              reasons=reasons, shortHorizonV2=view)
                try:
                    from .research import evaluate_research
                    macro = diagnose_macro_trend(bars['1h'], ticker)
                    result['macro'] = macro if macro['trend'] != 'INSUFFICIENT' else None
                    result['research'] = evaluate_research(bars, ticker, book, macro, now)
                except Exception as exc:
                    result['research'] = [{'mode':'SHADOW','status':'ERROR','version':'recovery-shadow-v1',
                                           'label':'研究评估异常','reasons':['RESEARCH_ERROR:'+type(exc).__name__]}]
                result['macro'] = _stamp_live_hour(result.get('macro'), bars['1h'], ticker)
                return result
            macro = diagnose_macro_trend(bars['1h'], ticker)
            result['macro'] = macro if macro['trend'] != 'INSUFFICIENT' else None
            if len(bars['15m']) >= 64:
                raw = TechnicalIndicators.calculate_volatility_regime(bars['15m'],ticker['price'])
                # Forecast-like legacy target fields must not reach the UI.
                result['volatility'] = {k:raw[k] for k in ('level','quantile','swing','p25','p75','sample_bars') if k in raw}
            signal = scan_symbol('BTCUSDT', ticker, macro, bars['1m'], s['book'], bars['1h'], bars['15m'], bars['5m'])
            result.update(signal=signal, status='BUY_CANDIDATE' if signal else 'WAIT_CONFIRMATION',
                          reasons=reasons or ([] if signal else ['NO_ELIGIBLE_SETUP']))
            # Separate output namespace: runtime/outbox only consume result['signal'].
            try:
                from .research import evaluate_research
                result['research'] = evaluate_research(bars,ticker,book,macro,now)
            except Exception as exc:
                result['research'] = [{'mode':'SHADOW','status':'ERROR','version':'recovery-shadow-v1',
                                       'label':'研究评估异常','reasons':['RESEARCH_ERROR:'+type(exc).__name__]}]
            result['macro'] = _stamp_live_hour(result.get('macro'), bars['1h'], ticker)
    except (ValueError, KeyError, TypeError, OverflowError) as exc:
        result.update(status='BLOCK_ENTRY', signal=None, macro=None, volatility=None, reasons=['INVALID_INPUT:'+str(exc)])
    return result
