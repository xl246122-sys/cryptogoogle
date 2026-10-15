from pathlib import Path
root=Path(__file__).resolve().parents[1]
p=root/'src/services/binanceService.ts';s=p.read_text(encoding='utf-8')
start=s.index('export const API_PROVIDERS:')
end=s.index('export const INITIAL_WATCHLIST_SYMBOLS',start)
s=s[:start]+'''export const API_PROVIDERS: ApiProviderConfig[] = [{
  id:'BINANCE', name:'Binance Global 现货公开行情', apiKey:'无需密钥',
  status:'active', latencyMs:null, description:'同一币安现货市场；实时延迟需测量，断流显示未知。', isPrimary:true,
}];

'''+s[end:]
start=s.index('    // 2. Fallback to Finnhub')
end=s.index('    return this.currentTickers[symbol] || null;',start)
s=s[:start]+'    // No cross-venue or fabricated fallback.\n'+s[end:]
s=s.replace("      'https://api.binance.us/api/v3',\n",'').replace("      '/api/binance',\n",'')
s=s.replace("          lastUpdate: Date.now(),", "          lastUpdate: Number(data.closeTime) || 0,",1)
p.write_text(s,encoding='utf-8',newline='\n')
p=root/'src/types/crypto.ts';s=p.read_text(encoding='utf-8').replace('latencyMs: number;','latencyMs: number | null;');p.write_text(s,encoding='utf-8',newline='\n')
p=root/'src/components/views/RadarView.tsx';s=p.read_text(encoding='utf-8').replace("  const btc = tickers['BTCUSDT'];", "  const observed = tickers['BTCUSDT'];\n  const btc = observed && Date.now()-observed.lastUpdate <= 10000 ? observed : undefined;")
p.write_text(s,encoding='utf-8',newline='\n')
