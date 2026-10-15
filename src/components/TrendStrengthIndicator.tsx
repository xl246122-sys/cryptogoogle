import React from 'react';
import {Activity, TrendingDown, TrendingUp} from 'lucide-react';
import type {MacroTrendAnalysis} from '../types/crypto';

interface Props {macroTrend:MacroTrendAnalysis;currentPrice?:number;className?:string}
export function TrendStrengthIndicator({macroTrend:m,className=''}:Props){
  const ready=m.dataReady===true && Number.isFinite(m.hourlyRsi) && m.hourlyRsi>=0 && m.hourlyRsi<=100 && Number.isFinite(m.hourlyMa20) && m.hourlyMa20>0;
  const bearish=m.hourlyTrend==='BEARISH',bullish=m.hourlyTrend==='BULLISH';
  const color=!ready?'#9aa0a6':bearish?'#f28b82':bullish?'#81c995':'#fdd663';
  const Icon=bearish?TrendingDown:bullish?TrendingUp:Activity;
  const label=!ready?'待更新':bearish?'空头背景':bullish?'多头背景':'震荡背景';
  return <section aria-label="1小时趋势强度" className={`rounded-2xl border px-3.5 py-3 ${className}`} style={{borderColor:color+'40',background:`linear-gradient(120deg, ${color}0d, #151820 75%)`}}>
    <div className="flex items-center justify-between gap-2">
      <h2 className="text-[13px] font-semibold text-gray-100">1小时趋势强度 <span className="text-[10px] font-normal text-gray-500">BTC</span></h2>
      <span className="inline-flex items-center gap-1 text-[11px] font-medium" style={{color}}><Icon size={13} aria-hidden="true"/>{label}</span>
    </div>
    <div className="mt-2 flex justify-between text-[10px] text-gray-400"><span>偏弱</span><span>RSI 动量</span><span>偏强</span></div>
    <div className="relative mx-1 my-2 h-2 rounded-full" style={{background:ready?'linear-gradient(90deg,#ea4335 0%,#fbbc04 50%,#34a853 100%)':'#343a46'}} role={ready?'meter':undefined} aria-label={ready?'1小时 RSI 动量，非上涨概率':undefined} aria-valuemin={ready?0:undefined} aria-valuemax={ready?100:undefined} aria-valuenow={ready?m.hourlyRsi:undefined}>
      <span className="absolute inset-y-0 left-[45%] border-l border-black/25"/><span className="absolute inset-y-0 left-[55%] border-l border-black/25"/>
      {ready && <span className="absolute top-1/2 size-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-white shadow-[0_0_7px_#ffffff40] transition-[left] duration-700 ease-out motion-reduce:transition-none" style={{left:`${m.hourlyRsi}%`,background:color}}/>}
    </div>
    <div className="flex justify-between gap-2 text-[11px] tabular-nums"><span className="text-gray-400">RSI <strong style={{color}}>{ready?m.hourlyRsi.toFixed(2):'—'}</strong></span><span className="text-gray-400">MA20 <span className="text-gray-200">{ready?'$'+m.hourlyMa20.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2}):'—'}</span></span></div>
    <details className="mt-2 text-[10px] text-gray-500">
      <summary className="cursor-pointer select-none">{ready?'收盘数据 · 非买入指令':'行情不可用 · 暂停解读'}<span className="ml-2 text-gray-400">查看依据</span></summary>
      <div className="mt-2 space-y-1 border-t border-white/5 pt-2 text-[11px] leading-relaxed"><p>{m.regimeNameZh}</p><p>{m.regimeDescription}</p><p>{m.biasZh}</p><p>彩条直接表示服务端 1h RSI（0–100），不是胜率或综合评分；背景分类以服务端判断为准。</p></div>
    </details>
  </section>;
}
