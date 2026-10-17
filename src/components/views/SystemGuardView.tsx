import React, { useState, useEffect, useRef, useMemo } from 'react';
import {
  Server,
  Cpu,
  ShieldCheck,
  Bell,
  Terminal,
  ChevronDown,
  ChevronUp,
  Activity,
  Sliders,
  Sparkles,
  Zap,
  Volume2,
  Clock,
  Download,
  Copy,
  Check,
  AlertTriangle,
  HardDrive,
  RefreshCw,
  Coins,
  Gauge,
  RotateCcw,
} from 'lucide-react';
import { ScannerConfig, MacroTrendAnalysis } from '../../types/crypto';
import { GuardLabDrawer } from '../HorizonPanels';
import { strategySettings, families } from '../../services/strategySettings';
import { soundService } from '../../services/soundService';
import { ServerConnectionPanel } from '../ServerConnectionPanel';
import { PositionMonitor } from '../PositionMonitor';
import {
  PYTHON_DAEMON_SCRIPT,
  SYSTEMD_SERVICE_FILE,
  UBUNTU_DEPLOY_GUIDE,
} from '../../services/exportService';

interface SystemGuardViewProps {
  config: ScannerConfig;
  macroTrend: MacroTrendAnalysis;
  onUpdateConfig: (newConfig: Partial<ScannerConfig>) => void;
  onRequestNotificationPermission: () => void;
  hasNotificationPermission: boolean;
}

const INTERVAL_PRESETS = [
  { label: '2秒 (超高频)', ms: 2000 },
  { label: '5秒 (标准)', ms: 5000 },
  { label: '10秒', ms: 10000 },
  { label: '1分钟', ms: 60000 },
  { label: '5分钟', ms: 300000 },
];

interface StrategyDef {
  key: 'BURST_BREAKOUT' | 'FLASH_CRASH_REBOUND' | 'RANGE_OSCILLATION';
  nameZh: string;
  nameEn: string;
  tag: string;
  tagBg: string;
  tagText: string;
  description: string;
  quantFormula: string;
}

const STRATEGIES: StrategyDef[] = [
  {
    key: 'BURST_BREAKOUT',
    nameZh: '放量起爆追高模型',
    nameEn: 'Burst Breakout',
    tag: '顺势起爆',
    tagBg: 'bg-[#3d3005]',
    tagText: 'text-[#fdd663]',
    description: '已收盘5m/15m突破；有效区间内入场，最近已确认阻力净空间≥0.40%，无阻力参考不交易；TP1减50%，余仓TP2。',
    quantFormula: 'Close > PriorHigh · Volume ≥ 1.08× · TakerBuy ≥ 48% · UpperWick ≤ 45%',
  },
  {
    key: 'FLASH_CRASH_REBOUND',
    nameZh: '暴跌抄底反弹模块',
    nameEn: 'Flash Crash Rebound',
    tag: '稳健超跌',
    tagBg: 'bg-[#122824]',
    tagText: 'text-[#4db6ac]',
    description: '累计跌幅≥5%且近1小时先高后低跌幅≥3%，通过瀑布和止跌过滤；最近阻力扣成本后不足1%则跳过。',
    quantFormula: '急跌 + 右侧止跌/背离确认 · 净空间≥1% · TP1减70% · 余仓TP2/失效退出',
  },
  {
    key: 'RANGE_OSCILLATION',
    nameZh: '区间震荡获利模块',
    nameEn: 'Range Oscillation',
    tag: '箱体低吸',
    tagBg: 'bg-[#232834]',
    tagText: 'text-[#c4c7c5]',
    description: '15m稳定箱体下沿低吸，上下沿重复测试并通过五类止跌过滤；最近阻力净空间不足1%则跳过。',
    quantFormula: '稳定箱体 + 五类止跌过滤 · 净空间≥1% · TP1全出 · 破箱/止损退出',
  },
];

