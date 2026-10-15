import {strategySettings,families} from '../../services/strategySettings';
import React, { useMemo,useEffect,useRef,useState } from 'react';
import { ScannerConfig, MacroTrendAnalysis } from '../../types/crypto';
import { API_PROVIDERS } from '../../services/binanceService';
import { soundService } from '../../services/soundService';
import {
  Cpu,
  Clock,
  Volume2,
  Bell,
  AlertTriangle,
  Zap,
  Layers,
  Database,
  ShieldCheck,
  Check,
  Sliders,
  Sparkles,
  Shield,
  TrendingUp,
  Activity,
  ArrowDownRight,
  RotateCcw,
  Gauge,
  Radio,
  CheckCircle2,
  XCircle,
  Coins,
} from 'lucide-react';

interface StrategyEngineViewProps {
  config: ScannerConfig;
  macroTrend: MacroTrendAnalysis;
  onUpdateConfig: (newConfig: Partial<ScannerConfig>) => void;
  onRequestNotificationPermission: () => void;
  hasNotificationPermission: boolean;
}

const INTERVAL_PRESETS = [
  { label: '2秒 (超高频)', ms: 2000 },
  { label: '5秒', ms: 5000 },
  { label: '10秒', ms: 10000 },
  { label: '1分钟', ms: 60000 },
  { label: '3分钟', ms: 180000 },
  { label: '5分钟', ms: 300000 },
  { label: '10分钟', ms: 600000 },
  { label: '30分钟', ms: 1800000 },
  { label: '1小时', ms: 3600000 },
];

interface StrategyDef {
  key: keyof ScannerConfig['activeStrategies'];
  nameZh: string;
  nameEn: string;
  tag: string;
  tagBg: string;
  tagText: string;
  winRate: string;
  ruleScoreRange: string;
  frequencyTag: '高频触发' | '中频捕捉' | '低频条件';
  description: string;
  quantFormula: string;
  getMacroCompatibility: (macro: MacroTrendAnalysis) => {
    status: 'ACTIVE' | 'PROTECTED' | 'GATED';
    badge: string;
    badgeBg: string;
    badgeText: string;
  };
}

