import math
from typing import Dict, List, Optional, Tuple
from .clock import clock as time
from .config import *


def _advance_rule_track(track: dict, price: Optional[float], now_ms: int) -> Optional[str]:
    """Reference-only exit state machine. Never rewrites a user's actual position or sends orders."""
    if now_ms < track['alertedAtMs'] or now_ms <= track.get('lastSeenMs', 0):
        return None
    valid_price = price is not None and math.isfinite(price) and price > 0
    if now_ms - track.get('lastSeenMs', track['alertedAtMs']) > QUOTE_MAX_AGE_MS:
        track['observationGap'] = True
    def exit_part(fraction, exit_price, reason, at_ms):
        fraction = min(fraction, track['remainingFraction'])
        track['exitLegs'].append({'fraction': fraction, 'price': exit_price, 'reason': reason, 'atMs': at_ms})
        track['remainingFraction'] = max(0.0, track['remainingFraction'] - fraction)
    # Deadline is checked BEFORE extrema/targets. Late prices cannot turn a timeout into a win.
    if now_ms >= track['deadlineMs']:
        exact_quote = price if valid_price and now_ms == track['deadlineMs'] else None
        exit_part(track['remainingFraction'], exact_quote, 'TIME_EXIT', track['deadlineMs'])
        reason = 'TIME_EXIT' if exact_quote is not None else 'TIME_EXIT_PRICE_UNAVAILABLE'
    elif not valid_price:
        return None
    else:
        track['maxHigh'] = max(track['maxHigh'], price)
        track['minLow'] = min(track['minLow'], price)
        track['lastPrice'], track['lastSeenMs'] = price, now_ms
        if price <= track['sl']:
            track['firstSlMs'] = now_ms
            exit_part(track['remainingFraction'], price, 'STOP_EXIT', now_ms)
            reason = 'STOP_EXIT'
        elif price <= track['invalidationPrice']:
            exit_part(track['remainingFraction'], price, 'INVALIDATION_EXIT', now_ms)
            reason = 'INVALIDATION_EXIT'
        else:
            if price >= track['tp1'] and track.get('firstTp1Ms') is None:
                track['firstTp1Ms'] = now_ms
                exit_part(track['tp1Fraction'], track['tp1'], 'TP1_REFERENCE', now_ms)
            if track['remainingFraction'] > 1e-9 and price >= track['tp2']:
                track['firstTp2Ms'] = now_ms
                exit_part(track['remainingFraction'], track['tp2'], 'TP2_REFERENCE', now_ms)
            if track['remainingFraction'] > 1e-9:
                return None
            reason = 'TP2_EXIT' if track.get('firstTp2Ms') else 'TP1_EXIT'
    legs = track['exitLegs']
    track['referenceNetPct'] = (round(sum(leg['fraction'] * ((leg['price']/track['entry']-1)*100-FRICTION_PCT) for leg in legs), 4)
                               if all(leg['price'] is not None for leg in legs) else None)
    return reason

