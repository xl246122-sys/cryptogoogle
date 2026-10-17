# Symbols - User Command: Fixed exclusively to BTC/USDT!
MACRO_BENCHMARK = "BTCUSDT"
TARGET_SYMBOLS = ["BTCUSDT"]

# Scanner Settings
SCAN_INTERVAL_SECONDS = 2.0
MIN_BEARISH_DROP_REQUIRED = 5.0
COOLDOWN_SECONDS = 90
# 15m x 240 bars = 60 hours. W=16 gives about 15 non-overlapping windows.
REGIME_MIN_BARS = 96  # 24h of 15m bars. Enough for W=16 without blocking the scan.
REGIME_WINDOW_BARS = 16
FRICTION_PCT = 0.11  # Assumed round-trip allowance, not a measured fill.
MIN_GROSS_TP1 = 0.70
MIN_NET_TP1 = max(0.40, MIN_GROSS_TP1 - FRICTION_PCT)
MIN_NET_RR = 1.10
SETUP_MAX_AGE_MS = 120_000
ALERT_TTL_MS = 90_000
QUOTE_MAX_AGE_MS = 10_000
MAX_ENTRY_DEVIATION_PCT = 0.15
MAX_STRUCTURAL_SL_PCT = 3.0
MAX_TREND_SL_PCT = 1.20
ENGINE_VERSION = "Crypto-G V1.16"
RULE_VERSION = "three-models-v2"
# Policy thresholds are conservative initial hypotheses, not fitted win-rate claims.
TRADE_POLICIES = {
    "BREAKOUT": {"max_hold_minutes": 240, "min_net_tp1": MIN_NET_TP1, "max_net_target": None, "max_stop_pct": 1.20, "tp1_fraction": 0.50},
    "REBOUND": {"max_hold_minutes": 90, "min_net_tp1": MIN_NET_TP1, "max_net_target": 6.00, "max_stop_pct": 2.00, "tp1_fraction": 0.70},
    "RANGE": {"max_hold_minutes": 240, "min_net_tp1": MIN_NET_TP1, "max_net_target": 4.00, "max_stop_pct": 1.20, "tp1_fraction": 1.00},
}
TARGET_BUFFER_PCT = 0.05  # Exit before observed resistance, never extend it.

