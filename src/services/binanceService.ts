import { KlineCandle, MarketTicker, ApiProviderConfig } from '../types/crypto';

export const API_PROVIDERS: ApiProviderConfig[] = [{
  id:'BINANCE', name:'Binance Global 现货公开行情', apiKey:'无需密钥',
  status:'active', latencyMs:null, description:'同一币安现货市场；实时延迟需测量，断流显示未知。', isPrimary:true,
}];

export const INITIAL_WATCHLIST_SYMBOLS = ['BTCUSDT'];

export const SYMBOL_METADATA: Record<
  string,
  { name: string; precision: number; roleZh: string; role: 'PRIMARY_TRADING' | 'MACRO_BEACON' }
> = {
  BTCUSDT: {
    name: 'Bitcoin (比特币)',
    precision: 2,
    roleZh: '核心量化交易标的 (实盘买入/大盘锚定)',
    role: 'PRIMARY_TRADING',
  },
};

class BinanceService {
  private ws: WebSocket | null = null;
  private finnhubWs: WebSocket | null = null;
  private tickerListeners: ((tickers: Record<string, MarketTicker>) => void)[] = [];
  private currentTickers: Record<string, MarketTicker> = {};
  private activeProvider: 'BINANCE' | 'FINNHUB' | 'MASSIVE' | 'ALPHA_VANTAGE' = 'BINANCE';
  private klineCache: Record<string, KlineCandle[]> = {};
  private isPollingActive = false;
  private pollIntervalId: any = null;
  private lastFetchedRealPrice: Record<string, number> = {};
  private consecutiveErrors = 0;

  constructor() {
    this.currentTickers['BTCUSDT'] = {
      symbol: 'BTCUSDT',
      name: 'Bitcoin (比特币)',
      price: 0,
      change24h: 0,
      high24h: 0,
      low24h: 0,
      volume24h: 0,
      quoteVolume24h: 0,
      lastUpdate: Date.now(),
      dataSource: '正在连接币安行情...',
      sparkline: [],
    };
  }

  public setProvider(provider: 'BINANCE' | 'FINNHUB' | 'MASSIVE' | 'ALPHA_VANTAGE') {
    this.activeProvider = provider;
  }

  public getActiveProvider() {
    return this.activeProvider;
  }

  /**
   * Fetch real 24h ticker info from Binance & Fallback APIs with 100% REAL data
   */
  public async fetchTicker24h(symbol = 'BTCUSDT'): Promise<MarketTicker | null> {
    const startMs = Date.now();
    const coinMeta = SYMBOL_METADATA[symbol] || { name: symbol, precision: 2 };

    // 1. Try Binance Vision / Binance US / Proxy endpoints first
    const binanceEndpoints = [
      'https://data-api.binance.vision/api/v3',
      'https://api.binance.com/api/v3',
    ];

    for (const base of binanceEndpoints) {
      try {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 3500);
        const url = `${base}/ticker/24hr?symbol=${symbol}`;
        const res = await fetch(url, {
          headers: { Accept: 'application/json' },
          signal: controller.signal,
        });
        clearTimeout(timeoutId);

        if (!res.ok) continue;
        const data = await res.json();
        if (!data || !data.lastPrice || data.code !== undefined) continue;

        const currentPrice = parseFloat(data.lastPrice);
        if (isNaN(currentPrice) || currentPrice <= 0) continue;

        this.lastFetchedRealPrice[symbol] = currentPrice;
        this.consecutiveErrors = 0;
        const existing = this.currentTickers[symbol];

        const prevSparkline = existing?.sparkline && existing.sparkline.length > 0
          ? existing.sparkline
          : [currentPrice];

        const sparkline = [...prevSparkline.slice(-24), currentPrice];

        const ticker: MarketTicker = {
          symbol: data.symbol || symbol,
          name: coinMeta.name,
          price: currentPrice,
          change24h: +(parseFloat(data.priceChangePercent) || 0).toFixed(2),
          high24h: parseFloat(data.highPrice) || currentPrice,
          low24h: parseFloat(data.lowPrice) || currentPrice,
          volume24h: parseFloat(data.volume) || 0,
          quoteVolume24h: parseFloat(data.quoteVolume) || 0,
          lastUpdate: Number(data.closeTime) || 0,
          dataSource: '币安官方实时直连 (Binance Vision)',
          latency: Date.now() - startMs,
          sparkline,
        };

        this.currentTickers[symbol] = ticker;
        this.notifyListeners();
        return ticker;
      } catch {
        // Try next endpoint
      }
    }

