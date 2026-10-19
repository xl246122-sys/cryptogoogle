#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Crypto-G - BTC spot monitor modular stage-one candidate
BTCUSDT BUY candidates only. No order execution.

V1.07 corrections from the read-only audit:
1. Volatility uses 15m bars (not 1m). Current window is excluded from the quantile.
2. A small 1m ATR can no longer force the LOW tier.
3. Reversal entries pass the anti-knife gate. One green candle does not cancel a waterfall.
4. Structural stop and target are rejected when invalid. They are not rewritten into a fixed percent.
5. 1h candles are required. Missing macro data blocks the signal.
6. FCM data uses the same field names as the Android client, and the 90s cooldown is persisted.
7. rule_score is a rule checklist, not a probability.

V1.11: three independent model policies, observed-resistance targets only,
structural invalidation, fractional reference exits and per-model deadlines.
V1.12: durable opportunity/action journals, manual fill cost accounting, execution latency and idempotent sync.
"""

import os
import hashlib
from decimal import Decimal
import sys
import time
import math
import json
import logging
import datetime
from typing import Dict, List, Optional, Tuple

# Setup logging
LOG_DIR = os.environ.get("CRYPTOG_LOG_DIR", "/opt/shotcrypto/logs")
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, "scanner.log")
ALERTED_SETUPS_FILE = os.path.join(LOG_DIR, "alerted_setups.json")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILE, encoding='utf-8')
    ]
)
logger = logging.getLogger("Crypto-G")

# API Configuration
BINANCE_API_BASES = [
    "https://data-api.binance.vision/api/v3",
    "https://api.binance.com/api/v3",
    "https://api1.binance.com/api/v3",
    "https://api2.binance.com/api/v3",
]

from cryptog.config import *
from cryptog.features import TechnicalIndicators, get_closed_candles
from cryptog.market_state import diagnose_macro_trend, diagnose_cascade_downtrend
from cryptog.cost_risk import entry_contract, entry_is_valid, model_targets, notification_ttl_ms
from cryptog.lifecycle import _advance_rule_track
from cryptog.strategy import validate_market_data_quality, verify_micro_range_reversal, _closed_breakout, observed_resistances, stable_range_box, recent_crash_confirmed, scan_symbol

SKIP_LOG_EVERY_SEC = 120.0
LAST_SKIP_LOG = 0.0
RECENT_ALERT_MEMORY: Dict[str, dict] = {}
ALERTED_SETUPS: Dict[str, int] = {}
LAST_ALERT_MS: Dict[str, int] = {}


def load_alerted_setups():
    global ALERTED_SETUPS, LAST_ALERT_MS, RECENT_ALERT_MEMORY
    if os.path.exists(ALERTED_SETUPS_FILE):
        try:
            with open(ALERTED_SETUPS_FILE, "r", encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, dict) and "setups" in raw:
                ALERTED_SETUPS = raw.get("setups") or {}
                LAST_ALERT_MS = raw.get("last_alert_ms") or {}
            elif isinstance(raw, dict):
                ALERTED_SETUPS = raw
                LAST_ALERT_MS = {}
            else:
                ALERTED_SETUPS = {}
                LAST_ALERT_MS = {}
            now = time.time()
            for sym, ts in LAST_ALERT_MS.items():
                age = now - (int(ts) / 1000.0)
                if 0 <= age < COOLDOWN_SECONDS:
                    RECENT_ALERT_MEMORY[sym] = {"time": now - age, "price": 0.0}
            logger.info("Loaded %d alerted setups from history file.", len(ALERTED_SETUPS))
        except Exception as e:
            logger.warning("Could not load alerted setups: %s", e)
            ALERTED_SETUPS = {}
            LAST_ALERT_MS = {}


def save_alerted_setup(setup_key: str, timestamp_ms: int, symbol: str):
    global ALERTED_SETUPS, LAST_ALERT_MS
    ALERTED_SETUPS[setup_key] = timestamp_ms
    LAST_ALERT_MS[symbol] = timestamp_ms
    if len(ALERTED_SETUPS) > 500:
        keys_to_remove = sorted(ALERTED_SETUPS.keys(), key=lambda k: ALERTED_SETUPS[k])[:-400]
        for k in keys_to_remove:
            ALERTED_SETUPS.pop(k, None)
    tmp_path = f"{ALERTED_SETUPS_FILE}.tmp"
    payload = {"setups": ALERTED_SETUPS, "last_alert_ms": LAST_ALERT_MS}
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        os.replace(tmp_path, ALERTED_SETUPS_FILE)
    except Exception as e:
        logger.error("Failed to persist alerted setups atomically: %s", e)


# Permanent model library. Append-only. Never trimmed.
# Alerts are written here even if the phone is off or the user never taps close.
LIBRARY_DIR = os.environ.get("CRYPTOG_LIBRARY_DIR", "/opt/shotcrypto/model_library")
RUNTIME = None
LIBRARY_PORT = int(os.environ.get('CRYPTOG_API_PORT', '8788'))
LIBRARY_HORIZON_MS = 12 * 60 * 60 * 1000
LIBRARY_LOCK = __import__("threading").Lock()
OPEN_TRACKS: Dict[str, dict] = {}
_LIBRARY_READY = False
_LAST_TRACK_SAVE_MS = 0


def set_library_dir(path: str):
    """Tests point this at a temp folder. Production keeps /opt/shotcrypto/model_library."""
    global LIBRARY_DIR, _LIBRARY_READY, OPEN_TRACKS
    LIBRARY_DIR = path
    _LIBRARY_READY = False
    OPEN_TRACKS = {}


def _library_ensure():
    global _LIBRARY_READY, OPEN_TRACKS
    if _LIBRARY_READY:
        return
    os.makedirs(LIBRARY_DIR, exist_ok=True)
    open_path = os.path.join(LIBRARY_DIR, "open_tracks.json")
    if os.path.exists(open_path):
        try:
            with open(open_path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, dict):
                OPEN_TRACKS = raw
            else:
                raise ValueError('track snapshot is not an object')
        except Exception as e:
            logger.warning("Could not read open tracks: %s", e)
            raise RuntimeError('Track snapshot is unreadable; refusing to replace history') from e
    _LIBRARY_READY = True
    try:
        _recover_library()
    except Exception:
        _LIBRARY_READY = False
        raise


def _iso_cst(ms: int) -> str:
    tz = datetime.timezone(datetime.timedelta(hours=8))
    return datetime.datetime.fromtimestamp(ms / 1000.0, tz).isoformat(timespec="seconds")


def _append_jsonl(name: str, row: dict):
    global _LIBRARY_READY
    _library_ensure()
    path = os.path.join(LIBRARY_DIR, name)
    line = json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(line)
            f.flush()
            os.fsync(f.fileno())
        _sync_library_directory()
    except Exception:
        _LIBRARY_READY = False  # Reconcile a possibly committed/partial append before a retry.
        raise


def _sync_library_directory():
    if hasattr(os, 'O_DIRECTORY'):
        fd = os.open(LIBRARY_DIR, os.O_RDONLY | os.O_DIRECTORY)
        try: os.fsync(fd)
        finally: os.close(fd)


def _save_open_tracks(force: bool = False):
    global _LAST_TRACK_SAVE_MS
    now_ms = int(time.time() * 1000)
    if not force and now_ms - _LAST_TRACK_SAVE_MS < 15000:
        return
    _library_ensure()
    path = os.path.join(LIBRARY_DIR, "open_tracks.json")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(OPEN_TRACKS, f, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    _sync_library_directory()
    _LAST_TRACK_SAVE_MS = now_ms


def _num(value, default=0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def record_model_alert(sig: dict) -> str:
    """Append one alert. The same alert id is not written twice."""
    alert_id = sig.get("structure_key") or f"{sig['symbol']}_{sig['strategy']}_{sig['confirmation_time']}"
    now_ms = int(sig.get("timestamp") or time.time() * 1000)
    with LIBRARY_LOCK:
        _library_ensure()
        if alert_id in OPEN_TRACKS:
            return alert_id
        row = {
            "recordType": "ALERT",
            "alertId": alert_id,
            "symbol": "BTCUSDT",
            "alertedAtMs": now_ms,
            "alertedAtCst": _iso_cst(now_ms),
            "engineVersion": V2_ENGINE_VERSION if sig.get("rule_version") == "short-horizon-v2" else ENGINE_VERSION,
            "strategy": sig.get("strategy"),
            "strategyNameZh": sig.get("strategy_name_zh"),
            "regime": sig.get("regime"),
            "hourlyRsi": sig.get("hourly_rsi"),
            "entryPrice": sig.get("entry_price"),
            "targetTP1": sig.get("target_tp1"),
            "targetTP2": sig.get("target_tp2"),
            "stopLoss": sig.get("stop_loss"),
            "profitPct1": sig.get("profit_pct1"),
            "profitPct2": sig.get("profit_pct2"),
            "stopLossPct": sig.get("stop_loss_pct"),
            "netTp1": sig.get("net_tp1"),
            "netTp2": sig.get("net_tp2"),
            "netRr": sig.get("net_rr"),
            "riskReward": sig.get("risk_reward"),
            "ruleScore": sig.get("rule_score"),
            "ruleScoreBreakdown": sig.get("rule_score_breakdown"),
            "ruleScoreIsNotWinRate": True,
            "timeHorizon": sig.get("time_horizon"),
            "confirmationTime": sig.get("confirmation_time"),
            "volatilityLevel": sig.get("volatility_level"),
            "quantilePct": sig.get("quantile_pct"),
            "structureSupport": sig.get("structure_support"),
            "reasonZh": sig.get("reason_zh"),
            "winRateStatus": "历史胜率：未验证",
            "tradeRules": {key: sig.get(key) for key in ("model", "rule_version", "max_hold_minutes", "min_net_tp1", "min_net_rr", "friction_pct", "cost_snapshot", "max_net_target", "invalidation_price", "tp1_fraction", "target_basis", "exit_rule", "tier", "tier_label")},
        }
        OPEN_TRACKS[alert_id] = {
            "alertId": alert_id,
            "entry": _num(sig.get("entry_price")),
            "tp1": _num(sig.get("target_tp1")),
            "tp2": _num(sig.get("target_tp2")),
            "sl": _num(sig.get("stop_loss")),
            "alertedAtMs": now_ms,
            "maxHigh": _num(sig.get("entry_price")),
            "minLow": _num(sig.get("entry_price")),
            "firstTp1Ms": None,
            "firstTp2Ms": None,
            "firstSlMs": None,
            "lastPrice": _num(sig.get("entry_price")),
            "lastSeenMs": now_ms,
            "simBuyAtMs": None,
            "userClosedAtMs": None,
            "backfillExitPrice": None,
            "stillHoldingAtMs": None,
            "outcomeWritten": False,
            "signalSnapshot": dict(sig),
        }
        if sig.get("model") in TRADE_POLICIES:
            OPEN_TRACKS[alert_id].update({
                "model": sig["model"], "ruleVersion": sig["rule_version"],
                "deadlineMs": now_ms + int(sig["max_hold_minutes"] * 60000),
                "maxHoldMinutes": sig["max_hold_minutes"],
                "invalidationPrice": sig["invalidation_price"],
                "tp1Fraction": sig["tp1_fraction"], "remainingFraction": 1.0,
                "exitLegs": [], "observationGap": False,
            })
        row['initialTrack'] = OPEN_TRACKS[alert_id].copy()
        try:
            _append_jsonl("alerts.jsonl", row)
        except Exception:
            OPEN_TRACKS.pop(alert_id, None)
            raise
        _save_open_tracks(force=True)
        logger.info("Model library recorded alert %s", alert_id)
        return alert_id


def _settle_track(alert_id: str, track: dict, now_ms: int, reason: str):
    entry = track["entry"] or 0.0
    mfe = ((track["maxHigh"] - entry) / entry * 100.0) if entry else 0.0
    mae = ((track["minLow"] - entry) / entry * 100.0) if entry else 0.0
    if track.get("userClosedAtMs") or track.get("backfillExitPrice"):
        user_exit = "REPORTED"
    elif track.get("simBuyAtMs"):
        user_exit = "SIM_OPEN_UNREPORTED"
    else:
        user_exit = "ALERT_ONLY"
    firsts = [ms for ms in (track.get("firstTp1Ms"), track.get("firstTp2Ms"), track.get("firstSlMs")) if ms]
    row = {
        "recordType": "MARKET_OUTCOME",
        "alertId": alert_id,
        "symbol": "BTCUSDT",
        "settledAtMs": now_ms,
        "settledAtCst": _iso_cst(now_ms),
        "alertedAtMs": track["alertedAtMs"],
        "entryPrice": entry,
        "targetTP1": track["tp1"],
        "targetTP2": track["tp2"],
        "stopLoss": track["sl"],
        "maxHigh": round(track["maxHigh"], 2),
        "minLow": round(track["minLow"], 2),
        "mfePct": round(mfe, 4),
        "maePct": round(mae, 4),
        "firstTp1Ms": track.get("firstTp1Ms"),
        "firstTp2Ms": track.get("firstTp2Ms"),
        "firstSlMs": track.get("firstSlMs"),
        "tp1Touched": track.get("firstTp1Ms") is not None,
        "tp2Touched": track.get("firstTp2Ms") is not None,
        "slTouched": track.get("firstSlMs") is not None,
        "pathStatus": reason,
        "userExitStatus": user_exit,
        "userExitStatusScope": "LEGACY_SIMULATION_EVENTS_ONLY",
        "userExitNote": "此字段仅描述旧版模拟/补记事件；实际成交请按 MANUAL_FILL 及更正链计算。参考路径不是成交。",
        "observedMinutes": round((min(now_ms, track.get("deadlineMs", track["alertedAtMs"] + LIBRARY_HORIZON_MS)) - track["alertedAtMs"]) / 60000.0, 1),
        "ruleScoreIsNotWinRate": True,
        "model": track.get("model"),
        "ruleVersion": track.get("ruleVersion"),
        "deadlineMs": track.get("deadlineMs"),
        "maxHoldMinutes": track.get("maxHoldMinutes"),
        "exitLegs": track.get("exitLegs", []),
        "observationGap": track.get("observationGap", False),
        "referenceOnly": True,
        "referenceNetPct": track.get("referenceNetPct"),
        "performanceEligible": False,  # Sampled reference path is not a backtest or actual fill.
    }
    if alert_id not in OUTCOME_IDS:
        _append_jsonl("outcomes.jsonl", row)
        OUTCOME_IDS.add(alert_id)
    track["outcomeWritten"] = True
    track["pathStatus"] = reason
    logger.info("Model library settled %s as %s (%s)", alert_id, reason, user_exit)




def observe_model_price(price: float, now_ms: Optional[int] = None):
    """New alerts follow their rule deadline; old alerts keep a legacy 12h observation label."""
    now_ms = now_ms or int(time.time() * 1000)
    with LIBRARY_LOCK:
        _library_ensure()
        if not OPEN_TRACKS:
            return
        changed = False
        force_save = False
        for alert_id, track in OPEN_TRACKS.items():
            if track.get("outcomeWritten"):
                continue
            if track.get('ruleVersion') == RULE_VERSION:
                before_legs = len(track.get('exitLegs', []))
                reason = _advance_rule_track(track, price, now_ms)
                force_save = force_save or len(track.get('exitLegs', [])) != before_legs
                if reason:
                    _settle_track(alert_id, track, now_ms, reason)
                    force_save = True
                changed = True
                continue
            # Legacy tracks: reject out-of-window data before updating extremes.
            if now_ms >= track['alertedAtMs'] + LIBRARY_HORIZON_MS:
                sl_ms, tp1_ms = track.get('firstSlMs'), track.get('firstTp1Ms')
                if sl_ms and tp1_ms:
                    reason = 'HORIZON_12H_SL_BEFORE_TP1' if sl_ms < tp1_ms else 'HORIZON_12H_TP1_BEFORE_SL'
                elif sl_ms: reason = 'HORIZON_12H_SL_TOUCHED'
                elif track.get('firstTp2Ms'): reason = 'HORIZON_12H_TP2_TOUCHED'
                elif tp1_ms: reason = 'HORIZON_12H_TP1_TOUCHED'
                else: reason = 'HORIZON_12H_NO_TARGET'
                _settle_track(alert_id, track, now_ms, reason)
                changed = force_save = True
                continue
            if not price or not math.isfinite(price) or price <= 0:
                continue
            changed = True
            track["maxHigh"] = max(track.get("maxHigh") or price, price)
            track["minLow"] = min(track.get("minLow") or price, price)
            track["lastPrice"] = price
            track["lastSeenMs"] = now_ms
            if track.get("tp1") and price >= track["tp1"] and not track.get("firstTp1Ms"):
                track["firstTp1Ms"] = now_ms
                force_save = True
            if track.get("tp2") and price >= track["tp2"] and not track.get("firstTp2Ms"):
                track["firstTp2Ms"] = now_ms
                force_save = True
            if track.get("sl") and price <= track["sl"] and not track.get("firstSlMs"):
                track["firstSlMs"] = now_ms
                force_save = True
        if changed:
            _save_open_tracks(force=force_save)


def _read_journal(name):
    path = os.path.join(LIBRARY_DIR, name)
    if not os.path.exists(path):
        return []
    rows = []
    with open(path, 'rb+') as f:
        while True:
            offset = f.tell()
            line = f.readline()
            if not line:
                break
            try:
                row = json.loads(line)
                if not isinstance(row, dict): raise ValueError('journal row is not an object')
            except (ValueError, UnicodeDecodeError):
                if line.endswith(b'\n') or f.read(1):
                    raise ValueError('Journal corruption requires review: ' + name)
                # Preserve crash-truncated bytes before removing the uncommitted tail.
                with open(path + '.partial.' + str(time.time_ns()), 'wb') as backup:
                    backup.write(line); backup.flush(); os.fsync(backup.fileno())
                f.seek(offset); f.truncate(); f.flush(); os.fsync(f.fileno())
                break
            rows.append(row)
            if not line.endswith(b'\n'):
                f.write(b'\n'); f.flush(); os.fsync(f.fileno())
    return rows


ACTION_EVENTS = {}
OUTCOME_IDS = set()


def _project_action(row):
    track = OPEN_TRACKS.get(row['alertId'])
    if track is None: return
    kind, at = row['recordType'], row['actedAtMs']
    field = {'SIM_BUY': 'simBuyAtMs', 'USER_CLOSE': 'userClosedAtMs',
             'BACKFILL_CLOSE': 'userClosedAtMs', 'STILL_HOLDING': 'stillHoldingAtMs',
             'PHONE_RECEIVED': 'phoneReceivedAtMs', 'PHONE_OPENED': 'phoneOpenedAtMs'}.get(kind)
    if field:
        previous = track.get(field)
        track[field] = min(previous, at) if previous and kind.startswith('PHONE_') else at
    if kind == 'BACKFILL_CLOSE': track['backfillExitPrice'] = row.get('exitPrice')


def _recover_library():
    global ACTION_EVENTS, OUTCOME_IDS
    ACTION_EVENTS = {}
    OUTCOME_IDS = set()
    _read_journal('delivery_events.jsonl')
    for row in _read_journal('alerts.jsonl'):
        if row.get('initialTrack') and row['alertId'] not in OPEN_TRACKS:
            OPEN_TRACKS[row['alertId']] = row['initialTrack']
    for row in _read_journal('user_actions.jsonl'):
        if row.get('eventId'): ACTION_EVENTS[row['eventId']] = row
        _project_action(row)
    for row in _read_journal('outcomes.jsonl'):
        OUTCOME_IDS.add(row['alertId'])
        track = OPEN_TRACKS.get(row['alertId'])
        if track:
            track.update(outcomeWritten=True, pathStatus=row['pathStatus'])
            if row.get('model'): track['remainingFraction'] = 0.0
            for key in ('maxHigh', 'minLow', 'firstTp1Ms', 'firstTp2Ms', 'firstSlMs', 'exitLegs', 'referenceNetPct', 'observationGap'):
                if key in row: track[key] = row[key]


def _finite(value, positive=False, nullable=False):
    if value is None and nullable: return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError('number must be finite')
    if (positive and value <= 0) or (not positive and value < 0): raise ValueError('number out of range')
    return value


def validate_execution_fill(fill, now_ms):
    if not isinstance(fill, dict) or fill.get('source') != 'MANUAL' or fill.get('side') not in ('BUY', 'SELL'):
        raise ValueError('invalid fill source or side')
    if not all(key in fill for key in ('commission', 'commissionAssetUsdtRate', 'referencePrice', 'referenceAtMs')):
        raise ValueError('missing cost or benchmark fields: use null for unknown')
    for key in ('fillId', 'positionId'):
        value = fill.get(key)
        if not isinstance(value, str) or not 1 <= len(value) <= 160 or not all(c.isascii() and (c.isalnum() or c in '_-.') for c in value):
            raise ValueError('invalid fill identity')
    for key in ('price', 'quantity', 'executedAtMs'): _finite(fill.get(key), positive=True)
    if not 0 < fill['price'] * fill['quantity'] <= 1e15: raise ValueError('fill value out of range')
    if fill['executedAtMs'] > now_ms + 5000: raise ValueError('future fill')
    if not isinstance(fill.get('timeApproximate'), bool): raise ValueError('time accuracy required')
    trade_id = fill.get('exchangeTradeId')
    if trade_id and (not isinstance(trade_id, str) or not trade_id.isascii() or not trade_id.isdigit() or len(trade_id)>40):
        raise ValueError('invalid exchange trade ID')
    commission = _finite(fill.get('commission'), nullable=True)
    asset = fill.get('commissionAsset')
    if not isinstance(asset, str) or not 1 <= len(asset) <= 12 or not asset.isascii() or not asset.isalnum() or asset != asset.upper():
        raise ValueError('invalid commission asset')
    if asset == 'BTC' and commission is not None and commission >= fill['quantity']: raise ValueError('excessive BTC fee')
    _finite(fill.get('commissionAssetUsdtRate'), positive=True, nullable=True)
    fee_rate = fill['price'] if asset=='BTC' else 1 if asset=='USDT' else fill.get('commissionAssetUsdtRate')
    if commission is not None and fee_rate is not None and not commission*fee_rate <= 1e15: raise ValueError('commission value out of range')
    ref = _finite(fill.get('referencePrice'), positive=True, nullable=True)
    ref_at = _finite(fill.get('referenceAtMs'), positive=True, nullable=True)
    if (ref is None) != (ref_at is None) or (ref_at is not None and ref_at > fill['executedAtMs']):
        raise ValueError('invalid quote benchmark')


def execution_summary(fills):
    from cryptog.execution_accounting import execution_summary as summarize
    for fill in fills:
        validate_execution_fill(fill, int(time.time()*1000))
    return summarize(fills)


def _p2_on_fill(row: dict) -> None:
    from cryptog.ledger import Ledger
    from cryptog.execution_sync import mirror
    ledger=None
    try:
        ledger=Ledger(os.path.join(LIBRARY_DIR,'research.sqlite3'))
        series={}
        if RUNTIME is not None and hasattr(RUNTIME,'cache'):
            series=RUNTIME.cache.snapshot(int(time.time()*1000)).get('series') or {}
        if not mirror(ledger,row,series.get('1m'),series.get('15m')):logger.error('Research action pending retry')
    except Exception as exc:logger.error('Research action mirror: %s',type(exc).__name__)
    finally:
        if ledger:ledger.close()


def apply_user_action(payload: dict, authenticated_owner=None) -> dict:
    event_id = payload.get('eventId')
    try:
        allowed = {'SIM_BUY', 'USER_CLOSE', 'BACKFILL_CLOSE', 'STILL_HOLDING', 'PHONE_RECEIVED', 'PHONE_OPENED', 'ENTRY_REJECTED', 'MANUAL_FILL'}
        kind, alert_id = payload.get('recordType'), payload.get('alertId')
        if kind not in allowed or not isinstance(alert_id, str) or not 1 <= len(alert_id) <= 160 or not all(c.isascii() and (c.isalnum() or c in '_-.') for c in alert_id):
            raise ValueError('invalid action')
        now_ms = int(time.time()*1000)
        at = _finite(payload.get('actedAtMs'), positive=True)
        if at > now_ms+5000: raise ValueError('future action')
        canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, allow_nan=False)
        if not event_id: event_id = 'legacy-' + hashlib.sha256(canonical.encode()).hexdigest()
        if not isinstance(event_id, str) or not 1 <= len(event_id) <= 160 or not all(c.isascii() and (c.isalnum() or c in '_-.') for c in event_id):
            raise ValueError('invalid eventId')
        payload_hash = hashlib.sha256(canonical.encode()).hexdigest()
        row = {'eventId': event_id, 'payloadHash': payload_hash, 'recordType': kind, 'alertId': alert_id,
               'symbol': 'BTCUSDT', 'actedAtMs': int(at), 'actedAtCst': _iso_cst(at), 'receivedAtMs': now_ms,
               'note': str(payload.get('note') or '')[:300], 'approximate': bool(payload.get('approximate')),
               'exitSource': str(payload.get('exitSource') or '')[:40], 'strategy': str(payload.get('strategy') or '')[:40],
               'recordSource': 'MANUAL_UNVERIFIED' if kind=='MANUAL_FILL' else 'SIMULATED' if kind in ('SIM_BUY','USER_CLOSE') else 'CLIENT_REPORTED'}
        if authenticated_owner is not None:
            if not isinstance(authenticated_owner,str) or len(authenticated_owner)!=64 or any(c not in '0123456789abcdef' for c in authenticated_owner):
                raise ValueError('invalid authenticated owner')
            row['authenticatedOwner']=authenticated_owner
        if payload.get('costSnapshot') is not None:
            from cryptog.cost_model import cost_snapshot
            row['costSnapshot'] = cost_snapshot(int(at), payload['costSnapshot'])
        for key in ('entryPrice', 'exitPrice', 'positionSize', 'signalAtMs', 'signalPrice', 'quoteAtMs'):
            row[key] = _finite(payload.get(key), positive=True, nullable=True)
        with LIBRARY_LOCK:
            _library_ensure()
            old = ACTION_EVENTS.get(event_id)
            if old:
                if old.get('authenticatedOwner') and old['authenticatedOwner']!=authenticated_owner: raise ValueError('action owner mismatch')
                if old.get('payloadHash') != payload_hash: raise ValueError('eventId reused with different data')
                return {'ok': True, 'eventId': event_id, 'alertId': alert_id, 'duplicate': True}
            track = OPEN_TRACKS.get(alert_id, {})
            if kind == 'SIM_BUY':
                if not row['entryPrice'] or not row['positionSize']: raise ValueError('simulation entry and size required')
                signal_at = track.get('alertedAtMs') or row.get('signalAtMs')
                row['entryLatency'] = {name: at-start if start and at>=start else None for name, start in
                    [('signalToEntryMs',signal_at),('receivedToEntryMs',track.get('phoneReceivedAtMs')),('openedToEntryMs',track.get('phoneOpenedAtMs'))]}
                reference = track.get('entry') or row.get('signalPrice')
                row['signalToEntryPriceChangePct'] = (row['entryPrice']/reference-1)*100 if reference else None
            if kind == 'USER_CLOSE':
                if not all(row[k] for k in ('entryPrice','exitPrice','positionSize')): raise ValueError('simulation close prices and size required')
                quantity = row['positionSize']/row['entryPrice']
                gross = quantity*(row['exitPrice']-row['entryPrice'])
                cost = (row['positionSize']+quantity*row['exitPrice'])*0.00055
                if row.get('strategy')=='QUICK_PAPER_V2':
                    from cryptog.execution_accounting import paper_close_cost
                    cost=paper_close_cost(row,list(ACTION_EVENTS.values()))
                row['simulatedAccounting'] = {'grossUsdt': gross, 'assumedCostUsdt': cost, 'netUsdt': gross-cost,
                                              'costAssumption': 'frozen entry cost-v2.1 on initial notional' if row.get('strategy')=='QUICK_PAPER_V2' else '0.055% each leg, not actual fees', 'performanceEligible': False}
            if kind == 'MANUAL_FILL':
                fill = payload.get('fill'); validate_execution_fill(fill, now_ms)
                if any(r.get('fill', {}).get('fillId') == fill['fillId'] for r in ACTION_EVENTS.values()): raise ValueError('fillId already recorded')
                replaces = payload.get('replacesEventId')
                replaced = {r.get('replacesEventId') for r in ACTION_EVENTS.values() if r.get('replacesEventId')}
                if replaces:
                    original = ACTION_EVENTS.get(replaces)
                    if not original or not original.get('fill') or replaces in replaced or original['alertId'] != alert_id or original['fill']['positionId'] != fill['positionId']:
                        raise ValueError('invalid or already superseded fill correction')
                    row['replacesEventId'] = replaces
                    row['replacesFillId'] = original['fill']['fillId']
                    replaced.add(replaces)
                if fill.get('exchangeTradeId') and any(r['eventId'] not in replaced and r.get('fill', {}).get('exchangeTradeId') == fill['exchangeTradeId'] for r in ACTION_EVENTS.values()):
                    raise ValueError('exchange trade ID already recorded; use a correction')
                previous = [r for r in ACTION_EVENTS.values() if r.get('fill', {}).get('positionId') == fill['positionId'] and r['eventId'] not in replaced]
                if any(r['alertId'] != alert_id for r in previous): raise ValueError('position belongs to another opportunity')
                row['fill'] = fill
                row['performanceEligible'] = False  # User reported, not exchange verified or a strategy backtest.
                row['executionSummary'] = execution_summary([r['fill'] for r in previous] + [fill])
                track = OPEN_TRACKS.get(alert_id, {})
                signal_at = track.get('alertedAtMs') or row.get('signalAtMs')
                received = track.get('phoneReceivedAtMs')
                opened = track.get('phoneOpenedAtMs')
                end = fill['executedAtMs'] if fill['side'] == 'BUY' and not fill['timeApproximate'] else None
                row['entryLatency'] = {name: end-start if end and start and end>=start else None for name, start in [('signalToEntryMs',signal_at),('receivedToEntryMs',received),('openedToEntryMs',opened)]}
            _append_jsonl('user_actions.jsonl', row) # fsync before ACK; replay after a lost ACK/restart.
            ACTION_EVENTS[event_id] = row
            _project_action(row)
            _save_open_tracks(force=True)
            _p2_on_fill(row)
        return {'ok': True, 'eventId': event_id, 'alertId': alert_id}
    except (ValueError, TypeError, OverflowError) as exc:
        return {'ok': False, 'eventId': event_id, 'error': str(exc)}



def record_delivery(alert_id, status):
    with LIBRARY_LOCK:
        if RUNTIME and getattr(RUNTIME,'ledger',None):
            try:
                from cryptog.funnel import stage
                stage(RUNTIME.ledger,alert_id,int(time.time()*1000),'DELIVERY',status)
            except Exception:
                logger.exception('Delivery research mirror failed')
        _append_jsonl('delivery_events.jsonl', {'alertId': alert_id, 'status': status, 'atMs': int(time.time()*1000),
                                             'note': 'FCM acceptance is not handset delivery or human attention'})


def execution_reports(alert_id):
    """Current projection, including late arrivals and append-only corrections."""
    rows = [r for r in ACTION_EVENTS.values() if r['alertId'] == alert_id]
    replaced = {r.get('replacesEventId') for r in rows if r.get('replacesEventId')}
    fills = [r['fill'] for r in rows if r.get('fill') and r['eventId'] not in replaced]
    track = OPEN_TRACKS.get(alert_id, {})
    signal_at = track.get('alertedAtMs') or next((r['signalAtMs'] for r in rows if r.get('signalAtMs')), None)
    first = lambda kind: min((r['actedAtMs'] for r in rows if r['recordType']==kind), default=None)
    reports = []
    for position in sorted({f['positionId'] for f in fills}):
        selected = [f for f in fills if f['positionId']==position]
        buys = sorted((f for f in selected if f['side']=='BUY'), key=lambda f: f['executedAtMs'])
        entry_at = buys[0]['executedAtMs'] if buys and not buys[0]['timeApproximate'] else None
        latency = {name: entry_at-start if entry_at and start and entry_at>=start else None for name,start in
                   [('signalToEntryMs',signal_at),('receivedToEntryMs',first('PHONE_RECEIVED')),('openedToEntryMs',first('PHONE_OPENED'))]}
        original_price = track.get('entry') or next((r['signalPrice'] for r in rows if r.get('signalPrice')), None)
        contract = track.get('signalSnapshot', {})
        reports.append({'positionId': position, 'summary': execution_summary(selected), 'entryLatency': latency,
                        'signalToEntryPriceChangePct': (buys[0]['price']/original_price-1)*100 if buys and original_price else None,
                        'entryWithinSignalTime': signal_at <= entry_at < contract['expires_at'] if entry_at and signal_at and contract.get('expires_at') else None,
                        'entryWithinSignalRange': contract['entry_min'] <= buys[0]['price'] <= contract['entry_max'] if buys and contract.get('entry_min') and contract.get('entry_max') else None})
    return reports


def read_track_status(alert_id: str) -> Optional[dict]:
    with LIBRARY_LOCK:
        _library_ensure()
        track = OPEN_TRACKS.get(alert_id)
        if not track:
            return None
        return {
            "alertId": alert_id,
            "outcomeWritten": bool(track.get("outcomeWritten")),
            "pathStatus": track.get("pathStatus"),
            "tp1Touched": track.get("firstTp1Ms") is not None,
            "tp2Touched": track.get("firstTp2Ms") is not None,
            "slTouched": track.get("firstSlMs") is not None,
            "firstTp1Ms": track.get("firstTp1Ms"),
            "firstSlMs": track.get("firstSlMs"),
            "maxHigh": track.get("maxHigh"),
            "minLow": track.get("minLow"),
            "lastPrice": track.get("lastPrice"),
            "simBuy": track.get("simBuyAtMs") is not None,
            "userClosed": track.get("userClosedAtMs") is not None,
            "model": track.get("model"),
            "deadlineMs": track.get("deadlineMs"),
            "maxHoldMinutes": track.get("maxHoldMinutes"),
            "remainingFraction": track.get("remainingFraction"),
            "referenceNetPct": track.get("referenceNetPct"),
            "observationGap": track.get("observationGap"),
            "exitLegs": track.get("exitLegs", []),
        }


def start_model_library_server():
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from cryptog.security import DeviceAuth, tls_context
    import urllib.parse
    auth = DeviceAuth(os.environ['CRYPTOG_DEVICE_AUTH_FILE'])
    tls = tls_context()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            logger.info("model-library " + fmt, *args)

        def _cors(self):
            origin = self.headers.get('Origin','')
            allowed = os.environ.get('CRYPTOG_ALLOWED_ORIGINS','https://localhost,capacitor://localhost').split(',')
            if origin in allowed:
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header('Vary', 'Origin')
            self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Library-Token")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

        def _json(self, code: int, obj: dict):
            raw = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self._cors()
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def _authorized(self) -> bool:
            self.connection.settimeout(10)
            return auth.allow(self.headers.get("X-Library-Token", ""), self.client_address[0], self.command == 'POST')

        def do_OPTIONS(self):
            self.send_response(204)
            self._cors()
            self.end_headers()

        def do_GET(self):
            if not self._authorized():
                return self._json(401, {"ok": False})
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path == '/model-library/ai-state':
                if not RUNTIME or not hasattr(RUNTIME, 'ai'):
                    return self._json(503, {'ok': False, 'error': 'AI_ENGINE_UNAVAILABLE'})
                return self._json(200, RUNTIME.ai.status())
            if parsed.path == '/model-library/strategy-settings':
                return self._json(200,{'ok':True,**RUNTIME.settings.get()})
            if parsed.path == '/model-library/market-state':
                radar_only = (urllib.parse.parse_qs(parsed.query).get('view') or [''])[0] == 'radar'
                return self._json(200, RUNTIME.status(radar_only=True) if RUNTIME and radar_only else RUNTIME.status() if RUNTIME else {'ok':False,'schema':1,'snapshot':None})
            if parsed.path == '/model-library/capabilities':
                return self._json(200, {'ok': True, 'engineVersion': ENGINE_VERSION, 'userActionProtocol': 2})
            if parsed.path == '/model-library/opportunities':
                with LIBRARY_LOCK:
                    _library_ensure()
                    selected = sorted(OPEN_TRACKS.values(), key=lambda t: t['alertedAtMs'], reverse=True)[:100]
                    latest = {}
                    for row in _read_journal('delivery_events.jsonl'): latest[row['alertId']] = row['status']
                    opportunities = [{'alertId': t['alertId'], 'atMs': t['alertedAtMs'], 'model': t.get('model'),
                                      'delivery': latest.get(t['alertId'], 'UNKNOWN_LEGACY_OR_UNATTEMPTED'), 'pathStatus': t.get('pathStatus', 'OPEN')}
                                     for t in selected]
                return self._json(200, {'ok': True, 'opportunities': opportunities})
            if parsed.path == '/model-library/records':
                alert_id = (urllib.parse.parse_qs(parsed.query).get('alertId') or [''])[0]
                if not alert_id or len(alert_id) > 160:
                    return self._json(400, {'ok': False})
                with LIBRARY_LOCK:
                    _library_ensure()
                    records = {name: [r for r in _read_journal(name+'.jsonl') if r.get('alertId') == alert_id]
                               for name in ('alerts', 'delivery_events', 'user_actions', 'outcomes')}
                    reports = execution_reports(alert_id)
                return self._json(200, {'ok': True, 'alertId': alert_id, 'records': records, 'executionReports': reports})
            if parsed.path != "/model-library/status":
                return self._json(404, {"ok": False})
            alert_id = (urllib.parse.parse_qs(parsed.query).get("alertId") or [""])[0]
            return self._json(200, {"ok": True, "track": read_track_status(alert_id)})

        def do_POST(self):
            if not self._authorized():
                return self._json(401, {"ok": False})
            route = urllib.parse.urlparse(self.path).path
            if route not in ("/model-library/strategy-settings", "/model-library/action", "/model-library/position-review", "/model-library/exit-device", "/model-library/exit-receipt", "/model-library/exit-device-status", "/model-library/ai-config", "/model-library/ai-trigger", "/model-library/ai-verify", "/model-library/account-context"):
                return self._json(404, {"ok": False})
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                return self._json(400, {"ok": False, "error": "body size"})
            if length <= 0 or length > 32768:
                return self._json(400, {"ok": False, "error": "body size"})
            try:
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
            except Exception:
                return self._json(400, {"ok": False, "error": "json"})
            if not isinstance(payload, dict):
                return self._json(400, {"ok": False})
            if route == '/model-library/account-context':
                if not RUNTIME:return self._json(503,{'ok':False})
                try:return self._json(200,{'ok':True,'account':RUNTIME.account_context.put(payload,int(time.time()*1000))})
                except ValueError as exc:return self._json(400,{'ok':False,'error':str(exc)})
            if route == '/model-library/strategy-settings':
                try:return self._json(200,{'ok':True,**RUNTIME.settings.put(payload)})
                except ValueError as exc:return self._json(409,{'ok':False,'error':str(exc)})
            if route in ('/model-library/exit-device','/model-library/exit-receipt','/model-library/exit-device-status'):
                if not RUNTIME or not hasattr(RUNTIME,'exit_delivery'):
                    return self._json(503,{'ok':False,'error':'EXIT_RUNTIME_UNAVAILABLE'})
                device=__import__('hashlib').sha256(self.headers.get('X-Library-Token','').encode()).hexdigest()
                now=int(time.time()*1000)
                try:
                    if route.endswith('exit-device-status'):
                        status=RUNTIME.exit_delivery.device_status(device,payload.get('token'))
                        return self._json(200,{'ok':True,**status,'pushEnabled':RUNTIME.exit_enabled})
                    if route.endswith('exit-device'):
                        if 'token' not in payload:raise ValueError('Missing token')
                        RUNTIME.exit_delivery.register(device,payload['token'],now)
                        return self._json(200,{'ok':True,'registered':payload['token'] is not None,'pushEnabled':RUNTIME.exit_enabled})
                    identity=payload.get('deliveryId')
                    if not isinstance(identity,str) or len(identity)>100:raise ValueError('Invalid delivery')
                    result=RUNTIME.exit_delivery.receipt(device,identity,payload.get('kind'),payload.get('clientAtMs'),now)
                    return self._json(200,result)
                except ValueError:
                    return self._json(400,{'ok':False,'error':'INVALID_EXIT_REQUEST'})
            if route == '/model-library/position-review':
                notice_id = payload.get('noticeId')
                if not isinstance(notice_id,str) or len(notice_id)>100 or not RUNTIME:
                    return self._json(400, {'ok':False,'error':'INVALID_NOTICE'})
                device = __import__('hashlib').sha256(self.headers.get('X-Library-Token','').encode()).hexdigest()
                result = RUNTIME.store.review_position_notice(notice_id,device,int(time.time()*1000))
                return self._json(200 if result['ok'] else 409,result)
            if route == '/model-library/ai-config':
                if not RUNTIME or not hasattr(RUNTIME, 'ai'):
                    return self._json(503, {'ok': False, 'error': 'AI_ENGINE_UNAVAILABLE'})
                try:
                    return self._json(200, {'ok': True, 'config': RUNTIME.ai.set_config(payload)})
                except ValueError as exc:
                    return self._json(400, {'ok': False, 'error': str(exc)})
            if route == '/model-library/ai-verify':
                if not RUNTIME or not hasattr(RUNTIME,'ai'):
                    return self._json(503,{'ok':False,'error':'AI_ENGINE_UNAVAILABLE'})
                res=RUNTIME.ai.verify_connection()
                return self._json(200 if res['ok'] else 400,res)
            if route == '/model-library/ai-trigger':
                if not RUNTIME or not hasattr(RUNTIME, 'ai'):
                    return self._json(503, {'ok': False, 'error': 'AI_ENGINE_UNAVAILABLE'})
                res = RUNTIME.ai.execute_analysis(trigger_reason='MANUAL_TRIGGER')
                return self._json(200 if res.get('ok') else 400, res)
            result = apply_user_action(payload,hashlib.sha256(self.headers.get('X-Library-Token','').encode()).hexdigest())
            return self._json(200 if result.get("ok") else 400, result)

    try:
        _library_ensure()
        class TLSHTTPServer(ThreadingHTTPServer):
            def get_request(self):
                # Handshake in the request thread, not the shared accept loop.
                # One client that connects without sending TLS must not block all devices.
                sock, address = self.socket.accept()
                sock.settimeout(5)
                try:
                    return tls.wrap_socket(sock,server_side=True,do_handshake_on_connect=False), address
                except Exception:
                    sock.close()
                    raise
        httpd = TLSHTTPServer((os.environ.get('CRYPTOG_API_BIND','0.0.0.0'), LIBRARY_PORT), Handler)
        worker = __import__("threading").Thread(target=httpd.serve_forever, name="model-library", daemon=True)
        worker.start()
        httpd.worker = worker
        logger.info("Model library listening on 0.0.0.0:%s dir=%s", LIBRARY_PORT, LIBRARY_DIR)
        return httpd
    except Exception as e:
        logger.error("Model library HTTP server did not start: %s", e)
        raise


# Firebase Admin SDK Setup
FCM_INITIALIZED = False
FCM_KEY_PATH = os.environ.get('CRYPTOG_FCM_KEY_PATH', '/opt/shotcrypto/serviceAccountKey.json')

try:
    import firebase_admin
    from firebase_admin import credentials, messaging

    if os.path.exists(FCM_KEY_PATH):
        cred = credentials.Certificate(FCM_KEY_PATH)
        firebase_admin.initialize_app(cred)
        FCM_INITIALIZED = True
        logger.info(">>> Firebase Admin SDK Initialized! Topic broadcast active.")
    else:
        logger.warning("FCM Key not found at %s. Running in log alert mode.", FCM_KEY_PATH)
except Exception as e:
    logger.error("Failed to initialize Firebase Admin SDK: %s", e)


def fcm_payload(sig: dict) -> dict:
    """Field names match the Android client. Values are strings because FCM data is a string map."""
    fields = {
        "id": sig.get("structure_key") or f"{sig['symbol']}_{sig['strategy']}_{sig['confirmation_time']}",
        "symbol": "BTCUSDT",
        "signalType": "BUY",
        "strategy": sig["strategy"],
        "strategyNameZh": sig["strategy_name_zh"],
        "entryPrice": sig["entry_price"],
        "targetTP1": sig["target_tp1"],
        "targetTP2": sig["target_tp2"],
        "stopLoss": sig["stop_loss"],
        "profitPercent1": sig["profit_pct1"],
        "profitPercent2": sig["profit_pct2"],
        "stopLossPercent": sig["stop_loss_pct"],
        "riskRewardRatio": sig["risk_reward"],
        "netProfitPct1": sig["net_tp1"],
        "netRiskReward": sig["net_rr"],
        "timeHorizon": sig["time_horizon"],
        "ruleScore": sig["rule_score"],
        "rawRuleScore": sig.get("raw_rule_score", sig["rule_score"]),
        "ruleScoreBreakdown": sig.get("rule_score_breakdown", ""),
        "decisionStatus": "BUY_CANDIDATE",
        "confirmationTime": sig["confirmation_time"],
        "engineVersion": V2_ENGINE_VERSION if sig.get("rule_version") == "short-horizon-v2" else ENGINE_VERSION,
        "reasonZh": sig["reason_zh"],
        "volatilityLevel": sig["volatility_level"],
        "quantilePct": sig["quantile_pct"],
        "regime": sig.get("regime", ""),
        "historicalWinRateNote": "历史胜率：未验证",
        "timestamp": sig["timestamp"],
        "expiresAt": sig["expires_at"],
        "entryMin": sig["entry_min"],
        "entryMax": sig["entry_max"],
        "breakoutLevel": sig.get("breakout_level"),
        "rsi14": sig.get("rsi14"),
        "atrPercent": sig.get("atr_percent"),
        "volumeMultiplier": sig.get("volume_multiplier"),
        "vwapDiffPercent": sig.get("vwap_diff_percent"),
        "orderFlowImbalance": sig.get("order_flow_imbalance"),
        "estimatedFriction": sig.get("friction_pct", FRICTION_PCT),
        "netProfitPct2": sig.get("net_tp2"),
        "structureSupportPrice": sig.get("structure_support"),
        "tier": sig.get("tier"),
        "tierLabel": sig.get("tier_label"),
        "aiVerdict": sig.get("ai_verdict"),
        "aiNote": sig.get("ai_note"),
        "positionFractionPct": sig.get("position_fraction_pct"),
        "breakevenPrice": sig.get("breakeven_price"),
        "timeStopMinutes": sig.get("time_stop_minutes"),
        "tradeRules": json.dumps({"model": sig.get("model"), "ruleVersion": sig.get("rule_version"),
            "maxHoldMinutes": sig.get("max_hold_minutes"), "minNetTp1": sig.get("min_net_tp1"),
            "minNetRr": sig.get("min_net_rr"), "frictionPct": sig.get("friction_pct"), "costSnapshot": sig.get("cost_snapshot"),
            "maxNetTarget": sig.get("max_net_target"), "invalidationPrice": sig.get("invalidation_price"),
            "tp1Fraction": sig.get("tp1_fraction"), "targetBasis": sig.get("target_basis"),
            "exitRule": sig.get("exit_rule"), "tier": sig.get("tier"), "tierLabel": sig.get("tier_label")}, ensure_ascii=False),
    }
    return {k: str(v) for k, v in fields.items() if v is not None}


def send_fcm_alert(title: str, body: str, data: Optional[dict] = None) -> bool:
    if not FCM_INITIALIZED:
        logger.info("[ALERT SIMULATED] %s\n%s", title, body)
        return False
    try:
        payload_data = dict(data or {})
        payload_data["title"] = str(title)
        payload_data["body"] = str(body)
        remaining_ms = int(payload_data.get("expiresAt", 0)) - int(time.time() * 1000)
        if remaining_ms <= 0:
            return False
        msg = messaging.Message(
            notification=messaging.Notification(title=title, body=body),
            topic="shot_crypto_signals",
            data=payload_data,
            android=messaging.AndroidConfig(
                priority="high",
                ttl=datetime.timedelta(milliseconds=notification_ttl_ms(payload_data, remaining_ms)),
                notification=messaging.AndroidNotification(
                    channel_id="shot_crypto_signals_v2",
                    sound="default",
                    default_vibrate_timings=True,
                    tag=payload_data.get('eventId'),
                )
            )
        )
        res = messaging.send(msg)
        logger.info(">>> FCM PUSH BROADCAST SUCCESS! MsgID: %s | Title: %s", res, title)
        return True
    except Exception as e:
        logger.error("FCM broadcast failed: %s", e)
        return False


def send_position_hint(token, data):
    """Device-directed inbox hint; never broadcast actual positions to a topic."""
    if not FCM_INITIALIZED:return False
    remaining=int(data['expiresAtMs'])-int(time.time()*1000)
    if remaining<=0:return False
    try:
        messaging.send(messaging.Message(token=token,data=data,
            notification=messaging.Notification(title='Crypto-G 持仓退出事件',body='有待核对的持仓退出记录，请打开查看最新状态。提醒不代表成交。'),
            android=messaging.AndroidConfig(priority='high',ttl=datetime.timedelta(milliseconds=min(remaining,300000)),
                notification=messaging.AndroidNotification(channel_id='cryptog_position_exits_v1',tag='cryptog-position-inbox',
                    sound='default',visibility='private',default_vibrate_timings=True))))
        return True
    except Exception as exc:
        logger.warning('Position push failed: %s',type(exc).__name__)
        return False


def main():
    global RUNTIME
    from cryptog.runtime import Runtime
    RUNTIME = Runtime(sys.modules[__name__])
    RUNTIME.run()

if __name__ == "__main__":
    main()
