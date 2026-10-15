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
MIN_NET_TP1 = 0.40
MIN_NET_RR = 1.10
SETUP_MAX_AGE_MS = 120_000
ALERT_TTL_MS = 90_000
QUOTE_MAX_AGE_MS = 10_000
MAX_ENTRY_DEVIATION_PCT = 0.15
MAX_STRUCTURAL_SL_PCT = 3.0
MAX_TREND_SL_PCT = 1.20
ENGINE_VERSION = "Crypto-G V1.16"
RULE_VERSION = "three-models-v1"
# Policy thresholds are conservative initial hypotheses, not fitted win-rate claims.
TRADE_POLICIES = {
    "BREAKOUT": {"max_hold_minutes": 240, "min_net_tp1": 0.40, "max_net_target": None, "max_stop_pct": 1.20, "tp1_fraction": 0.50},
    "REBOUND": {"max_hold_minutes": 90, "min_net_tp1": 1.00, "max_net_target": 6.00, "max_stop_pct": 2.00, "tp1_fraction": 0.70},
    "RANGE": {"max_hold_minutes": 240, "min_net_tp1": 1.00, "max_net_target": 4.00, "max_stop_pct": 1.20, "tp1_fraction": 1.00},
}
TARGET_BUFFER_PCT = 0.05  # Exit before observed resistance, never extend it.