const STRATEGY_DEFINITIONS: StrategyDef[] = [
  {
    key: 'BURST_BREAKOUT',
    nameZh: '放量起爆追高模型',
    nameEn: 'Burst Breakout',
    tag: '顺势起爆',
    tagBg: 'bg-[#3d3005]',
    tagText: 'text-[#fdd663]',
    winRate: '历史胜率：未验证',
    ruleScoreRange: '按实际信号计算',
    frequencyTag: '高频触发',
    description: '已收盘5m/15m突破；有效区间内入场，最近已确认阻力净空间≥0.40%，无阻力参考不交易；TP1减50%，余仓TP2，最长4小时。',
    quantFormula: 'Close > PriorHigh · Volume ≥ 1.08× · TakerBuy ≥ 48% · UpperWick ≤ 45% · 限时价格复核',
    getMacroCompatibility: (macro) => {
      if (macro.hourlyTrend === 'BEARISH') {
        return {
          status: 'GATED',
          badge: '大盘空头锁定拦截',
          badgeBg: 'bg-[#331818]',
          badgeText: 'text-[#f28b82]',
        };
      }
      return {
        status: 'ACTIVE',
        badge: '多头大势允许顺势起爆',
        badgeBg: 'bg-[#143820]',
        badgeText: 'text-[#81c995]',
      };
    },
  },
  {
    key: 'TREND_PULLBACK_BUY',
    nameZh: '顺势回踩企稳模块',
    nameEn: 'Trend Pullback Bounce',
    tag: '高盈亏比',
    tagBg: 'bg-[#143820]',
    tagText: 'text-[#81c995]',
    winRate: '历史胜率：未验证',
    ruleScoreRange: '按实际信号计算',
    frequencyTag: '中频捕捉',
    description: '顺大势主升浪中，缩量回踩 EMA20/VWAP 机构成本线企稳收阳并获大单护盘，盈亏比极高。',
    quantFormula: 'Price near SMA20/VWAP & RSI 38-54 & Imbalance > +3%',
    getMacroCompatibility: (macro) => {
      if (macro.hourlyTrend === 'BEARISH') {
        return {
          status: 'GATED',
          badge: '空头下行禁止回踩抄底',
          badgeBg: 'bg-[#331818]',
          badgeText: 'text-[#f28b82]',
        };
      }
      return {
        status: 'ACTIVE',
        badge: '多头主升浪极优买点',
        badgeBg: 'bg-[#143820]',
        badgeText: 'text-[#81c995]',
      };
    },
  },
  {
    key: 'FLASH_CRASH_REBOUND',
    nameZh: '暴跌抄底反弹模块',
    nameEn: 'Flash Crash Rebound',
    tag: '稳健超跌',
    tagBg: 'bg-[#122824]',
    tagText: 'text-[#4db6ac]',
    winRate: '历史胜率：未验证',
    ruleScoreRange: '按实际信号计算',
    frequencyTag: '中频捕捉',
    description: '累计跌幅≥5%且近1小时先高后低跌幅≥3%，通过瀑布和止跌过滤；最近阻力扣成本后不足1%则跳过，最长90分钟。',
    quantFormula: '急跌 + 右侧止跌/背离确认 · 净空间≥1% · TP1减70% · 余仓TP2/失效/90分钟退出',
    getMacroCompatibility: (macro) => {
      if (macro.hourlyTrend === 'BEARISH') {
        return {
          status: 'PROTECTED',
          badge: '空头下行 · 强制跌幅 ≥ 5% 抄底确认',
          badgeBg: 'bg-[#332210]',
          badgeText: 'text-[#fdd663]',
        };
      }
      return {
        status: 'ACTIVE',
        badge: '超跌均值回归可用',
        badgeBg: 'bg-[#143820]',
        badgeText: 'text-[#81c995]',
      };
    },
  },
  {
    key: 'RSI_DIVERGENCE',
    nameZh: 'RSI 底背离反弹模型',
    nameEn: 'RSI Bullish Divergence',
    tag: 'Trend-Aligned',
    tagBg: 'bg-[#1a3258]',
    tagText: 'text-[#8ab4f8]',
    winRate: '历史胜率：未验证',
    ruleScoreRange: '按实际信号计算',
    frequencyTag: '低频条件',
    description: '价格创出新低而 RSI 逆势抬高。在空头下行态强制要求标的高位累计跌幅 ≥ 5% 并收右侧阳线企稳确认。',
    quantFormula: 'Price Low2 ≤ Low1 & RSI Low2 ≥ Low1 + 1.0 (空头需标的累计跌幅 ≥ 5%)',
    getMacroCompatibility: (macro) => {
      if (macro.hourlyTrend === 'BEARISH') {
        return {
          status: 'PROTECTED',
          badge: '空头下行 · 强制跌幅 ≥ 5% 底背离确认',
          badgeBg: 'bg-[#1a3258]',
          badgeText: 'text-[#8ab4f8]',
        };
      }
      return {
        status: 'ACTIVE',
        badge: '标准底背离放行',
        badgeBg: 'bg-[#143820]',
        badgeText: 'text-[#81c995]',
      };
    },
  },
  {
    key: 'VWAP_MEAN_REVERSION',
    nameZh: '机构 VWAP 均值回归',
    nameEn: 'VWAP Mean Reversion',
    tag: '≥ 1.5 ATR',
    tagBg: 'bg-[#1a3258]',
    tagText: 'text-[#8ab4f8]',
    winRate: '历史胜率：未验证',
    ruleScoreRange: '按实际信号计算',
    frequencyTag: '中频捕捉',
    description: 'VWAP-Volatility Spread 过滤：现价脱离 1m VWAP 达到 ≥ 1.5 ATR 极度拉伸，捕捉高概率均值抽回。',
    quantFormula: '(1m VWAP - Price) / ATR14 ≥ 1.5 & OrderBook Imbalance > +2%',
    getMacroCompatibility: (macro) => {
      if (macro.isStronglyBearish) {
        return {
          status: 'GATED',
          badge: '强空头主跌防套过滤',
          badgeBg: 'bg-[#331818]',
          badgeText: 'text-[#f28b82]',
        };
      }
      return {
        status: 'ACTIVE',
        badge: '极值价差抽回放行',
        badgeBg: 'bg-[#143820]',
        badgeText: 'text-[#81c995]',
      };
    },
  },
  {
    key: 'RANGE_OSCILLATION',
    nameZh: '区间震荡获利模块',
    nameEn: 'Range Oscillation',
    tag: '箱体低吸',
    tagBg: 'bg-[#232834]',
    tagText: 'text-[#c4c7c5]',
    winRate: '历史胜率：未验证',
    ruleScoreRange: '按实际信号计算',
    frequencyTag: '高频触发',
    description: '15m稳定箱体下沿低吸，上下沿重复测试并通过五类止跌过滤；最近阻力净空间不足1%则跳过，最长4小时。',
    quantFormula: '稳定箱体 + 五类止跌过滤 · 净空间≥1% · TP1全出 · 破箱/止损/4小时退出',
    getMacroCompatibility: (macro) => {
      if (macro.hourlyTrend === 'BEARISH') {
        return {
          status: 'GATED',
          badge: '空头大势压制下轨破位',
          badgeBg: 'bg-[#331818]',
          badgeText: 'text-[#f28b82]',
        };
      }
      return {
        status: 'ACTIVE',
        badge: '震荡箱体买点',
        badgeBg: 'bg-[#143820]',
        badgeText: 'text-[#81c995]',
      };
    },
  },
  {
    key: 'VOLATILITY_MOMENTUM',
    nameZh: '波动调整动量模型',
    nameEn: 'Volatility Momentum',
    tag: '动量冲锋',
    tagBg: 'bg-[#232834]',
    tagText: 'text-[#c4c7c5]',
    winRate: '历史胜率：未验证',
    ruleScoreRange: '按实际信号计算',
    frequencyTag: '高频触发',
    description: '标准化波动率收益 Z-Score ≥ 1.8σ，捕捉大单资金持续推动的短线急剧加速动量段。',
    quantFormula: 'Returns10 / Normalized StdDev ≥ +1.8σ',
    getMacroCompatibility: (macro) => {
      if (macro.hourlyTrend === 'BEARISH') {
        return {
          status: 'GATED',
          badge: '空头下行禁用逆势追多',
          badgeBg: 'bg-[#331818]',
          badgeText: 'text-[#f28b82]',
        };
      }
      return {
        status: 'ACTIVE',
        badge: '多头动量顺势冲锋',
        badgeBg: 'bg-[#143820]',
        badgeText: 'text-[#81c995]',
      };
    },
  },
];

