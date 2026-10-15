"""Local one-time wiring edits; no remote access."""
from pathlib import Path
root = Path(__file__).resolve().parents[1]
def edit(name, transform):
    p=root/name
    p.write_text(transform(p.read_text(encoding='utf-8')),encoding='utf-8',newline='\n')

# Patch where the dependency now lives; the assertions remain unchanged.
edit('tests/test_trade_rules.py', lambda s:s.replace("patch.object(m,'", "patch.object(strategy_module,'"))

# Quarantine the unused local strategy implementation outside the application bundle.
old=root/'src/services/quantEngine.ts'
target=root/'tests/legacy/quantEngine.v112.ts'
target.parent.mkdir(exist_ok=True)
target.write_text(old.read_text(encoding='utf-8').replace("'../types/crypto'", "'../../src/types/crypto'"),encoding='utf-8',newline='\n')
old.unlink()
edit('tests/quantEngine.test.ts',lambda s:s.replace("'../src/services/quantEngine'","'./legacy/quantEngine.v112'"))

def app(s):
    s=s.replace("import { QuantEngine } from './services/quantEngine';", "import { fetchMarketState, unknownMarket } from './services/marketState';")
    start=s.index('  // Core Quantitative Scanner Cycle')
    end=s.index('  // Subscribe to Binance Stream',start)
    s=s[:start]+'''  // Only the server snapshot describes strategy state. A local price is not server health.
  useEffect(() => {
    let disposed = false;
    let busy = false;
    const refresh = async () => {
      if (busy) return;
      busy = true;
      try {
        const state = await fetchMarketState();
        if (!disposed) setMacroTrend(state);
      } catch { if (!disposed) setMacroTrend(unknownMarket()); }
      finally { busy = false; }
    };
    void refresh();
    const timer = window.setInterval(() => void refresh(), 3000);
    return () => { disposed = true; window.clearInterval(timer); };
  }, []);

'''+s[end:]
    s=s.replace('      runScanner(updatedTickers);','').replace('[config.scanIntervalMs, runScanner]','[config.scanIntervalMs]')
    return s
edit('src/App.tsx',app)

def radar(s):
    start=s.index('      {/* 2. Dynamic Volatility')
    end=s.index('      {/* 4. Live BTC',start)
    s=s[:start]+'''      <div className="p-4 rounded-2xl bg-[#1c2029] border border-[#2b313f] space-y-2" role="status">
        <h2 className="font-semibold">{macroTrend.regimeNameZh}</h2>
        <p className="text-sm text-gray-300">{macroTrend.regimeDescription}</p>
        <p className="text-xs text-gray-400">{macroTrend.biasZh}</p>
        {macroTrend.dataReady && <p className="text-xs">1h RSI：{macroTrend.hourlyRsi.toFixed(2)} · MA20：{formatPrice(macroTrend.hourlyMa20)}</p>}
        <p className="text-xs text-gray-400">具体入场与止盈止损只看有效候选；行情状态不是买入指令。</p>
      </div>

'''+s[end:]
    return s.replace('{scanIntervalSec}s 频次','行情刷新 {scanIntervalSec}s').replace("import { TrendStrengthIndicator } from '../TrendStrengthIndicator';",'')
edit('src/components/views/RadarView.tsx',radar)

edit('src/services/modelLibrary.ts',lambda s:s.replace("const LIBRARY_URL = 'http://43.163.203.127:8788';\nconst LIBRARY_TOKEN = 'cg-ml-7f3a9c2e';", "import { connection } from './serverConnection';").replace('${LIBRARY_URL}','${connection().url}').replace('LIBRARY_TOKEN','connection().token'))
edit('src/services/exportService.ts',lambda s:s.replace("import daemonSource from '../../scratch/remote_scanner_daemon.py?raw';", "const daemonSource = '# 服务端已模块化。请使用仓库完整部署包，不能只复制单个脚本。';").replace('部署时上传 scratch/remote_scanner_daemon.py，不要使用仍写着其他币种的旧脚本。','部署必须包含 scratch/cryptog、requirements.txt 和入口脚本；配置 TLS 与独立设备凭据。参阅阶段一交付文档。'))
edit('src/components/views/ServerDaemonView.tsx',lambda s:s.replace('进程永不中断','连接与推送状态需要实际监测').replace("import React, { useState } from 'react';", "import React, { useState } from 'react';\nimport { ServerConnectionPanel } from '../ServerConnectionPanel';").replace('<div className="space-y-3 pb-20">','<div className="space-y-3 pb-20">\n      <ServerConnectionPanel />'))
