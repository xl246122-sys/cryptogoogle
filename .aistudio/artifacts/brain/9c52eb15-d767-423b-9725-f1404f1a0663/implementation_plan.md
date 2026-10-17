# ShotCrypto - Ultra-Short-Term Crypto Scanner & Quantitative Alert System

ShotCrypto is an ultra-short-term cryptocurrency trading scanner and real-time alert terminal designed for Bitcoin (BTC), SUI, and major altcoins. It monitors live market microstructures to capture 1%–6% profit opportunities within 1-minute to 6-hour holding windows using authoritative quantitative models.

---

## User Review & Critical Decisions

> [!IMPORTANT]
> The following core parameters and architecture decisions were confirmed during the Phase 1 consultation:
> 
> - **Deployment & Delivery Mode**: Mobile-first Progressive Web App (PWA) with native-grade touch ergonomics, real-time audio chimes, modal signal alerts, background notifications, plus a downloadable production Python scanner daemon ready for deployment on the user's Ubuntu server (`43.163.203.127`) and local environment (`D:\Shot-Crypto`).
> - **Quantitative Signal Engine**: Hybrid Consensus Multi-Model Engine combining 5 quantitative models:
>   1. **Markov Regime Switching (MRS)**: Identifies trending vs. mean-reverting vs. high-volatility market states.
>   2. **Volatility-Adjusted Momentum (VAM)**: Catches breakout surges with volume confirmation.
>   3. **VWAP & Bollinger Mean Reversion**: Spots extreme overextensions for rapid snap-backs.
>   4. **Flash Crash Dip Rebound**: Detects capitulation washouts for 1%–6% relief bounces.
>   5. **Order Flow & Microstructure Imbalance**: Assesses bid/ask pressure and aggressive taker volume.
> - **Signal Outputs**: Natural language trade signals with explicit Entry price, Target Take-Profit (TP 1%–6%), Stop-Loss (SL), estimated holding period (10m–5h), and model confidence.
> - **Real-Time Data Ingestion**: Primary Binance public REST & WebSocket streams with automatic failover to user-provided API credentials (Finnhub, Massive, Alpha Vantage).
> - **Alerting Modalities**: Web Audio synthesized alert chimes, high-priority modal popups, and browser notification integration with selectable scan frequencies (2s, 5s, 10s, 1m, 3m, 5m, 10m, 30m, 1h).

---

## 1. Overview & Core Concept

- **What It Does**: High-frequency crypto radar that continuously analyzes 1m, 5m, 15m, and 1h candlestick data and order book depth. When quantitative conditions align, it triggers instantaneous audio chimes and visual alerts showing precise Entry, TP1, TP2, and SL price levels with plain-language rationales.
- **Target Audience / Persona**: Active ultra-short-term scalpers and momentum traders who hold positions for 10 minutes to 5 hours, seeking repeatable 1%–6% gains while avoiding sudden regime shifts and catastrophic drawdowns.
- **Key Value**: Replaces emotional chasing with mathematical discipline: eliminates analysis paralysis by delivering actionable high-probability setups before moves exhaust.

---

## 2. User Experience & Visual Design

### Key User Flows
1. **Radar Feed (Home)**: Instant view of BTC/USDT and high-momentum pairs (SUI, ETH, SOL) with real-time price tickers, 24h change, and active quantitative regime badges. Live signal ticker displays the latest triggered opportunities.
2. **Signal Detail & Trade Planner**: Tapping any signal expands an analytical card showing:
   - Consensus Score (e.g., 88% Bullish Breakthrough)
   - Triggering Model Breakdown (e.g., Markov Regime: Trending Up, VAM: +3.2σ, VWAP: At Lower Band)
   - Natural Language Strategy: *"BTC 5m breakout above local resistance with 2.8x volume spike. Macro 1h trend remains bullish."*
   - Execution Targets: Recommended Entry, TP1 (+1.8%), TP2 (+3.6%), Stop Loss (-1.2%), Risk/Reward Ratio (2.3:1)
3. **Watchlist & Custom Monitor**: User adds custom coins (BTC, SUI, DOGE, SOL, etc.) with personalized price and volatility threshold alerts.
4. **Scanner Control & Engine Tuner**: Toggle scan intervals (2s, 5s, 10s, 1m, 5m), adjust sensitivity filters, enable/disable specific models, and test audio alert chimes.
5. **Server Daemon & Export Hub**: Direct code viewer and download center for the user's standalone Python script (`shot_crypto_daemon.py`), `systemd` service configuration, and Firebase Cloud Messaging (FCM) push worker designed for the Japanese Ubuntu server.

### Visual Identity & Theme
- **Aesthetic Direction**: Tactical Fintech Terminal with Google Material 3 and modern dark-mode depth. Crisp typography, high contrast, clean hairline borders (`border-slate-800`), and zero decorative fluff.
- **Color Palette**:
  - Dominant Canvas (60%): Slate deep black (`#090D16` / `bg-slate-950`)
  - Structural Surfaces (30%): Dark slate elevation surfaces (`#111827` / `bg-slate-900/90`)
  - Accents (10%):
    - Bullish / Buy Signals: Emerald Green (`#10B981` / `text-emerald-400`)
    - Bearish / Stop Loss: Rose Red (`#F43F5E` / `text-rose-400`)
    - Primary Interactive: Electric Cyan / Binance Yellow (`#F0B90B` / `#06B6D4`)
