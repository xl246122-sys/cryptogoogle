# Crypto-G Project Rules & Instructions for AI Coding Assistants

## APK Delivery Rule
- **Target Output Directory**: `D:\Crypto-Google\release`
- **File Naming Pattern**: `Crypto-G V{versionName}.apk` (e.g. `Crypto-G V1.03.apk`)
- **Version Increment**: Increment `versionName` by `+0.01` and `versionCode` by `+1` on each release in `android/app/build.gradle`.
- **Automated Copy**: Gradle `assembleDebug` automatically executes `copyApkToRelease` to place the compiled APK directly into `D:\Crypto-Google\release`.

## Quantitative Engine Rules (`short-horizon-v2`)

Approved plan: `开发方案资料 Opus5.5/CryptoGoogle-BTC短线交易监控预警系统-开发方案.md`. Do not retune the numbers below. Learning may not move the hard constraints.

- **Asset**: `BTCUSDT` spot, long only.
- **Holding**: 5 minutes to 6 hours.
- **Rule version**: `short-horizon-v2`. Engine A lives in `scratch/cryptog/engine_v2.py`. Constants are the `V2_*` names in `scratch/cryptog/config.py`.
- **Legacy constants**: `FRICTION_PCT = 0.11` and the old TP1 / RR gates stay only so retired records can be replayed.

### Cost, target, stop, size
- **Friction**: `0.24%` round trip (0.10% taker per side + about 0.02% slippage per side, BNB discount off). With BNB discount the floor is `0.19%`. Real fills may raise the working cost (`scratch/cryptog/cost_model.py`); they may not lower the floor.
- **Net TP1**: at least `0.50%` (gross at least `0.74%`), checked at the worst price of the entry band.
- **Net RR**: Net TP1 / (stop distance + friction) at least `1.0`.
- **Stop distance**: `0.35%` to `1.20%`, structural price plus a `0.15 × ATR15` buffer where the module says so. Never tighten a structural stop to pass the gate. A stop closer than 0.35% is moved farther away.
- **Position**: risk `0.5%` of equity. Notional fraction = risk / (stop distance + friction). The twin ledger is `scratch/cryptog/ledger.py` at `500 USDT`.
- **Validity**: two bars of the trigger timeframe (30 minutes on 15m, 10 minutes on 5m). Price running `0.25%` above the entry band voids the setup.

### Exits
- TP1 sells 50% and moves the stop to breakeven plus friction. The remainder trails the 15m EMA20 or leaves at TP2.
- At 90 minutes, exit if progress is under `+0.3R`. Hard exit at 360 minutes.
- On one bar, a stop touch outranks a target touch.
- Tick reminders (`scratch/cryptog/stop_monitor.py`): plan, within 0.15% of the stop, 15m close back under the reclaim price, stop, 90-minute / 6-hour time exit, TP1, a 1% drop inside 5 minutes, or a 1H close through environment support. Real fills and shadow positions both use this classification. Closed-bar settlement stays reproducible.