export const SystemGuardView: React.FC<SystemGuardViewProps> = ({
  config,
  macroTrend,
  onUpdateConfig: updateLocal,
  onRequestNotificationPermission,
  hasNotificationPermission,
}) => {
  // Accordion drawer open/close states
  const [openDrawers, setOpenDrawers] = useState<Record<string, boolean>>({
    server: true, // Default open for server check
    strategies: false,
    positions: false,
    audio: false,
    deploy: false,
  });

  const toggleDrawer = (id: string) => {
    setOpenDrawers((prev) => ({ ...prev, [id]: !prev[id] }));
  };

  // Cloud strategy settings state
  const [cloud, setCloud] = useState('正在读取云端配置…');
  const revision = useRef<number | null>(null);
  const saving = useRef(false);

  useEffect(() => {
    let live = true;
    const refresh = async () => {
      if (saving.current) return;
      try {
        const v = await strategySettings();
        if (live) {
          revision.current = v.revision;
          updateLocal({
            activeStrategies: {
              ...config.activeStrategies,
              ...v.activeStrategies,
            } as ScannerConfig['activeStrategies'],
          });
          setCloud(`云端已同步 · 版本 ${v.revision}`);
        }
      } catch (e) {
        if (live) setCloud(String(e));
      }
    };
    void refresh();
    const timer = setInterval(refresh, 15000);
    return () => {
      live = false;
      clearInterval(timer);
    };
  }, []);

  const handleUpdateStrategyConfig = (next: Partial<ScannerConfig>) => {
    if (!next.activeStrategies) {
      updateLocal(next);
      return;
    }
    if (saving.current || revision.current === null) {
      setCloud('请等待云端配置读取完成');
      return;
    }
    saving.current = true;
    setCloud('正在保存云端配置…');
    const activeStrategies = Object.fromEntries(
      families.map((k) => [k, !!next.activeStrategies![k as keyof typeof next.activeStrategies]])
    );
    void strategySettings({ revision: revision.current, activeStrategies })
      .then((v) => {
        revision.current = v.revision;
        updateLocal({
          activeStrategies: {
            ...config.activeStrategies,
            ...v.activeStrategies,
          } as ScannerConfig['activeStrategies'],
        });
        setCloud(`云端已生效 · 版本 ${v.revision}`);
      })
      .catch((e) => {
        setCloud(`保存失败：${String(e)}；请重试`);
      })
      .finally(() => {
        saving.current = false;
      });
  };

  const toggleStrategy = (key: keyof typeof config.activeStrategies) => {
    handleUpdateStrategyConfig({
      activeStrategies: {
        ...config.activeStrategies,
        [key]: !config.activeStrategies[key],
      },
    });
  };

  const activeCount = useMemo(() => {
    return STRATEGIES.filter((s) => config.activeStrategies[s.key]).length;
  }, [config.activeStrategies]);

  const [copiedKey, setCopiedKey] = useState<string | null>(null);
  const handleCopy = (text: string, key: string) => {
    navigator.clipboard.writeText(text);
    setCopiedKey(key);
    setTimeout(() => setCopiedKey(null), 2000);
  };

  const handleDownload = (filename: string, content: string) => {
    const blob = new Blob([content], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };

  return (
    <div className="space-y-3 pb-8 animate-fadeIn">
      <GuardLabDrawer market={macroTrend} />
      {/* 1. Global Overview Hero Card */}
      <div className="relative overflow-hidden rounded-2xl bg-gradient-to-br from-[#161a26] via-[#121520] to-[#0d1017] border border-gray-800 p-3.5 shadow-lg">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div className="p-2 rounded-xl bg-blue-500/15 text-blue-400 border border-blue-500/25">
              <Activity className="w-5 h-5" />
            </div>
            <div>
              <h1 className="text-sm font-bold text-white tracking-wide">系统与量化守护</h1>
              <p className="text-[10px] text-gray-400 mt-0.5">
                前后端双端连通 · 核心策略风控 · 持仓退出联动
              </p>
            </div>
          </div>
          <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-emerald-950/80 text-emerald-400 border border-emerald-500/30 font-medium">
            24/7 守护中
          </span>
        </div>

        {/* Quick Global Health Pills (4 Key Indicators at a glance) */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mt-3 pt-3 border-t border-gray-800/80 text-[11px]">
          <div className="p-2 rounded-xl bg-[#0d1017] border border-gray-800/60 flex items-center justify-between">
            <span className="text-gray-400 text-[10px]">云端节点</span>
            <span className="text-emerald-400 font-mono font-medium text-[10.5px]">43.163...</span>
          </div>
          <div className="p-2 rounded-xl bg-[#0d1017] border border-gray-800/60 flex items-center justify-between">
            <span className="text-gray-400 text-[10px]">策略激活</span>
            <span className="text-blue-400 font-mono font-medium text-[10.5px]">{activeCount}/3 类</span>
          </div>
          <div className="p-2 rounded-xl bg-[#0d1017] border border-gray-800/60 flex items-center justify-between">
            <span className="text-gray-400 text-[10px]">大盘大势</span>
            <span className="text-amber-400 font-mono font-medium text-[10.5px]">
              {macroTrend.dataReady ? macroTrend.regimeNameZh : '待更新'}
            </span>
          </div>
          <div className="p-2 rounded-xl bg-[#0d1017] border border-gray-800/60 flex items-center justify-between">
            <span className="text-gray-400 text-[10px]">设备通知</span>
            <span className={`font-mono font-medium text-[10.5px] ${hasNotificationPermission ? 'text-emerald-400' : 'text-amber-400'}`}>
              {hasNotificationPermission ? '已授权' : '待授权'}
            </span>
          </div>
        </div>
      </div>

      {/* 2. Accordion Drawer: 云端服务器连接与状态 (Server Connection) */}
      <div className="rounded-2xl border border-gray-800 bg-[#141824] overflow-hidden shadow-md">
        <button
          onClick={() => toggleDrawer('server')}
          className="w-full p-3.5 flex items-center justify-between text-left hover:bg-white/[0.02] transition"
        >
          <div className="flex items-center gap-2.5">
            <div className="p-1.5 rounded-lg bg-emerald-500/15 text-emerald-400">
              <Server className="w-4 h-4" />
            </div>
            <div>
              <span className="text-xs font-semibold text-white block">云端服务器连接与设备绑定</span>
              <span className="text-[10px] text-gray-400">东京节点 · HTTPS 私有鉴权通道</span>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-emerald-950/60 text-emerald-300 border border-emerald-700/40">
              43.163.203.127
            </span>
            {openDrawers.server ? (
              <ChevronUp className="w-4 h-4 text-gray-400" />
            ) : (
              <ChevronDown className="w-4 h-4 text-gray-400" />
            )}
          </div>
        </button>

        {openDrawers.server && (
          <div className="p-3 border-t border-gray-800 space-y-2.5 bg-[#10131d] animate-fadeIn">
            <ServerConnectionPanel />
          </div>
        )}
      </div>

      {/* 3. Accordion Drawer: BTC 量化买入策略模型 (Quant Strategy Models) */}
      <div className="rounded-2xl border border-gray-800 bg-[#141824] overflow-hidden shadow-md">
        <button
          onClick={() => toggleDrawer('strategies')}
          className="w-full p-3.5 flex items-center justify-between text-left hover:bg-white/[0.02] transition"
        >
          <div className="flex items-center gap-2.5">
            <div className="p-1.5 rounded-lg bg-blue-500/15 text-blue-400">
              <Cpu className="w-4 h-4" />
            </div>
            <div>
              <span className="text-xs font-semibold text-white block">BTC 量化买入策略模型</span>
              <span className="text-[10px] text-gray-400">{cloud}</span>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-blue-950/60 text-blue-300 border border-blue-700/40">
              已启用 {activeCount}/3
            </span>
            {openDrawers.strategies ? (
              <ChevronUp className="w-4 h-4 text-gray-400" />
            ) : (
              <ChevronDown className="w-4 h-4 text-gray-400" />
            )}
          </div>
        </button>

        {openDrawers.strategies && (
          <div className="p-3.5 border-t border-gray-800 space-y-3 bg-[#10131d] animate-fadeIn">
            {/* Quick Presets Ribbon */}
            <div className="flex items-center justify-between gap-1.5 text-xs">
              <button
                onClick={() => {
                  const allOn = { BURST_BREAKOUT: true, FLASH_CRASH_REBOUND: true, RANGE_OSCILLATION: true };
                  handleUpdateStrategyConfig({ activeStrategies: allOn as any });
                }}
                className="flex-1 py-1 px-2 rounded-lg bg-[#181d2a] hover:bg-gray-800 text-[10.5px] text-blue-300 border border-gray-700/80 text-center transition"
              >
                全部启用
              </button>
              <button
                onClick={() => {
                  const safeOn = { BURST_BREAKOUT: false, FLASH_CRASH_REBOUND: true, RANGE_OSCILLATION: true };
                  handleUpdateStrategyConfig({ activeStrategies: safeOn as any });
                }}
                className="flex-1 py-1 px-2 rounded-lg bg-[#181d2a] hover:bg-gray-800 text-[10.5px] text-emerald-300 border border-gray-700/80 text-center transition"
              >
                防守反弹
              </button>
              <button
                onClick={() => {
                  const burstOn = { BURST_BREAKOUT: true, FLASH_CRASH_REBOUND: false, RANGE_OSCILLATION: false };
                  handleUpdateStrategyConfig({ activeStrategies: burstOn as any });
                }}
                className="flex-1 py-1 px-2 rounded-lg bg-[#181d2a] hover:bg-gray-800 text-[10.5px] text-amber-300 border border-gray-700/80 text-center transition"
              >
                顺势起爆
              </button>
            </div>

            {/* Individual Strategy Cards */}
            <div className="space-y-2">
              {STRATEGIES.map((strat) => {
                const isEnabled = !!config.activeStrategies[strat.key];
                return (
                  <div
                    key={strat.key}
                    onClick={() => toggleStrategy(strat.key)}
                    className={`p-2.5 rounded-xl border transition-all cursor-pointer ${
                      isEnabled
                        ? 'bg-[#151a26] border-gray-700'
                        : 'bg-[#11141c] border-gray-800 opacity-60'
                    }`}
                  >
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <span className={`text-xs font-semibold ${isEnabled ? 'text-white' : 'text-gray-400'}`}>
                          {strat.nameZh}
                        </span>
                        <span className={`text-[9.5px] px-1.5 py-0.2 rounded font-medium ${strat.tagBg} ${strat.tagText}`}>
                          {strat.tag}
                        </span>
                      </div>

                      {/* Custom iOS/M3 Pill Toggle */}
                      <div
                        className={`w-9 h-5 rounded-full transition-colors p-0.5 flex items-center ${
                          isEnabled ? 'bg-blue-600 justify-end' : 'bg-gray-700 justify-start'
                        }`}
                      >
                        <div className="w-4 h-4 rounded-full bg-white shadow-sm" />
                      </div>
                    </div>

                    <p className="text-[10px] text-gray-400 mt-1 leading-relaxed">
                      {strat.description}
                    </p>

                    <div className="mt-1 text-[9px] font-mono text-gray-500 truncate">
                      模型: {strat.quantFormula}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </div>

      {/* 4. Accordion Drawer: 实际持仓退出联动监控 (Position Exit Monitor) */}
      <div className="rounded-2xl border border-gray-800 bg-[#141824] overflow-hidden shadow-md">
        <button
          onClick={() => toggleDrawer('positions')}
          className="w-full p-3.5 flex items-center justify-between text-left hover:bg-white/[0.02] transition"
        >
          <div className="flex items-center gap-2.5">
            <div className="p-1.5 rounded-lg bg-amber-500/15 text-amber-400">
              <ShieldCheck className="w-4 h-4" />
            </div>
            <div>
              <span className="text-xs font-semibold text-white block">实际持仓退出联动监控</span>
              <span className="text-[10px] text-gray-400">双向止盈止损推送 · 超时平仓观察</span>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-amber-950/60 text-amber-300 border border-amber-700/40">
              联动就绪
            </span>
            {openDrawers.positions ? (
              <ChevronUp className="w-4 h-4 text-gray-400" />
            ) : (
              <ChevronDown className="w-4 h-4 text-gray-400" />
            )}
          </div>
        </button>

        {openDrawers.positions && (
          <div className="p-3 border-t border-gray-800 space-y-2 bg-[#10131d] animate-fadeIn">
            <PositionMonitor />
          </div>
        )}
      </div>

      {/* 5. Accordion Drawer: 预警提示音与推送权限 (Audio & Notifications) */}
      <div className="rounded-2xl border border-gray-800 bg-[#141824] overflow-hidden shadow-md">
        <button
          onClick={() => toggleDrawer('audio')}
          className="w-full p-3.5 flex items-center justify-between text-left hover:bg-white/[0.02] transition"
        >
          <div className="flex items-center gap-2.5">
            <div className="p-1.5 rounded-lg bg-indigo-500/15 text-indigo-400">
              <Bell className="w-4 h-4" />
            </div>
            <div>
              <span className="text-xs font-semibold text-white block">预警提示音与刷新频率</span>
              <span className="text-[10px] text-gray-400">
                音频试听 · 系统权限 · 刷新间隔
              </span>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-indigo-950/60 text-indigo-300 border border-indigo-700/40">
              {config.scanIntervalMs / 1000}s
            </span>
            {openDrawers.audio ? (
              <ChevronUp className="w-4 h-4 text-gray-400" />
            ) : (
              <ChevronDown className="w-4 h-4 text-gray-400" />
            )}
          </div>
        </button>

        {openDrawers.audio && (
          <div className="p-3.5 border-t border-gray-800 space-y-3 bg-[#10131d] text-xs animate-fadeIn">
            {/* Audio test buttons */}
            <div>
              <span className="text-[11px] text-gray-400 block mb-1.5">预警提示音试听</span>
              <div className="grid grid-cols-2 gap-2">
                <button
                  onClick={() => soundService.playBuySignalChime()}
                  className="py-2 px-3 rounded-xl bg-emerald-950/40 hover:bg-emerald-900/50 border border-emerald-700/50 text-emerald-300 font-medium text-xs flex items-center justify-center gap-1.5 transition active:scale-95"
                >
                  <Zap className="w-3.5 h-3.5" />
                  <span>试听买入提示音</span>
                </button>
                <button
                  onClick={() => soundService.playRiskAlertChime()}
                  className="py-2 px-3 rounded-xl bg-rose-950/40 hover:bg-rose-900/50 border border-rose-700/50 text-rose-300 font-medium text-xs flex items-center justify-center gap-1.5 transition active:scale-95"
                >
                  <ShieldCheck className="w-3.5 h-3.5" />
                  <span>试听止损提示音</span>
                </button>
              </div>
            </div>

            {/* Notification permission button */}
            {!hasNotificationPermission && (
              <button
                onClick={onRequestNotificationPermission}
                className="w-full py-2 px-3 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white font-medium text-xs flex items-center justify-center gap-1.5 transition"
              >
                <Bell className="w-3.5 h-3.5" />
                <span>开启 Android 系统后台推送通知权限</span>
              </button>
            )}

            {/* Scan interval selector */}
            <div>
              <span className="text-[11px] text-gray-400 block mb-1.5">本地行情刷新间隔</span>
              <div className="grid grid-cols-3 sm:grid-cols-5 gap-1.5">
                {INTERVAL_PRESETS.map((p) => {
                  const isSelected = config.scanIntervalMs === p.ms;
                  return (
                    <button
                      key={p.ms}
                      onClick={() => updateLocal({ scanIntervalMs: p.ms })}
                      className={`py-1.5 px-2 rounded-xl text-[10.5px] font-mono transition text-center ${
                        isSelected
                          ? 'bg-blue-900/60 text-blue-300 border border-blue-500 font-bold'
                          : 'bg-[#151924] text-gray-400 hover:text-white border border-gray-800'
                      }`}
                    >
                      {p.label}
                    </button>
                  );
                })}
              </div>
            </div>
          </div>
        )}
      </div>

      {/* 6. Accordion Drawer: 生产基础设施与脚本部署 (Infrastructure & Scripts) */}
      <div className="rounded-2xl border border-gray-800 bg-[#141824] overflow-hidden shadow-md">
        <button
          onClick={() => toggleDrawer('deploy')}
          className="w-full p-3.5 flex items-center justify-between text-left hover:bg-white/[0.02] transition"
        >
          <div className="flex items-center gap-2.5">
            <div className="p-1.5 rounded-lg bg-purple-500/15 text-purple-400">
              <Terminal className="w-4 h-4" />
            </div>
            <div>
              <span className="text-xs font-semibold text-white block">云端生产环境与脚本部署</span>
              <span className="text-[10px] text-gray-400">Ubuntu 26.04LTS · Systemd 守护运行</span>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-purple-950/60 text-purple-300 border border-purple-700/40">
              部署指引
            </span>
            {openDrawers.deploy ? (
              <ChevronUp className="w-4 h-4 text-gray-400" />
            ) : (
              <ChevronDown className="w-4 h-4 text-gray-400" />
            )}
          </div>
        </button>

        {openDrawers.deploy && (
          <div className="p-3.5 border-t border-gray-800 space-y-3 bg-[#10131d] text-xs animate-fadeIn">
            {/* Server specs quick table */}
            <div className="p-2.5 rounded-xl bg-[#141824] border border-gray-800 text-[11px] font-mono space-y-1">
              <div className="flex justify-between">
                <span className="text-gray-400">主机 IP:</span>
                <span className="text-amber-300">43.163.203.127 (腾讯云东京)</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-400">守护服务:</span>
                <span className="text-emerald-400">shotcrypto.service (7线程)</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-400">脚本路径:</span>
                <span className="text-gray-300 truncate max-w-[200px]">/opt/shotcrypto/scanner_daemon.py</span>
              </div>
            </div>

            {/* Quick Export/Download actions */}
            <div className="grid grid-cols-2 gap-2">
              <button
                onClick={() => handleDownload('shot-crypto.service', SYSTEMD_SERVICE_FILE)}
                className="py-2 px-2.5 rounded-xl bg-[#181d2a] hover:bg-gray-800 border border-gray-700 text-gray-300 font-medium text-[11px] flex items-center justify-center gap-1.5 transition"
              >
                <Download className="w-3.5 h-3.5" />
                <span>下载 Systemd 服务配置</span>
              </button>
              <button
                onClick={() => handleDownload('UBUNTU_DEPLOY_GUIDE.md', UBUNTU_DEPLOY_GUIDE)}
                className="py-2 px-2.5 rounded-xl bg-[#181d2a] hover:bg-gray-800 border border-gray-700 text-gray-300 font-medium text-[11px] flex items-center justify-center gap-1.5 transition"
              >
                <Download className="w-3.5 h-3.5" />
                <span>下载部署指引文档</span>
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