- **Typography & Hierarchy**:
  - Display & Headings: `Plus Jakarta Sans` for crisp legibility
  - Data, Prices, and Metrics: `JetBrains Mono` / tabular numerals (`font-mono tabular-nums`)
- **Ergonomics & Touch**:
  - Sticky bottom tab bar (Home, Signals, Watchlist, Strategy, Server Setup) with $\ge 44\text{px}$ touch targets
  - In-app PWA install trigger and audio enable toggle on initial user tap

---

## 3. Key Product Decisions & Trade-Offs

- **Decision 1: Direct Client Binance WebSocket + Express Proxy Failover**
  - *Chosen Approach*: Stream live ticker and 1m kline data directly from Binance public endpoints in the browser, with backend Express proxy fallback for CORS resilience.
  - *Why*: Delivers millisecond-level tick latency without hammering server CPU, while backup API keys (Finnhub, Massive, Alpha Vantage) provide multi-source redundancy.
- **Decision 2: In-Browser Quantitative Engine + Server Python Daemon**
  - *Chosen Approach*: The PWA executes the full quantitative mathematical pipeline client-side (Bollinger, RSI, VWAP, ATR, Volatility Momentum, Markov Regime simulation) while providing a fully featured, ready-to-run Python daemon for 24/7 background server scanning on the user's Ubuntu server.
  - *Why*: Gives the user immediate zero-setup execution in any browser/phone right now, plus the exact script needed for their 24/7 server setup.
- **Decision 3: Web Audio API Synthesizer for Alerts**
  - *Chosen Approach*: Synthesize crisp, professional alert chimes using the Web Audio API (sine/triangle oscillator frequency sweeps) with fallback HTML5 audio.
  - *Why*: Never relies on broken external audio URLs; works reliably across iOS Safari, Android Chrome, and desktop.

---

## 4. Technical Architecture & Data Strategy

```
┌────────────────────────────────────────────────────────────────────────┐
│                        ShotCrypto Frontend PWA                         │
│                                                                        │
│  ┌───────────────────────┐  ┌─────────────────┐  ┌──────────────────┐  │
│  │     Radar Feed        │  │  Signal Engine  │  │   Audio & Push   │  │
│  │ (Tickers & Kline Viz) │  │ (Hybrid Models) │  │  Alert Dispatch  │  │
│  └───────────┬───────────┘  └────────┬────────┘  └────────┬─────────┘  │
└──────────────┼───────────────────────┼────────────────────┼────────────┘
               │                       │                    │             
               ▼                       ▼                    ▼             
┌────────────────────────────────────────────────────────────────────────┐
│                     Client Quantitative Engine                         │
│                                                                        │
│  • Markov Regime Classifier (Trend / Range / Volatile)                 │
│  • Volatility-Adjusted Momentum (VAM, Z-score > 2.0)                   │
│  • VWAP & Bollinger Band Snapback (Mean Reversion)                     │
│  • Flash Crash Oversold Relief Calculator (RSI < 22, ATR stretch)      │
│  • SL / TP Target Formulator (1%–6% profit, 10m–5h horizon)            │
└──────────────────────────────────┬─────────────────────────────────────┘
                                   │
               ┌───────────────────┴───────────────────┐
               ▼                                       ▼
┌─────────────────────────────┐         ┌──────────────────────────────┐
│  Primary Live Feed          │         │  Redundant API Fallback      │
│  • Binance Public REST/WS   │         │  • Finnhub API Key           │
│  • Depth & Kline Streaming  │         │  • Massive API Key           │
│                             │         │  • Alpha Vantage API Key     │
└─────────────────────────────┘         └──────────────────────────────┘
                                   ▲
                                   │
┌──────────────────────────────────┴─────────────────────────────────────┐
│          Ubuntu Server Companion (`shot_crypto_daemon.py`)             │
│  • 24/7 High-Frequency Python Scanner (2s–5s loop)                     │
│  • Firebase Cloud Messaging (FCM) Push to Android App                  │
│  • Full deployment guide & Systemd service configuration               │
└────────────────────────────────────────────────────────────────────────┘
```

### Data Model & State
- `MarketTicker`: `{ symbol, price, change24h, high24h, low24h, volume24h, lastUpdate }`
- `KlineCandle`: `{ time, open, high, low, close, volume, vwap }`
- `TradeSignal`: `{ id, symbol, type: 'BUY' | 'SELL_RISK', strategy: 'BREAKOUT' | 'DIP_REBOUND' | 'VWAP_REVERSION' | 'REGIME_SWITCH', entryPrice, targetTP1, targetTP2, stopLoss, potentialProfitPercent, confidence, timeHorizon, explanation, timestamp }`
- `WatchlistItem`: `{ symbol, alertHigh, alertLow, trailingStopPercent, notes, isMonitored }`
- `ScannerConfig`: `{ scanIntervalMs: 2000, soundEnabled: true, pushEnabled: true, minProfitTarget: 1.5, maxProfitTarget: 6.0, selectedCoins: ['BTCUSDT', 'SUIUSDT', 'ETHUSDT', 'SOLUSDT'] }`