// Material 3 Switch Component with smooth thumb transition & haptic touch target
const M3Switch: React.FC<{
  checked: boolean;
  onChange: () => void;
  ariaLabel: string;
}> = ({ checked, onChange, ariaLabel }) => {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={ariaLabel}
      onClick={(e) => {
        e.stopPropagation();
        onChange();
      }}
      className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full p-0.5 transition-colors duration-200 ease-in-out focus:outline-none focus-visible:ring-2 focus-visible:ring-[#8ab4f8] ${
        checked ? 'bg-[#8ab4f8]' : 'bg-[#2d313a]'
      }`}
    >
      <span
        className={`pointer-events-none flex h-5 w-5 transform items-center justify-center rounded-full shadow-md transition duration-200 ease-in-out ${
          checked
            ? 'translate-x-5 bg-[#041e49] text-[#8ab4f8]'
            : 'translate-x-0 bg-[#8e9196] text-transparent'
        }`}
      >
        {checked && <Check className="w-3 h-3 stroke-[3]" />}
      </span>
    </button>
  );
};

const ACTIVE_MODELS = STRATEGY_DEFINITIONS.filter(s => ['BURST_BREAKOUT', 'FLASH_CRASH_REBOUND', 'RANGE_OSCILLATION'].includes(s.key));

export const StrategyEngineView: React.FC<StrategyEngineViewProps> = ({
  config,
  macroTrend,
  onUpdateConfig: updateLocal,
  onRequestNotificationPermission,
  hasNotificationPermission,
}) => {
  const [cloud,setCloud]=useState('正在读取云端配置');const revision=useRef<number|null>(null);const saving=useRef(false);
  useEffect(()=>{let live=true;const refresh=async()=>{if(saving.current)return;try{const v=await strategySettings();if(live){revision.current=v.revision;updateLocal({activeStrategies:{...config.activeStrategies,...v.activeStrategies} as ScannerConfig['activeStrategies']});setCloud(`云端已同步 · 版本 ${v.revision}`);}}catch(e){if(live)setCloud(String(e));}};void refresh();const timer=setInterval(refresh,15000);return()=>{live=false;clearInterval(timer);};},[]);
  const onUpdateConfig=(next:Partial<ScannerConfig>)=>{
   if(!next.activeStrategies){updateLocal(next);return;}
   if(saving.current||revision.current===null){setCloud('请等待云端配置读取完成');return;}
   saving.current=true;setCloud('正在保存云端配置…');
   const activeStrategies=Object.fromEntries(families.map(k=>[k,!!next.activeStrategies![k as keyof typeof next.activeStrategies]]));
   void strategySettings({revision:revision.current,activeStrategies}).then(v=>{revision.current=v.revision;updateLocal({activeStrategies:{...config.activeStrategies,...v.activeStrategies} as ScannerConfig['activeStrategies']});setCloud(`云端已生效 · 版本 ${v.revision}`);}).catch(e=>{setCloud(`保存失败：${String(e)}；请等待刷新后重试`);}).finally(()=>{saving.current=false;});
  };
  const toggleStrategy = (key: keyof typeof config.activeStrategies) => {
    onUpdateConfig({
      activeStrategies: {
        ...config.activeStrategies,
        [key]: !config.activeStrategies[key],
      },
    });
  };

  const isBearish = macroTrend.hourlyTrend === 'BEARISH';

  // Strategy count & scan depth metrics
  const activeCount = useMemo(() => {
    return ACTIVE_MODELS.filter(s => config.activeStrategies[s.key]).length;
  }, [config.activeStrategies]);

  const totalCount = ACTIVE_MODELS.length;
  const depthPercentage = Math.round((activeCount / totalCount) * 100);

  const frequencyEstimate = '暂无实测统计';

  // Depth description text
  const depthModeLabel = useMemo(() => {
    if (activeCount === 7) return { title: '全谱深度扫描 (Deep Scan)', color: 'text-[#8ab4f8]' };
    if (activeCount >= 4) return { title: '平衡精选模式 (Balanced)', color: 'text-[#81c995]' };
    if (activeCount >= 1) return { title: `${activeCount} 类策略已选择`, color: 'text-[#fdd663]' };
    return { title: '已暂停全部策略 (Paused)', color: 'text-[#f28b82]' };
  }, [activeCount]);

  // Preset Handlers
  const handleEnableAll = () => {
    const allOn: Record<string, boolean> = {};
    STRATEGY_DEFINITIONS.forEach((s) => {
      allOn[s.key] = ACTIVE_MODELS.some(model => model.key === s.key);
    });
    onUpdateConfig({
      activeStrategies: allOn as any,
    });
  };

  const handleConservativePreset = () => {
    // Only high win-rate reversal & mean reversion
    onUpdateConfig({
      activeStrategies: {
        FLASH_CRASH_REBOUND: true,
        RSI_DIVERGENCE: false,
        VWAP_MEAN_REVERSION: false,
        BURST_BREAKOUT: false,
        TREND_PULLBACK_BUY: false,
        RANGE_OSCILLATION: true,
        VOLATILITY_MOMENTUM: false,
      },
    });
  };

  const handleTrendFollowingPreset = () => {
    // Trend following & breakout
    onUpdateConfig({
      activeStrategies: {
        BURST_BREAKOUT: true,
        TREND_PULLBACK_BUY: false,
        VOLATILITY_MOMENTUM: false,
        RSI_DIVERGENCE: false,
        FLASH_CRASH_REBOUND: false,
        VWAP_MEAN_REVERSION: false,
        RANGE_OSCILLATION: false,
      },
    });
  };

  const handleResetRecommended = () => {
    // Recommended default all-active
    handleEnableAll();
  };

  return (
    <div className="space-y-3 pb-20">
      {/* Header */}
      <div className="px-1">
        <h2 className="text-sm font-semibold text-white flex items-center gap-1.5">
          <Cpu className="w-4 h-4 text-[#8ab4f8]" />
          <span>量化分析引擎与大趋势过滤网</span>
        </h2>
        <p className="text-[10px] text-[#9aa0a6] mt-0.5">
          云端负责生成买入候选；两台手机共享云端策略开关
        </p>
      </div>

      {/* Macro Trend Gating Status Card */}
      <div
        className={`p-3 rounded-2xl border ${
          isBearish ? 'bg-[#1e1517] border-[#4f2328]' : 'bg-[#121c16] border-[#1f4028]'
        }`}
      >
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <AlertTriangle
              className={`w-4 h-4 ${isBearish ? 'text-[#f28b82]' : 'text-[#81c995]'}`}
            />
            <span className="text-xs font-semibold text-white">大周期趋势过滤门阀</span>
          </div>
          <span
            className={`text-[10px] font-mono px-2 py-0.5 rounded-full ${
              isBearish ? 'bg-[#441717] text-[#f28b82]' : 'bg-[#143820] text-[#81c995]'
            }`}
          >
            {macroTrend.dataReady === false ? '等待行情' : macroTrend.regimeNameZh}
          </span>
        </div>
        <p className="text-[11px] text-[#c4c7c5] mt-1.5 leading-relaxed">
          {macroTrend.dataReady === false ? '尚未取得足够行情，暂不判断方向。' : '本地行情状态仅供观察。实际准入以云端信号及打开时的价格复核为准。'}
        </p>
      </div>

      {/* 1. NEW DEDICATED SECTION: Individual Signal Strategy Switches & Scan Depth Customization */}
      <div className="p-3.5 rounded-2xl bg-[#1c2029] border border-[#2b313f] space-y-3">
        {/* Section Title & Live Status */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1.5">
            <Sliders className="w-4 h-4 text-[#8ab4f8]" />
            <h3 className="text-xs font-semibold text-white">云端策略开关</h3>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="text-[10px] font-mono text-[#8ab4f8] bg-[#1a3258] px-2 py-0.5 rounded-full border border-[#3b6bb0]/50">
              已选 {activeCount}/{totalCount}
            </span>
          </div>
        </div>

        <p className="text-[11px] text-[#9aa0a6] leading-relaxed">
          {cloud}。开关控制对应策略族的新入场及推送；关闭不停止已有持仓退出管理。观察提醒独立运行。
        </p>

        {/* Dynamic Scan Depth & Signal Frequency Impact Panel */}
        <div className="p-2.5 rounded-xl bg-[#14171f] border border-[#232834] space-y-2">
          <div className="flex items-center justify-between text-[11px]">
            <span className="text-[#9aa0a6] flex items-center gap-1">
              <Gauge className="w-3.5 h-3.5 text-[#8ab4f8]" />
              <span>启用策略:</span>
              <strong className={depthModeLabel.color}>{depthModeLabel.title}</strong>
            </span>
            <span className="font-mono text-white text-[10px] font-semibold">
              {depthPercentage}%
            </span>
          </div>

          {/* Depth Visual Bar */}
          <div className="w-full h-1.5 bg-[#232834] rounded-full overflow-hidden">
            <div
              className={`h-full transition-all duration-300 rounded-full ${
                activeCount >= 6
                  ? 'bg-gradient-to-r from-[#1a73e8] to-[#8ab4f8]'
                  : activeCount >= 3
                  ? 'bg-gradient-to-r from-[#1b5e20] to-[#81c995]'
                  : activeCount > 0
                  ? 'bg-gradient-to-r from-[#e37400] to-[#fdd663]'
                  : 'bg-[#5f6368]'
              }`}
              style={{ width: `${depthPercentage}%` }}
            />
          </div>

          {/* Signal Frequency & Win Rate Impact Row */}
          <div className="grid grid-cols-2 gap-2 pt-1">
            <div className="p-1.5 rounded-lg bg-[#1a1e28] border border-[#2a2f3e] flex items-center justify-between">
              <div className="text-[9px] text-[#9aa0a6]">实际信号频次</div>
              <div className="text-[10px] font-mono text-[#81c995] font-medium">
                {frequencyEstimate}
              </div>
            </div>
            <div className="p-1.5 rounded-lg bg-[#1a1e28] border border-[#2a2f3e] flex items-center justify-between">
              <div className="text-[9px] text-[#9aa0a6]">综合回测胜率</div>
              <div className="text-[10px] font-mono text-[#8ab4f8] font-medium">
                {'未验证'}
              </div>
            </div>
          </div>

          {/* Quick Preset Buttons */}
          <div className="pt-1">
            <div className="text-[9px] text-[#9aa0a6] mb-1 flex items-center gap-1">
              <Sparkles className="w-3 h-3 text-[#fdd663]" />
              <span>快速策略组合预设:</span>
            </div>
            <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-4">
              <button
                type="button"
                onClick={handleEnableAll}
                className="py-1 px-2 rounded-lg bg-[#171a21] hover:bg-[#202532] border border-[#282d38] text-[10px] text-[#8ab4f8] font-medium transition-colors text-center"
              >
                全部启用 (全深)
              </button>
              <button
                type="button"
                onClick={handleConservativePreset}
                className="py-1 px-2 rounded-lg bg-[#171a21] hover:bg-[#202532] border border-[#282d38] text-[10px] text-[#81c995] font-medium transition-colors text-center"
              >
                保守组合 (待验证)
              </button>
              <button
                type="button"
                onClick={handleTrendFollowingPreset}
                className="py-1 px-2 rounded-lg bg-[#171a21] hover:bg-[#202532] border border-[#282d38] text-[10px] text-[#fdd663] font-medium transition-colors text-center"
              >
                顺势突破 (攻击)
              </button>
              <button
                type="button"
                onClick={handleResetRecommended}
                className="py-1 px-2 rounded-lg bg-[#171a21] hover:bg-[#202532] border border-[#282d38] text-[10px] text-[#9aa0a6] hover:text-white font-medium transition-colors text-center flex items-center justify-center gap-1"
              >
                <RotateCcw className="w-2.5 h-2.5" />
                <span>重置默认</span>
              </button>
            </div>
          </div>
        </div>

        {/* Individual Strategy Toggle Cards */}
        <div className="space-y-2 pt-1">
          {ACTIVE_MODELS.map((strat) => {
            const isEnabled = !!config.activeStrategies[strat.key];
            const macroCompat = { status: 'GATED' as const, badge: '以云端实际信号为准', badgeBg: 'bg-[#232834]', badgeText: 'text-[#9aa0a6]' };

            return (
              <div
                key={strat.key}
                onClick={() => toggleStrategy(strat.key)}
                className={`p-3 rounded-xl border transition-all cursor-pointer ${
                  isEnabled
                    ? 'bg-[#171a21] border-[#2b313f] hover:border-[#3b4356]'
                    : 'bg-[#13151b] border-[#20242e] opacity-70 hover:opacity-90'
                }`}
              >
                <div className="flex items-start justify-between gap-2.5">
                  <div className="flex-1 min-w-0">
                    {/* Strategy Name & Tags */}
                    <div className="flex flex-wrap items-center gap-1.5">
                      <span
                        className={`text-xs font-semibold ${
                          isEnabled ? 'text-white' : 'text-[#9aa0a6]'
                        }`}
                      >
                        {strat.nameZh}
                      </span>
                      <span className="text-[10px] text-[#9aa0a6] font-mono">
                        ({strat.nameEn})
                      </span>
                      <span
                        className={`text-[9px] px-1.5 py-0.2 rounded font-medium ${strat.tagBg} ${strat.tagText}`}
                      >
                        {strat.tag}
                      </span>
                    </div>

                    {/* Metadata pills (Rule Score & Verified Status & Frequency) */}
                    <div className="flex items-center gap-1.5 mt-1 flex-wrap">
                      <span className="text-[9px] font-mono text-[#fdd663] bg-[#382b0e] px-1.5 py-0.2 rounded border border-[#664d12]">
                        {strat.ruleScoreRange}
                      </span>
                      <span className="text-[9px] font-mono text-[#9aa0a6] bg-[#171a21] px-1.5 py-0.2 rounded border border-[#282d38]">
                        {strat.winRate}
                      </span>
                      <span className="text-[9px] text-[#9aa0a6] bg-[#232834] px-1.5 py-0.2 rounded">
                        频次未统计
                      </span>
                      <span
                        className={`text-[9px] font-mono px-1.5 py-0.2 rounded ${macroCompat.badgeBg} ${macroCompat.badgeText}`}
                      >
                        {macroCompat.badge}
                      </span>
                    </div>

                    {/* Quantitative Logic Description */}
                    <p className="text-[10px] text-[#9aa0a6] mt-1.5 leading-relaxed">
                      {strat.description}
                    </p>

                    {/* Quant formula badge */}
                    <div className="mt-1 text-[9px] font-mono text-[#5f6368] truncate">
                      模型: {strat.quantFormula}
                    </div>
                  </div>

                  {/* Material 3 Toggle Switch */}
                  <div className="pt-0.5 shrink-0">
                    <M3Switch
                      checked={isEnabled}
                      onChange={() => toggleStrategy(strat.key)}
                      ariaLabel={`切换 ${strat.nameZh}`}
                    />
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* 2. Exclusive Monitored Asset: BTC/USDT */}
      <div className="p-3.5 rounded-2xl bg-[#1c2029] border border-[#2b313f] space-y-2.5">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1.5">
            <Coins className="w-4 h-4 text-[#fbbc04]" />
            <h3 className="text-xs font-semibold text-white">专属量化买入标的 (BTC Only)</h3>
          </div>
          <span className="text-[10px] font-mono text-[#81c995] bg-[#143820] px-2 py-0.5 rounded-full border border-[#2a6831]/60">
            纯 BTC 现货
          </span>
        </div>

        <p className="text-[11px] text-[#9aa0a6]">
          遵循绝对纯化铁律：专属监控并辅助决策 BTC/USDT 现货买入机会，已彻底移除并屏蔽所有山寨币杂波。
        </p>

        <div className="p-2.5 rounded-xl bg-[#252219] border border-[#fbbc04]/50 flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-lg bg-[#fbbc04]/20 border border-[#fbbc04]/40 flex items-center justify-center text-[#fbbc04] font-bold text-sm">
              ₿
            </div>
            <div>
              <div className="text-xs font-semibold text-white flex items-center gap-1.5">
                <span>BTC / USDT</span>
                <span className="text-[9px] px-1.5 py-0.2 rounded bg-[#143820] text-[#81c995] font-semibold">
                  唯一现货做多标的
                </span>
                <span className="text-[9px] px-1.5 py-0.2 rounded bg-[#202532] text-[#8ab4f8] font-mono">
                  BUY 信号专属
                </span>
              </div>
              <div className="text-[10px] text-[#9aa0a6] mt-0.5 font-mono">
                价格精度: 2位小数 ($XX,XXX.XX) · 币安现货撮合
              </div>
            </div>
          </div>
          <span className="text-[10px] text-[#fbbc04] font-mono font-medium">聚焦核心</span>
        </div>
      </div>

      {/* 3. Scan Frequency Selector */}
      <div className="p-3.5 rounded-2xl bg-[#1c2029] border border-[#2b313f] space-y-2.5">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1.5">
            <Clock className="w-4 h-4 text-[#81c995]" />
            <h3 className="text-xs font-semibold text-white">扫描预警频率设置</h3>
          </div>
          <span className="text-[10px] font-mono text-[#81c995] bg-[#143820] px-2 py-0.5 rounded-full border border-[#2a6831]/60">
            当前:{' '}
            {config.scanIntervalMs >= 60000
              ? `${config.scanIntervalMs / 60000}分钟`
              : `${config.scanIntervalMs / 1000}秒`}
          </span>
        </div>

        <p className="text-[11px] text-[#9aa0a6]">
          设置本地行情刷新间隔，不改变云端扫描周期，也不代表端到端通知延迟。
        </p>

        <div className="grid grid-cols-3 gap-1.5 pt-0.5">
          {INTERVAL_PRESETS.map((p) => {
            const isSelected = config.scanIntervalMs === p.ms;
            return (
              <button
                key={p.ms}
                onClick={() => onUpdateConfig({ scanIntervalMs: p.ms })}
                className={`py-1.5 px-2 rounded-xl text-[11px] font-mono font-medium transition-all text-center ${
                  isSelected
                    ? 'bg-[#1a3258] text-[#8ab4f8] border border-[#3b6bb0]/60 font-semibold shadow-sm'
                    : 'bg-[#171a21] text-[#9aa0a6] hover:text-[#e2e2e8] border border-[#282d38]'
                }`}
              >
                {p.label}
              </button>
            );
          })}
        </div>
      </div>

      {/* 4. Audio & Notification Tuning */}
      <div className="p-3.5 rounded-2xl bg-[#1c2029] border border-[#2b313f] space-y-2.5">
        <div className="flex items-center gap-1.5">
          <Volume2 className="w-4 h-4 text-[#81c995]" />
          <h3 className="text-xs font-semibold text-white">预警提示音与推送权限</h3>
        </div>

        <div className="grid grid-cols-2 gap-2 pt-0.5">
          <button
            onClick={() => soundService.playBuySignalChime()}
            className="py-2 px-3 rounded-full bg-[#143820] hover:bg-[#1e4e2a] border border-[#2a6831]/60 text-xs font-medium text-[#81c995] flex items-center justify-center gap-1.5 transition-colors active:scale-95"
          >
            <Zap className="w-3.5 h-3.5" />
            <span>试听买入音</span>
          </button>

          <button
            onClick={() => soundService.playRiskAlertChime()}
            className="py-2 px-3 rounded-full bg-[#231518] hover:bg-[#341b20] border border-[#4f2328]/60 text-xs font-medium text-[#f28b82] flex items-center justify-center gap-1.5 transition-colors active:scale-95"
          >
            <ShieldCheck className="w-3.5 h-3.5" />
            <span>试听止损音</span>
          </button>
        </div>

        {!hasNotificationPermission && (
          <button
            onClick={onRequestNotificationPermission}
            className="w-full py-2 px-3 rounded-full bg-[#1a3258] hover:bg-[#204070] border border-[#3b6bb0]/60 text-xs font-medium text-[#8ab4f8] flex items-center justify-center gap-1.5 transition-colors"
          >
            <Bell className="w-3.5 h-3.5" />
            <span>开启系统后台通知推送</span>
          </button>
        )}
      </div>

      {/* 5. Multi-API Redundancy Status */}
      <div className="p-3.5 rounded-2xl bg-[#1c2029] border border-[#2b313f] space-y-2.5">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1.5">
            <Database className="w-4 h-4 text-[#8ab4f8]" />
            <h3 className="text-xs font-semibold text-white">数据接口状态</h3>
          </div>
          <span className="text-[10px] text-[#9aa0a6] font-mono">
            4路冗余容灾
          </span>
        </div>

        <div className="space-y-1.5 pt-0.5">
          {API_PROVIDERS.map((prov) => (
            <div
              key={prov.id}
              className="p-2.5 rounded-xl bg-[#171a21] border border-[#282d38] flex items-center justify-between"
            >
              <div>
                <div className="text-xs font-medium text-white flex items-center gap-1.5">
                  <span>{prov.name}</span>
                  {prov.isPrimary ? (
                    <span className="text-[9px] font-mono px-1.5 py-0.2 rounded-full bg-[#143820] text-[#81c995] border border-[#2a6831]/60">
                      主推最优
                    </span>
                  ) : (
                    <span className="text-[9px] font-mono px-1.5 py-0.2 rounded-full bg-[#232834] text-[#9aa0a6]">
                      热备
                    </span>
                  )}
                </div>
                <div className="text-[10px] text-[#9aa0a6] mt-0.5">
                  {prov.description}
                </div>
              </div>

              <div className="text-right text-xs font-mono">
                <div className="text-[#81c995] font-semibold">延迟未实测</div>
                <div className="text-[9px] text-[#9aa0a6]">
                  {prov.apiKey.substring(0, 6)}...
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};