# short-horizon-v2. The constants above remain only for the retired legacy routes and their replays.
V2_RULE_VERSION = "short-horizon-v2"
V2_ENGINE_VERSION = "Crypto-G V1.47"
V2_FRICTION_PCT = 0.24          # 0.10% taker each side + ~0.02% slippage each side, no BNB discount.
V2_MIN_NET_TP1 = 0.50           # Gross TP1 >= 0.74%.
V2_MIN_NET_RR = 1.00            # Net TP1 / (stop distance + friction).
V2_STOP_MIN_PCT = 0.35
V2_STOP_MAX_PCT = 1.20
V2_MAX_HOLD_MINUTES = 360
V2_TIME_STOP_MINUTES = 90
V2_TIME_STOP_PROGRESS_R = 0.30
V2_TP1_FRACTION = 0.50
V2_ENTRY_BELOW_PCT = 0.05       # Limit band below the reclaim close.
V2_ENTRY_ABOVE_PCT = 0.10
V2_ESCAPE_PCT = 0.25            # Price above the band top by this much voids the setup.
V2_RISK_PER_TRADE_PCT = 0.50    # Account fraction lost at the stop.
V2_NEAR_STOP_PCT = 0.15
V2_BREAKER_STOPS = 2
V2_BREAKER_DAILY_R = -2.0
V2_BREAKER_PAUSE_MS = 4 * 3600 * 1000
V2_CONTEXT_MAX_AGE_MS = 20 * 60 * 1000
V2_AI_TIMEOUT_S = 8.0
V2_TIER_WATCH = "WATCH"
V2_TIER_LABEL = "观察级·未验证"
V2_BNB_FRICTION_PCT = 0.19      # 0.075% taker each side + ~0.02% slippage, only if BNB discount is on.
V2_TAKER_PCT = 0.10
V2_SLIPPAGE_PCT = 0.02
V2_S1_MIN_DROP_PCT = 2.5
V2_S1_BEAR_EXTRA_PCT = 1.0
V2_S1_MIN_VOLUME_MULT = 2.5
V2_S1_STOP_ATR = 0.15
V2_S2_TOUCH_PCT = 0.30
V2_S2_WICK_TO_BODY = 1.5
V2_S2_ENTRY_MIN_PCT = 0.05
V2_S2_ENTRY_MAX_PCT = 0.20
V2_S2_STOP_PCT = 0.20
V2_S3_RSI_MAX = 45
V2_S3_ENTRY_BAND_PCT = 0.10
V2_S3_STOP_ATR = 0.15
V2_S4_VOLUME_MULT = 2.0
V2_S4_BAND_LOOKBACK = 200
V2_S4_BAND_PERCENTILE = 0.20
V2_S4_BREAK_BARS = 16
V2_S4_STOP_ATR = 0.15
V2_S4_SESSION_START_UTC = 13    # Beijing 21:00
V2_S4_SESSION_END_UTC = 20      # Beijing 04:00
V2_S5_VOLUME_MULT = 1.5
V2_S5_PRIOR_SESSIONS = 20
V2_OI_DROP_1H_PCT = 3.0
V2_FUNDING_EXTREME = -0.0001    # Exchange decimal for -0.01%.
V2_TAKER_SELL_MIN = 1.5
V2_DERIVATIVE_POINTS = 8
V2_ENV_DROP_5M_PCT = 1.0
V2_PROMOTE_MIN_TRADES = 60
V2_PROMOTE_MIN_EXPECTANCY = 0.10
V2_PROMOTE_MIN_WIN_RATE = 0.52
V2_PROMOTE_TARGET_WIN_LOW = 0.55
V2_PROMOTE_TARGET_WIN_HIGH = 0.62
V2_PROMOTE_MIN_PROFIT_FACTOR = 1.30
V2_PROMOTE_MAX_PBO = 0.30
V2_PROMOTE_MIN_DSR = 0.95
V2_PROMOTE_DSR_TRIALS = 20
V2_PROMOTE_MIN_PER_DAY = 0.5
V2_PROMOTE_MAX_PER_DAY = 6.0
V2_LAUNCH_MIN_WIN_RATE = 0.55
V2_RECALL_MOVE_PCT = 1.5
V2_RECALL_EARLY_FRACTION = 1 / 3
V2_RECALL_MIN = 0.50
V2_OOS_MS = 122 * 24 * 3600 * 1000
V2_EMBARGO_MS = 6 * 3600 * 1000
V2_PAPER_NOTIONAL_USDT = 500    # Fixed twin size. Opened by scratch/cryptog/ledger.py.
V2_TIER_RESEARCH = "RESEARCH"
V2_BNB_FRICTION_PCT = 0.19       # VIP0 with BNB discount: 0.075% taker each side + ~0.02% slippage each side.
V2_TAKER_PCT = 0.10
V2_SLIPPAGE_PCT = 0.02
V2_S1_MIN_DROP_PCT = 2.5
V2_S1_BEAR_EXTRA_PCT = 1.0       # 4H bearish: required drop becomes 3.5%.
V2_S1_MIN_VOLUME_MULT = 2.5
V2_S1_STOP_ATR = 0.15
V2_S2_TOUCH_PCT = 0.30
V2_S2_WICK_TO_BODY = 1.5
V2_S2_ENTRY_MIN_PCT = 0.05
V2_S2_ENTRY_MAX_PCT = 0.20
V2_S2_STOP_PCT = 0.20
V2_S3_RSI_MAX = 45
V2_S3_ENTRY_BAND_PCT = 0.10
V2_S3_STOP_ATR = 0.15
V2_S4_VOLUME_MULT = 2.0
V2_S4_BAND_LOOKBACK = 200
V2_S4_BAND_PERCENTILE = 0.20
V2_S4_BREAK_BARS = 16
V2_S4_STOP_ATR = 0.15
V2_S4_SESSION_START_UTC = 13     # 21:00 Beijing. US session, through 04:00 Beijing.
V2_S4_SESSION_END_UTC = 20
V2_S5_VOLUME_MULT = 1.5
V2_S5_PRIOR_SESSIONS = 20
V2_OI_DROP_1H_PCT = 3.0
V2_FUNDING_EXTREME = -0.0001     # Exchange decimal. -0.0001 = -0.01%.
V2_TAKER_SELL_MIN = 1.5
V2_DERIVATIVE_POINTS = 8
V2_ENV_DROP_5M_PCT = 1.0
V2_PROMOTE_MIN_TRADES = 60
V2_PROMOTE_MIN_EXPECTANCY = 0.10
V2_PROMOTE_MIN_WIN_RATE = 0.52
V2_PROMOTE_TARGET_WIN_LOW = 0.55
V2_PROMOTE_TARGET_WIN_HIGH = 0.62
V2_PROMOTE_MIN_PROFIT_FACTOR = 1.30
V2_PROMOTE_MAX_PBO = 0.30
V2_PROMOTE_MIN_DSR = 0.95
V2_PROMOTE_DSR_TRIALS = 20
V2_PROMOTE_MIN_PER_DAY = 0.5
V2_PROMOTE_MAX_PER_DAY = 6.0
V2_LAUNCH_MIN_WIN_RATE = 0.55
V2_RECALL_MOVE_PCT = 1.5
V2_RECALL_EARLY_FRACTION = 1 / 3
V2_RECALL_MIN = 0.50
V2_OOS_MS = 122 * 24 * 3600 * 1000   # Last four months are the untouched validation window.
V2_EMBARGO_MS = 6 * 3600 * 1000      # Max hold. Train labels that reach into the test window are purged.
V2_PAPER_NOTIONAL_USDT = 500         # Fixed twin size. Opened by scratch/cryptog/ledger.py.
V2_SHADOW_MS = 14 * 24 * 3600 * 1000
V2_TRIAL_MS = 14 * 24 * 3600 * 1000
V2_ROLLBACK_TRADES = 30
V2_ROLLBACK_MAX_DRAWDOWN_R = 6.0
V2_L1_MIN_SAMPLES = 200
V2_L1_P_MIN = 0.50
V2_L1_P_MAX = 0.70
V2_L1_ENTRY_OFFSET_MIN_PCT = -0.10
V2_L1_ENTRY_OFFSET_MAX_PCT = 0.10
V2_L1_STOP_BUFFER_MIN_PCT = 0.0
V2_L1_STOP_BUFFER_MAX_PCT = 0.20
V2_TIER_TRIAL = "TRIAL"
V2_TIER_TRIAL_LABEL = "试运行"
V2_TIER_TRADE = "TRADE"
V2_TIER_TRADE_LABEL = "交易级"
# P5 held reports. The cost floor and the environment gates stay where they are.
# 10 score points is one 1H half-state (100 * 0.20 * 0.5). 20 is the full 1H weight.
V2_ENV_PRIOR_CUTOFF = 0
V2_ENV_CUTOFF_STEP = 10
V2_ENV_CUTOFF_SPAN = 20
V2_ENV_MIN_SAMPLES = 200
V2_ENV_MIN_SIDE = 30

