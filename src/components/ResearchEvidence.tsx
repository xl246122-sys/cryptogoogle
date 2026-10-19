import React from 'react';
const num=(v:unknown,d=2)=>typeof v==='number'&&Number.isFinite(v)?v.toFixed(d):'未知';
const health=(v:unknown)=>v===true?'正常':v===false?'异常':'未知';
export function ResearchEvidence({data}:{data:any}) {
 return <>
 {data?.aiEffectiveness?.groups?.map((g:any,i:number)=><p key={i}>环境 {Object.values(g.environment||{}).join('/')}：否决 {g.vetoed} 笔 / 放行 {g.passed} 笔；均值 {num(g.vetoMeanR)}R / {num(g.passMeanR)}R。否决未满 100 笔不能判断保留效果。</p>)}
 <details className="border-t border-gray-700 pt-2 space-y-2"><summary>整笔净收益研究统计 · 未验证</summary>
  <p>仅已结算且路径有效的模拟样本；不代表独立样本外验证或真实账户表现。旧规则、费用或路径不明样本排除：{data?.researchSummary?.excluded ?? '未知'} 笔。</p>
  {!data?.researchSummary?.groups?.length && <p>暂无完整分组；样本缺失不记为收益为零。</p>}
  {data?.researchSummary?.groups?.map((g:any,i:number)=><div key={i} className="border-t border-gray-700 py-2 space-y-1">
   <p>{g.module} · {g.kind==='SHADOW'?'影子模拟':g.kind==='PAPER'?'纸面模拟':'模拟对照'} · {g.trades} 笔</p>
   <p>{new Date(g.fromMs).toLocaleString()} 至 {new Date(g.toMs).toLocaleString()}</p>
   <p>净胜率 {num(g.winRate*100)}% · 整笔 ≥0.8% 达成 {num(g.targetRate*100)}% · 均值 {num(g.expectancyPct,3)}%</p>
   <p>逐笔净收益加总回撤 {num(g.sumNetDrawdownPct,3)} 个百分点（非账户回撤）；最大连亏 {g.maxConsecutiveLosses} 笔</p>
   <p className="break-all text-gray-500">{g.ruleVersion} / {g.executionVersion} / {g.costVersion} · 工作成本 {num(g.frictionPct)}%</p>
  </div>)}
 </details>
 <details className="border-t border-gray-700 pt-2 space-y-2"><summary>运行与容量证据</summary>
  <p>扫描 {health(data?.runtimeHealthy)} · 行情 {health(data?.feedHealthy)} · 研究 {health(data?.spotResearch?.healthy)} · 买入推送处理 {health(data?.notificationHealthy)} · 退出推送处理 {health(data?.exitNotificationHealthy)}</p>
  <p>状态时间：{data?.snapshot?.atMs?new Date(data.snapshot.atMs).toLocaleString():'未知'}</p>
  <p>磁盘剩余 {data?.capacity?.diskFreeBytes==null?'未知':num(data.capacity.diskFreeBytes/1073741824)} GiB；监控日志日增 {data?.capacity?.journalGrowthBytesPerDay==null?'未知':num(data.capacity.journalGrowthBytesPerDay/1048576)} MiB（不涵盖研究库）</p>
  <p>最近备份及恢复演练：接口未提供，未知。平台接受与手机收到、用户打开分别统计。</p>
 </details>
 </>;
}