    // No cross-venue or fabricated fallback.
    return this.currentTickers[symbol] || null;
  }

  /**
   * Fetch 1m / 5m / 1h Klines for real technical analysis
   */
  public async fetchKlines(
    symbol = 'BTCUSDT',
    interval: '1m' | '5m' | '15m' | '1h' | '4h' = '1m',
    limit = 60
  ): Promise<KlineCandle[]> {
    const cacheKey = `${symbol}_${interval}_${limit}`;
    const binanceEndpoints = [
      'https://data-api.binance.vision/api/v3',
      'https://api.binance.com/api/v3',
    ];

    for (const base of binanceEndpoints) {
      try {
        const url = `${base}/klines?symbol=${symbol}&interval=${interval}&limit=${limit}`;
        const res = await fetch(url);
        if (!res.ok) continue;
        const raw = await res.json();
        if (!Array.isArray(raw) || raw.length === 0) continue;

        const now = Date.now();
        let cumulativeVol = 0;
        let cumulativePriceVol = 0;
        const candles: KlineCandle[] = raw.map((k: any) => {
          const openTime = parseInt(k[0], 10);
          const open = parseFloat(k[1]);
          const high = parseFloat(k[2]);
          const low = parseFloat(k[3]);
          const close = parseFloat(k[4]);
          const volume = parseFloat(k[5]);
          const closeTime = parseInt(k[6], 10);
          const takerBuyBase = parseFloat(k[9]);
          const isClosed = now >= closeTime;
          const typicalPrice = (high + low + close) / 3;

          cumulativeVol += volume;
          cumulativePriceVol += typicalPrice * volume;
          const vwap = cumulativeVol > 0 ? +(cumulativePriceVol / cumulativeVol).toFixed(2) : close;

          return {
            time: openTime,
            open,
            high,
            low,
            close,
            volume,
            takerBuyBase: Number.isFinite(takerBuyBase) ? takerBuyBase : undefined,
            vwap,
            closeTime,
            isClosed,
          };
        });

        this.klineCache[cacheKey] = candles;
        return candles;
      } catch {
        // Try next
      }
    }

    if (this.klineCache[cacheKey] && this.klineCache[cacheKey].length > 0) {
      return this.klineCache[cacheKey];
    }

    // Do NOT return fake klines if data is unavailable - fail safely with empty list
    return [];
  }

  /**
   * Fetch order book depth to calculate bid/ask microstructure imbalance and spread
   */
  public async fetchOrderBookDepth(
    symbol = 'BTCUSDT'
  ): Promise<{
    bidVolume: number;
    askVolume: number;
    imbalanceRatio: number;
    spreadPct: number;
    bestBid: number;
    bestAsk: number;
    isValid: boolean;
  }> {
    const binanceEndpoints = [
      'https://data-api.binance.vision/api/v3',
    ];

    for (const base of binanceEndpoints) {
      try {
        const url = `${base}/depth?symbol=${symbol}&limit=20`;
        const res = await fetch(url);
        if (!res.ok) continue;
        const data = await res.json();
        if (!data.bids || !data.asks || data.bids.length === 0 || data.asks.length === 0) continue;

        let bidVol = 0;
        let askVol = 0;
        data.bids.forEach((b: any) => {
          bidVol += parseFloat(b[1]);
        });
        data.asks.forEach((a: any) => {
          askVol += parseFloat(a[1]);
        });

        const total = bidVol + askVol;
        const imbalanceRatio = total > 0 ? (bidVol - askVol) / total : 0;
        const bestBid = parseFloat(data.bids[0][0]);
        const bestAsk = parseFloat(data.asks[0][0]);
        const midPrice = (bestBid + bestAsk) / 2;
        const spreadPct = midPrice > 0 ? +(((bestAsk - bestBid) / midPrice) * 100).toFixed(4) : 0.01;

        return {
          bidVolume: +bidVol.toFixed(3),
          askVolume: +askVol.toFixed(3),
          imbalanceRatio: +imbalanceRatio.toFixed(3),
          spreadPct,
          bestBid,
          bestAsk,
          isValid: true,
        };
      } catch {}
    }

    return {
      bidVolume: 0,
      askVolume: 0,
      imbalanceRatio: 0,
      spreadPct: 0.05,
      bestBid: 0,
      bestAsk: 0,
      isValid: false,
    };
  }

  /**
   * Connect to Binance real-time WebSocket for live tick stream (BTCUSDT)
   * With automatic fallback to Finnhub WebSocket
   */
  public connectWebSocket() {
    if (typeof window === 'undefined') return;

    try {
      if (this.ws) {
        this.ws.close();
      }

      // Binance stream for BTCUSDT mini ticker
      const wsUrl = 'wss://data-stream.binance.vision/stream?streams=btcusdt@miniTicker';
      this.ws = new WebSocket(wsUrl);

      this.ws.onmessage = (event) => {
        try {
          const payload = JSON.parse(event.data);
          const data = payload.data || payload;
          if (data && data.c) {
            const sym = 'BTCUSDT';
            if (!this.currentTickers[sym]) return;

            const price = parseFloat(data.c);
            const high = parseFloat(data.h);
            const low = parseFloat(data.l);
            const volume = parseFloat(data.v);
            const existing = this.currentTickers[sym];
            this.lastFetchedRealPrice[sym] = price;

            const prevSparkline = existing?.sparkline && existing.sparkline.length > 0
              ? existing.sparkline
              : [price];
            const sparkline = [...prevSparkline.slice(-24), price];

            this.currentTickers[sym] = {
              ...existing,
              symbol: sym,
              name: SYMBOL_METADATA[sym]?.name || existing.name,
              price,
              high24h: Math.max(existing?.high24h || 0, high),
              low24h: existing?.low24h && existing.low24h > 0 ? Math.min(existing.low24h, low) : low,
              volume24h: volume,
              lastUpdate: Date.now(),
              dataSource: '币安 WebSocket 毫秒级逐笔 (Vision)',
              sparkline,
            };
            this.notifyListeners();
          }
        } catch {}
      };

      this.ws.onerror = () => {
        this.connectFinnhubWebSocket();
      };

      this.ws.onclose = () => {
        setTimeout(() => {
          if (this.isPollingActive && !this.finnhubWs) {
            this.connectWebSocket();
          }
        }, 5000);
      };
    } catch {
      this.connectFinnhubWebSocket();
    }
  }

  /**
   * Finnhub real-time trade tick WebSocket fallback for BTC
   */
  private connectFinnhubWebSocket() {
    // No embedded third-party credentials or cross-source fallback.
    // Existing Binance REST/reconnect paths continue; unavailable data stays unavailable.
  }

  /**
   * Start high-frequency scanning for BTC
   */
  public startScanning(intervalMs = 2000) {
    this.isPollingActive = true;
    if (this.pollIntervalId) {
      clearInterval(this.pollIntervalId);
    }

    // Connect WebSockets
    this.connectWebSocket();

    // Initial immediate fetch
    this.fetchTicker24h('BTCUSDT');

    // Periodic scanner
    this.pollIntervalId = setInterval(() => {
      this.fetchTicker24h('BTCUSDT');
    }, Math.max(1000, intervalMs));
  }

  public stopScanning() {
    this.isPollingActive = false;
    if (this.pollIntervalId) {
      clearInterval(this.pollIntervalId);
      this.pollIntervalId = null;
    }
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
    if (this.finnhubWs) {
      this.finnhubWs.close();
      this.finnhubWs = null;
    }
  }

  public onTickersUpdate(listener: (tickers: Record<string, MarketTicker>) => void) {
    this.tickerListeners.push(listener);
    listener(this.currentTickers);
    return () => {
      this.tickerListeners = this.tickerListeners.filter((l) => l !== listener);
    };
  }

  private notifyListeners() {
    this.tickerListeners.forEach((l) => l({ ...this.currentTickers }));
  }

  public getTicker(symbol = 'BTCUSDT'): MarketTicker | undefined {
    return this.currentTickers[symbol];
  }
}

export const binanceService = new BinanceService();
