import React, { useEffect, useState } from 'react';
import type { MacroTrendAnalysis, ReleaseLab, TradeSignal, WatchlistItem } from '../types/crypto';

const LOCAL_LAB: ReleaseLab = {
  source: 'LOCAL',
  modules: ['S1', 'S2', 'S3', 'S4'].map((module) => ({
    module, stage: 'RESEARCH', label: '研究', push: true, tierLabel: '观察级·未验证', records: 0,
  })),
  l1: { status: 'INSUFFICIENT', applied: false, samples: null, minSamples: 200 },
  promotions: 0,
  hypotheses: [],
  note: '云端尚未返回晋级进度。S1–S4 为观察级·未验证；S5 仅研究，不发买入提示。',
};

function money(value?: number) {
  return value && value > 0 ? `$${value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : '—';
}

function remain(ms?: number | null) {
  if (ms == null) return '';
  const days = Math.ceil(ms / 86_400_000);
  return days <= 0 ? '已到期' : `剩余 ${days} 天`;
}

function costLine(lab: ReleaseLab) {
  const cost = lab.continuity?.cost;
  if (cost?.frictionPct == null) return '每月成本尚未同步。地板保持 0.24%。';
  if (cost.source === 'FILLS') return `${cost.month} 工作成本 ${cost.frictionPct}% ，高于地板 ${cost.floorPct ?? 0.24}%。`;
  if (cost.source === 'FLOOR') return `${cost.month} 实测未高于地板，工作成本保持 ${cost.frictionPct}%。`;
  return `${cost.month} 没有成对成交，工作成本保持地板 ${cost.floorPct ?? cost.frictionPct}%。`;
}

function boundLine(lab: ReleaseLab) {
  const env = lab.continuity?.environment;
  if (!env && lab.continuity?.environmentOpen) return `${lab.continuity.environmentOpen} 仍在 6 小时持有期内，分界报告稍后写入。`;
  if (!env) return '每季环境分界尚未同步。先验分界保持 0。';
  if (env.status === 'HELD' && env.cutoff != null) return `${env.quarter} 环境分界提案 ${env.cutoff}，先验 ${env.priorCutoff ?? 0}。提案未写入规则。`;
  return `${env.quarter} 已平样本不足 200，环境分界保持 ${env.priorCutoff ?? 0}。`;
}

function countdown(expiresAt: number | undefined, now: number) {
  if (!expiresAt) return '无有效期';
  const left = expiresAt - now;
  if (left <= 0) return '已过期';
  const minutes = Math.floor(left / 60000);
  const seconds = Math.floor((left % 60000) / 1000);
  return `${minutes}分${String(seconds).padStart(2, '0')}秒`;
}

export function EnvironmentCard({ market }: { market: MacroTrendAnalysis }) {
  const layers = market.layers;
  return (
    <section className="p-3.5 rounded-2xl bg-[#1c2029] border border-[#2b313f] space-y-2.5" aria-label="三层环境">
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-white">三层环境</h2>
        <span className="text-[10px] text-[#9aa0a6]">{layers ? `评分 ${layers.score > 0 ? '+' : ''}${layers.score}` : '等待云端'}</span>
      </div>
      {layers ? (
        <div className="grid grid-cols-3 gap-2 text-xs">
          {([['1D', layers.d1], ['4H', layers.h4], ['1H', layers.h1]] as const).map(([name, state]) => (
            <div key={name} className="rounded-xl bg-[#141822] border border-[#282d38] p-2">
              <div className="text-[10px] text-[#9aa0a6]">{name}</div>
              <div className="mt-0.5 font-semibold text-white">{state}</div>
            </div>
          ))}
        </div>
      ) : <p className="text-xs text-[#9aa0a6]">云端尚未返回 1D / 4H / 1H 环境。</p>}
      {market.levels && market.levels.length > 0 && (
        <div className="grid grid-cols-2 gap-2 text-[11px]">
          {market.levels.map((level) => (
            <div key={level.name} className="flex items-center justify-between rounded-lg bg-[#171a21] px-2 py-1.5">
              <span className="text-[#9aa0a6]">{level.name}</span>
              <span className="font-mono text-white">{money(level.price)}</span>
            </div>
          ))}
        </div>
      )}
      <WatchList market={market} />
    </section>
  );
}

function WatchList({ market }: { market: MacroTrendAnalysis }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);
  const rows = market.watchCandidates || [];
  return (
    <div className="space-y-1.5">
      <div className="text-[11px] text-[#9aa0a6]">观察级候选</div>
      {rows.length === 0 ? <p className="text-xs text-[#c4c7c5]">当前没有观察级候选。</p> : rows.map((row, index) => (
        <div key={`${row.module}-${index}`} className="flex items-center justify-between gap-2 rounded-lg bg-[#171a21] px-2 py-1.5 text-xs">
          <div className="min-w-0">
            <div className="font-semibold text-white">{row.module} · {row.tierLabel || '观察级·未验证'}</div>
            <div className="truncate text-[10px] text-[#9aa0a6]">{row.issue || row.name}</div>
          </div>
          <span className="shrink-0 font-mono text-[#fdd663]">{row.expiresAt ? countdown(row.expiresAt, now) : '仅记录'}</span>
        </div>
      ))}
    </div>
  );
}

export function PlanFacts({ signal }: { signal: TradeSignal }) {
  const trial = signal.tierLabel === '试运行' || (signal.strategyNameZh ?? '').includes('试运行');
  const timeStop = signal.timeStopMinutes ? `${signal.timeStopMinutes} 分钟未到 +0.3R 离场` : signal.timeHorizon;
  return (
    <div className="space-y-1.5 text-[11px] text-[#c4c7c5]">
      {trial && <span className="inline-flex rounded-full border border-[#664d12] bg-[#382b0e] px-2 py-0.5 font-semibold text-[#fdd663]">试运行</span>}
      <p>进场区 {money(signal.entryMin)} – {money(signal.entryMax)} · 止损 {money(signal.stopLoss)} · TP1 {money(signal.targetTP1)} · TP2 {money(signal.targetTP2)}</p>
      <p>时间止损 {timeStop}{signal.positionFractionPct ? ` · 建议仓位约为账户的 ${signal.positionFractionPct}%` : ''}</p>
      {signal.aiExplain && <p>AI：{signal.aiExplain}</p>}
    </div>
  );
}

export function TwinCard({ price, item }: { price: number; item: WatchlistItem }) {
  const entry = item.positionEntryPrice || 0;
  const stop = item.linkedSl || item.alertBelowPrice || 0;
  const planned = entry > 0 && stop > 0 && stop < entry;
  const distance = price > 0 && stop > 0 ? (price - stop) / price * 100 : null;
  const multiple = planned && price > 0 ? (price - entry) / (entry - stop) : null;
  return (
    <section className="p-3.5 rounded-2xl bg-[#1c2029] border border-[#2b313f] space-y-2" aria-label="孪生仓对比">
      <h2 className="text-sm font-semibold text-white">止损距离与孪生仓</h2>
      {planned ? (
        <div className="grid grid-cols-2 gap-2 text-xs">
          <div className="rounded-xl bg-[#171a21] p-2"><div className="text-[10px] text-[#9aa0a6]">距止损</div><div className="mt-0.5 font-mono text-white">{distance == null ? '—' : `${distance.toFixed(2)}%`}</div></div>
          <div className="rounded-xl bg-[#171a21] p-2"><div className="text-[10px] text-[#9aa0a6]">浮动 R</div><div className="mt-0.5 font-mono text-white">{multiple == null ? '—' : `${multiple.toFixed(2)}R`}</div></div>
          <div className="rounded-xl bg-[#171a21] p-2"><div className="text-[10px] text-[#9aa0a6]">手机持仓</div><div className="mt-0.5 font-mono text-white">{item.positionSize || 0} USDT</div></div>
          <div className="rounded-xl bg-[#171a21] p-2"><div className="text-[10px] text-[#9aa0a6]">系统孪生</div><div className="mt-0.5 font-mono text-white">500 USDT</div></div>
        </div>
      ) : <p className="text-xs text-[#9aa0a6]">没有挂上的交易计划。记入一笔买入后，这里比较手机持仓和 500 USDT 孪生仓。</p>}
      <p className="text-[10px] text-[#9aa0a6]">录入成交用上面的「买入 500 USDT」。系统出场仍按信号里的止损和止盈结算。</p>
    </section>
  );
}

export function ReviewCard({ market }: { market?: MacroTrendAnalysis }) {
  const lab = market?.lab;
  return (
    <section className="rounded-2xl border border-indigo-500/25 bg-[#141824] p-3 space-y-2" aria-label="复盘与假设">
      <h2 className="text-sm font-semibold text-white">复盘与假设</h2>
      <p className="text-xs text-[#c4c7c5]">{lab?.daily?.summary || '当日复盘还没有从云端同步。'}</p>
      <div className="text-[11px] text-[#9aa0a6]">待检验假设</div>
      {(lab?.hypotheses || []).length === 0 ? <p className="text-xs text-[#9aa0a6]">本周还没有假设。假设不会改 S1–S5。</p> : lab!.hypotheses.map((item, index) => (
        <p key={`${item.module}-${index}`} className="text-xs text-[#c4c7c5]">{item.module || '形态'} · {item.status || '未检验'} · {item.claim || '无说明'} · 未写入规则</p>
      ))}
      <p className="text-xs text-[#c4c7c5]">{lab?.veto ? `否决权${lab.veto.vetoEnabled ? '开' : '关'}。否决样本 ${lab.veto.vetoed ?? '—'} 笔，平均 R ${lab.veto.vetoedMeanR ?? '—'}；通过样本 ${lab.veto.passed ?? '—'} 笔，平均 R ${lab.veto.passedMeanR ?? '—'}。` : 'AI 否决价值还没有审计结果。'}</p>
    </section>
  );
}

function GuardFacts({ market }: { market: MacroTrendAnalysis }) {
  return (
    <div className="space-y-1.5 text-xs" aria-label="版本与新鲜度">
      <h2 className="text-sm font-semibold text-white">版本、熔断、数据新鲜度</h2>
      <p className="text-[#c4c7c5]">{market.biasZh || '模型版本尚未从云端同步。'}</p>
      <p className="text-[#c4c7c5]">熔断：{market.breaker ? `${market.breaker.state}${market.breaker.reason ? ` · ${market.breaker.reason}` : ''}` : '云端未报告熔断状态。'}</p>
      <p className="text-[#c4c7c5]">{market.freshness ? `${market.freshness.context} · ${market.freshness.derivatives}` : '云端未报告数据新鲜度。'}</p>
    </div>
  );
}

export function GuardCard({ market }: { market: MacroTrendAnalysis }) {
  return <section className="p-3.5 rounded-2xl bg-[#1c2029] border border-[#2b313f]"><GuardFacts market={market} /></section>;
}

export function LabCard({ market }: { market: MacroTrendAnalysis }) {
  const lab = market.lab || LOCAL_LAB;
  const gates = lab.gates;
  const gateText = gates
    ? `样本外至少 ${gates.minTrades ?? 60} 笔，扣费期望至少 +${gates.minExpectancyPct ?? 0.1}%，胜率至少 ${Math.round((gates.minWinRate ?? 0.52) * 100)}%，盈利因子至少 ${gates.minProfitFactor ?? 1.3}。`
    : '样本外至少 60 笔，扣费期望至少 +0.10%，胜率至少 52%，盈利因子至少 1.30。';
  return (
    <div className="space-y-2" aria-label="策略实验室">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-white">策略实验室</h2>
        <span className="text-[10px] text-[#9aa0a6]">晋级记录 {lab.promotions}</span>
      </div>
      <p className="text-[11px] text-[#9aa0a6]">{gateText}这是门槛，不是当前成绩。</p>
      {lab.note && <p className="text-xs text-[#fdd663]">{lab.note}</p>}
      {lab.modules.map((row) => (
        <div key={row.module} className="rounded-xl bg-[#171a21] px-2.5 py-2 text-xs">
          <div className="flex items-center justify-between gap-2">
            <span className="font-semibold text-white">{row.module} · {row.label}</span>
            <span className="text-[#fdd663]">{row.tierLabel}{row.push ? '' : ' · 不推送'}</span>
          </div>
          <p className="mt-0.5 text-[10px] text-[#9aa0a6]">{remain(row.remainingMs)}{row.records ? ` · 影子记录 ${row.records}` : ''}{(row.gaps || []).slice(0, 2).join('；')}</p>
        </div>
      ))}
      <p className="text-[11px] text-[#9aa0a6]">L1 {lab.l1.status === 'FIT' ? '已拟合' : '样本不足'}，提案未写入规则。{lab.l1.proposal?.pThreshold != null ? `P ${lab.l1.proposal.pThreshold}，进场偏移 ${lab.l1.proposal.entryOffsetPct}% ，止损缓冲 ${lab.l1.proposal.stopBufferPct}%。` : ''}</p>
      <p className="text-[11px] text-[#9aa0a6]">{costLine(lab)} 每周假设沿用复盘，保持未应用。</p>
      <p className="text-[11px] text-[#9aa0a6]">{boundLine(lab)}</p>
    </div>
  );
}

export function GuardLabDrawer({ market }: { market: MacroTrendAnalysis }) {
  const breaker = market.breaker?.state || '熔断未同步';
  return (
    <details className="group rounded-xl border border-[#2b313f] bg-[#1c2029]" aria-label="版本与策略实验室">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-2 px-3.5 py-2.5 [&::-webkit-details-marker]:hidden">
        <span className="text-sm font-semibold text-white">版本与策略实验室</span>
        <span className="flex items-center gap-1.5 text-[10px] text-[#9aa0a6]">{breaker}<span className="transition-transform group-open:rotate-180">▾</span></span>
      </summary>
      <div className="space-y-3 border-t border-[#2b313f] px-3.5 py-3">
        <GuardFacts market={market} />
        <LabCard market={market} />
      </div>
    </details>
  );
}