### Environment and modules
- **Context**: 1D / 4H / 1H use Binance-chart definitions (EMA7/25/99 SMA-seeded, BOLL(20,2) population SD, Wilder RSI6/14 and ATR14).
- **S1 flush reclaim** (any environment; watch tier, first candidate for promotion): 12h drop at least `2.5%`, and `3.5%` when 4H is bearish; low-bar volume at least `2.5×`; 15m green close back above the low bar's midpoint. Limit from reclaim close `-0.05%` to `+0.10%`. Stop = flush low − `0.15 × ATR15`. TP1 is the nearer of the last 1H swing high and `1 × ATR1h`.
- **S1 derivatives, score only**: OI down at least `3%` in 1 hour, funding rate at or below `-0.01%` (`-0.0001` in exchange decimals), or taker sell/buy at least `1.5`. Each match adds 8 points. None of them is required to emit the setup.
- **S2 support retest** (daily bull and 4H still above the daily EMA99): touch of the 4H lower band, a prior flush low, or the daily EMA cluster within `±0.3%`; 15m lower wick at least `1.5×` the body and the close back above the level. Limit is the level `+0.05%` to `+0.20%`. Stop is the level − `0.20%`. TP1 is the nearer of the 4H midline and the range midline.
- **S3 trend pullback**: closed until a 4H close is above the 4H EMA99, and both 4H and 1H are bullish. Then 15m RSI14 below `45` and a 5m close back above the 15m EMA20. Limit is EMA20 `±0.10%`. Stop is under the 15m pullback swing low.
- **S4 squeeze breakout**: closed until a 4H close is above the 4H EMA99. Also requires 4H not bearish and the US session window `13:00–20:00 UTC` (Beijing 21:00–04:00). 15m bandwidth in the lowest `20%` of `200` bars, volume at least `2×`, close through the prior `16`-bar high. Limit is a retest of the breakout, not a chase. Stop is the lower of the breakout-bar low and the midline, minus `0.15 × ATR15`. Target is one times the box height.
- **S5 session momentum**: research only, never a BUY push. Weekday US cash open (13:30 UTC in EDT, 14:30 UTC in EST) and the first 30 minutes close up on at least `1.5×` the prior `20` sessions' volume. No entry, stop, or target.
- **5m flush monitor**: a flush in progress is reported and does not emit a BUY.
- **Tier**: until a module passes the promotion gates on unseen data, every BUY push is `观察级·未验证` (`WATCH`). The circuit breaker pauses trade-tier pushes only; watch-tier pushes continue.
- **Circuit breaker**: two consecutive stops, or `−2R` in one CST day, pauses trade-tier BUY pushes for 4 hours.

### Promotion gates
All of these must hold out of sample: at least 60 trades; net expectancy at least `+0.10%` per trade with a bootstrap 95% lower bound above 0; win rate at least `52%` (launch target `55%`); profit factor at least `1.30`; PBO below `0.30`; when more than 20 parameter sets were tried, DSR above `0.95`; trade-tier frequency `0.5–6` per day. Launch also requires at least half of `≥1.5%` waves to have a candidate in the first third of the move. Tools: `scratch/cryptog/validation.py`, `scratch/cryptog/barriers.py`, `scratch/cryptog/baseline.py`.

### What learning must not change
BTC only, long only, the AI does not write prices, the cost floor, stop distance at most `1.20%`, hold at most 6 hours, and the circuit breaker.

### Research library
- Spot klines (`1m`, `5m`, `15m`, `1h`, `4h`, `1d`) and accumulated funding, open interest, and taker ratio: `scratch/cryptog/kline_store.py`.
- The daemon appends derivatives on `research.sqlite3` inside the model-library directory (`scratch/cryptog/derivatives.py`).
- The seven live tables (`candidates`, `features`, `shadow_positions`, `labels`, `real_fills`, `model_registry` / `promotions`, `ai_reviews`) are created by `scratch/cryptog/ledger.py` in `research.sqlite3`. `scratch/cryptog/evolution.py` writes `promotions` when a module finishes the 14-day shadow stage, finishes the 14-day trial, or rolls back. L1 proposals and P3 hypotheses do not change S1–S5 parameters. AI review content stays in P3; the table and its insert exist.

### AI and retired paths
- **AI**: reads Engine A output only. PASS / DOWNGRADE / VETO, fixed tags, one Chinese sentence, no prices. Timeout is 8 seconds; a timeout or a bad payload counts as PASS and is logged. Vetoed signals still settle in the shadow ledger. After 100 vetoed outcomes, veto stays enabled only if those outcomes were worse than the ones that passed.
- **Retired**: 1m five-barrier anti-knife gates (`RANGE_MICRO` / `RANGE_MEDIUM`), `short-horizon-v1`, the experimental push path, and AI-originated BUY pushes.
- **Server**: `43.163.203.127:/opt/shotcrypto/scanner_daemon.py` (`shotcrypto.service`).
