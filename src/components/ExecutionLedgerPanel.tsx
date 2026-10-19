import {connection} from '../services/serverConnection';
import {previewFillImport} from '../services/fillImport';
import {unboundJournalCount,bindUnassignedJournal,allLibraryJournal} from '../services/modelLibrary';
import React, {useEffect, useRef, useState} from 'react';
import {ExecutionFill, summarizeFills, validateFill, latencyMetrics} from '../services/executionLedger';
import {JournalEntry, libraryJournal, rememberAction, newEventId, flushLibraryQueue, effectiveExecutionRows, fetchOpportunityArchive, fetchRecentOpportunities} from '../services/modelLibrary';

const eventNames: Record<string,string> = {PHONE_RECEIVED:'前台接收提醒',PHONE_OPENED:'点击通知',ENTRY_REJECTED:'入场复核未通过',SIM_BUY:'模拟入场',USER_CLOSE:'模拟退出',BACKFILL_CLOSE:'旧版卖出补记',STILL_HOLDING:'用户仍持有',MANUAL_FILL:'实际成交补录'};
const deliveryNames: Record<string,string> = {ATTEMPT:'已尝试发送，结果待核对',FCM_ACCEPTED:'推送平台已接收（非手机送达）',FAILED:'发送失败',PRE_SEND_REJECTED:'发送前复核未通过',COOLDOWN_SUPPRESSED:'冷却期间未发送',UNKNOWN_LEGACY_OR_UNATTEMPTED:'发送状态未知或尚未尝试'};
const modelNames: Record<string,string> = {BREAKOUT:'突破',REBOUND:'反弹',RANGE:'震荡'};
const money = (value: number | null) => value === null ? '未知（资料不全）' : `${value.toFixed(4)} USDT`;

export function ExecutionLedgerPanel({alertId = ''}: {alertId?: string}) {
  const [rows, setRows] = useState<JournalEntry[]>([]);
  const importScope=useRef<string | undefined>(undefined);
  const [importPreview,setImportPreview]=useState<ReturnType<typeof previewFillImport>|null>(null);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [opportunities, setOpportunities] = useState<Awaited<ReturnType<typeof fetchRecentOpportunities>>>([]);
  const [position, setPosition] = useState<string>(() => newEventId());
  const [opportunity, setOpportunity] = useState(alertId);
  const [side, setSide] = useState<'BUY'|'SELL'>('BUY');
  const [price, setPrice] = useState(''); const [quantity, setQuantity] = useState('');
  const [commission, setCommission] = useState(''); const [asset, setAsset] = useState('USDT');
  const [rate, setRate] = useState(''); const [at, setAt] = useState('');
  const [approximate, setApproximate] = useState(false);
  const [reference, setReference] = useState(''); const [referenceAt, setReferenceAt] = useState('');
  const saving = useRef(false);
  const [fillId, setFillId] = useState(newEventId);
  const [replaces, setReplaces] = useState<string | undefined>();
  const [exchangeId, setExchangeId] = useState('');
  useEffect(() => {
    const refresh = () => { try { setRows(libraryJournal()); } catch (e) { setError(String(e)); } };
    refresh();
    window.addEventListener('library-journal-changed', refresh);
    window.addEventListener('storage', refresh);
    const timer = window.setInterval(() => void flushLibraryQueue(), 15000);
    window.addEventListener('online', flushLibraryQueue);
    return () => { clearInterval(timer); window.removeEventListener('library-journal-changed', refresh); window.removeEventListener('storage', refresh); window.removeEventListener('online', flushLibraryQueue); };
  }, []);
  const executions = effectiveExecutionRows(rows);
  const positions = [...new Set(executions.map(r => r.action.fill!.positionId))];
  const selected = executions.filter(r => r.action.fill!.positionId === position);
  const fills = selected.map(r => r.action.fill!);
  let summary: ReturnType<typeof summarizeFills> | null = null;
  let summaryError = '';
  try { summary = summarizeFills(fills); } catch (e) { summaryError = String(e); }
  const linkedId = selected[0]?.action.alertId || opportunity || `manual-${position}`;
  const associated = rows.filter(r => r.action.alertId === linkedId);
  const firstTime = (kind: string) => associated.filter(r => r.action.recordType === kind).reduce<number | undefined>((v,r) => Math.min(v ?? Infinity, r.action.actedAtMs),undefined);
  const firstBuy = [...fills].filter(f => f.side === 'BUY').sort((a,b)=>a.executedAtMs-b.executedAtMs)[0];
  const signalAt = associated.find(r=>r.action.signalAtMs)?.action.signalAtMs;
  const signalPrice = associated.find(r=>r.action.signalPrice)?.action.signalPrice;
  const latency = latencyMetrics(signalAt, firstTime('PHONE_RECEIVED'), firstTime('PHONE_OPENED'), firstBuy && !firstBuy.timeApproximate ? firstBuy.executedAtMs : undefined);
  const submit = (event: React.FormEvent) => {
    event.preventDefault(); if (saving.current) return;
    saving.current = true; setError(''); setMessage('');
    try {
      const fill: ExecutionFill = {fillId, positionId: position, source: 'MANUAL', side, price: Number(price), quantity: Number(quantity), executedAtMs: new Date(at).getTime(),
        commission: commission.trim() === '' ? null : Number(commission), commissionAsset: asset.trim().toUpperCase(), commissionAssetUsdtRate: rate.trim() === '' ? null : Number(rate),
        referencePrice: reference.trim() === '' ? null : Number(reference), referenceAtMs: referenceAt === '' ? null : new Date(referenceAt).getTime(), timeApproximate: approximate, exchangeTradeId: exchangeId.trim() || null};
      const issue = validateFill(fill); if (issue) throw new Error(issue);
      if (fill.exchangeTradeId && executions.some(r=>r.action.eventId!==replaces && r.action.fill?.exchangeTradeId===fill.exchangeTradeId)) throw new Error('同一币安成交编号已记录，请使用更正功能');
      summarizeFills([...selected.filter(r=>r.action.eventId!==replaces).map(r=>r.action.fill!), fill]);
      rememberAction({recordType:'MANUAL_FILL', eventId: fillId, replacesEventId: replaces, alertId: linkedId, actedAtMs: Date.now(), fill, signalAtMs: signalAt,
        note: '用户手工补录，未与交易所核验；实际成交价已经包含成交滑点，不重复扣除'});
      setFillId(newEventId()); setReplaces(undefined); setExchangeId(''); setPrice(''); setQuantity(''); setCommission(''); setReference(''); setReferenceAt(''); setAt('');
      setMessage('已保存到本机持久队列；下方状态为“服务器确认”后才表示服务器已存档。');
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { saving.current = false; }
  };
  const exportJournal = () => {
    const url = URL.createObjectURL(new Blob([JSON.stringify(allLibraryJournal(), null, 2)], {type:'application/json'}));
    const link = document.createElement('a'); link.href = url; link.download = `Crypto-G-records-${Date.now()}.json`; link.click(); setTimeout(()=>URL.revokeObjectURL(url),1000);
  };
  const downloadServer = async () => {
    try {
      const archive = await fetchOpportunityArchive(linkedId);
      const url = URL.createObjectURL(new Blob([JSON.stringify(archive,null,2)],{type:'application/json'}));
      const a=document.createElement('a'); a.href=url; a.download=`Crypto-G-server-${linkedId}.json`; a.click(); setTimeout(()=>URL.revokeObjectURL(url),1000);
      setMessage('已下载所选机会的服务器档案，含发送状态、用户事件和参考退出结果。');
    } catch (e) { setError(String(e)); }
  };
  const correct = (row: JournalEntry) => {
    const f=row.action.fill!;
    const format = (ms:number) => new Date(ms-new Date(ms).getTimezoneOffset()*60000).toISOString().slice(0,19);
    setPosition(f.positionId); setOpportunity(row.action.alertId); setSide(f.side); setPrice(String(f.price)); setQuantity(String(f.quantity));
    setCommission(f.commission===null?'':String(f.commission)); setAsset(f.commissionAsset); setRate(f.commissionAssetUsdtRate===null?'':String(f.commissionAssetUsdtRate));
    setAt(format(f.executedAtMs)); setApproximate(f.timeApproximate); setReference(f.referencePrice===null?'':String(f.referencePrice)); setReferenceAt(f.referenceAtMs===null?'':format(f.referenceAtMs));
    setReplaces(row.action.eventId); setFillId(newEventId()); setMessage('正在更正选中成交；保存后追加更正事件，原记录仍保留。');
    setExchangeId(f.exchangeTradeId || '');
  };
  const inputClass = 'w-full mt-1 p-2 rounded bg-[#10141c] border border-[#383e4c] text-white';
  return <section className="p-3 rounded-xl bg-[#1c2029] border border-[#383e4c] text-xs space-y-3">
    <h3 className="font-semibold text-white">实际成交补录与机会记录</h3>
    {unboundJournalCount()>0 && <div className="text-amber-200"><p>有 {unboundJournalCount()} 条旧记录或离线记录尚未确认服务器归属，暂不发送、不混入当前账户统计。</p><button className="underline" onClick={()=>{try{bindUnassignedJournal();setRows(libraryJournal());setMessage("已绑定当前连接，请核对后同步");}catch(e){setError(String(e));}}}>确认这些记录属于当前服务器及账户并绑定</button></div>}
    <button onClick={downloadServer} className="p-2 border rounded">下载所选机会的服务器档案</button>
    <button className="ml-2 p-2 border rounded" onClick={async()=>{try{setOpportunities(await fetchRecentOpportunities());}catch(e){setError(String(e));}}}>读取最近 100 次云端机会</button>
    {opportunities.length>0 && <details><summary>云端机会（包括发送失败和冷却抑制）</summary>{opportunities.map(o=><div key={o.alertId} className="border-t p-2 break-all"><p>{new Date(o.atMs).toLocaleString()} · {modelNames[o.model || ''] || '旧版'} · {deliveryNames[o.delivery] || '状态待核对'} · {o.pathStatus === 'OPEN' ? '参考路径观察中' : '参考路径已结束'}</p><button onClick={()=>{setReplaces(undefined);setExchangeId('');setPrice('');setQuantity('');setCommission('');setAt('');setPosition(newEventId());setOpportunity(o.alertId);setSide('BUY');setFillId(newEventId());}}>{o.alertId} · 选择关联</button></div>)}</details>}
    <p className="text-[#9aa0a6]">仅记录 BTCUSDT 手工成交，不下单、不改模拟持仓。每笔买入/分批卖出分别填写。实际手续费未知请留空，明确免手续费才填 0。</p>
    <div className="flex gap-2"><button onClick={()=>{setReplaces(undefined);setExchangeId('');setPrice('');setQuantity('');setCommission('');setAt('');setPosition(newEventId());setOpportunity(alertId);setSide('BUY');setFillId(newEventId());setMessage('已新建独立持仓，请补录买入');}} className="p-2 border rounded">新建独立持仓</button><button onClick={exportJournal} className="p-2 border rounded">导出全部记录</button><button onClick={()=>void flushLibraryQueue()} className="p-2 border rounded">重试同步</button></div>
    <label className="block">持仓记录<select className={inputClass} value={position} onChange={e=>{setReplaces(undefined);setExchangeId('');setPrice('');setQuantity('');setCommission('');setAt('');setPosition(e.target.value);setSide('SELL');setFillId(newEventId());}}><option value={position}>{positions.includes(position) ? `当前持仓 ${position.slice(0,8)}` : '新持仓（先买入）'}</option>{positions.filter(p=>p!==position).map(p=><option key={p} value={p}>{p.slice(0,8)}</option>)}</select></label>
    <details><summary>导入标准成交 JSON（先预览，再写入）</summary>
      <p>支持 ExecutionFill 数组或本应用导出的成交记录。按当前服务器及账户导入，费用仍需包含当时折算汇率；差异不自动覆盖。</p>
      <input type="file" accept=".json,application/json" onChange={async e=>{try{const file=e.target.files?.[0];if(!file)return;if(file.size>2_000_000)throw new Error('文件超过 2 MB');const capturedScope=connection().cacheScope;const raw=JSON.parse(await file.text());if(connection().cacheScope!==capturedScope)throw new Error("连接已变更，请重新选择文件");importScope.current=capturedScope;setImportPreview(previewFillImport(raw,executions.map(r=>r.action.fill!)));}catch(error){setImportPreview(null);setError(String(error));}}}/>
      {importPreview && <div><p>新增 {importPreview.fills.length} 笔，重复 {importPreview.duplicates} 笔将跳过。</p><button onClick={()=>{try{
        if(importScope.current!==connection().cacheScope)throw new Error("连接已变更，请重新选择文件");
        const checked=previewFillImport(importPreview.fills,effectiveExecutionRows(libraryJournal()).map(r=>r.action.fill!));
        const batchId=newEventId(),importedAt=Date.now();
        for(const [index,fill] of checked.fills.entries()){const prior=executions.find(r=>r.action.fill?.positionId===fill.positionId);rememberAction({recordType:'MANUAL_FILL',eventId:`import_${batchId}_${String(index).padStart(4,'0')}`,alertId:prior?.action.alertId || `import-${batchId}-${checked.fills.findIndex(f=>f.positionId===fill.positionId)}`,actedAtMs:importedAt,fill,note:'标准 JSON 导入，未与交易所核验'});}
        setImportPreview(null);setRows(libraryJournal());setMessage('已导入本机队列，请核对服务器同步状态');
      }catch(error){setError(String(error));}}}>确认将预览成交导入当前账户</button></div>}
    </details>
    <form onSubmit={submit} className="space-y-3">
      <label className="block">关联预警编号（无预警可留空）<input className={inputClass} value={selected[0]?.action.alertId || opportunity} disabled={selected.length>0} onChange={e=>setOpportunity(e.target.value)} list="recorded-opportunities"/></label>
      <label className="block">币安成交编号（可选，用于防重）<input className={inputClass} value={exchangeId} onChange={e=>setExchangeId(e.target.value)} placeholder="不是订单号；同一订单可有多笔成交"/></label>
      <datalist id="recorded-opportunities">{[...new Set(rows.map(r=>r.action.alertId))].map(id=><option key={id} value={id}/>)}</datalist>
      <div className="grid grid-cols-2 gap-2"><label>方向<select className={inputClass} value={side} onChange={e=>setSide(e.target.value as 'BUY'|'SELL')}><option value="BUY">实际买入</option><option value="SELL">实际卖出（可分批）</option></select></label>
        <label>成交均价 USDT<input required className={inputClass} inputMode="decimal" value={price} onChange={e=>setPrice(e.target.value)}/></label>
        <label>成交 BTC 数量（扣费前）<input required className={inputClass} inputMode="decimal" value={quantity} onChange={e=>setQuantity(e.target.value)}/></label>
        <label>实际手续费数量<input className={inputClass} inputMode="decimal" value={commission} onChange={e=>setCommission(e.target.value)} placeholder="未知留空"/></label>
        <label>手续费币种<input required className={inputClass} value={asset} onChange={e=>setAsset(e.target.value.toUpperCase())}/></label>
        <label>手续费币种当时 USDT 单价<input className={inputClass} value={rate} onChange={e=>setRate(e.target.value)} placeholder="BNB 等需填；BTC/USDT 自动"/></label>
      </div>
      <label className="block">实际成交时间（本机时区）<input required type="datetime-local" step="1" className={inputClass} value={at} onChange={e=>setAt(e.target.value)}/></label>
      <label className="flex gap-2"><input type="checkbox" checked={approximate} onChange={e=>setApproximate(e.target.checked)}/>时间为近似值（不计算精确入场延迟）</label>
      <details><summary>可选：成交前决策报价，用于衡量执行价差</summary><p className="text-[#9aa0a6] mt-2">买入填当时卖一价，卖出填当时买一价。没有当时记录就留空，不能用今天的报价替代。较早的报价差包含延迟期间行情变化，不等于纯撮合滑点。</p>
        <label className="block">基准价格<input className={inputClass} value={reference} onChange={e=>setReference(e.target.value)}/></label><label className="block">基准报价时间<input type="datetime-local" step="1" className={inputClass} value={referenceAt} onChange={e=>setReferenceAt(e.target.value)}/></label></details>
      <button type="submit" className="w-full p-2 rounded bg-[#285c42] text-white">保存这笔实际成交补录</button>
      {replaces && <button type="button" onClick={()=>{setReplaces(undefined);setFillId(newEventId());setPrice('');setQuantity('');setMessage('已取消更正');}}>取消更正</button>}
    </form>
    {error && <p role="alert" className="text-[#f28b82]">{error}</p>}{message && <p role="status" className="text-[#81c995]">{message}</p>}
    {summaryError && <p className="text-[#f28b82]">账目待核对：{summaryError}</p>}
    {summary && fills.length>0 && <div className="space-y-1 rounded-lg bg-[#171a21] p-2">
      <p>实际成交补录 · 未经交易所核验；已卖 {summary.sold.toFixed(8)} BTC（买入数量的 {summary.bought>0?(summary.sold/summary.bought*100).toFixed(2):'未知'}%）</p>
      <p>整笔 ≥0.8%：{summary.wholeTradeNetPct===null?'全部退出且费用齐全后判定':summary.wholeTradeNetPct>=.8?'已达到':'未达到'}</p>
      {firstBuy && !summary.closed && <><p>90 分钟检查：{new Date(firstBuy.executedAtMs+5400000).toLocaleString()}；进展不足 +0.3R 时退出。</p><p>6 小时最晚退出：{new Date(firstBuy.executedAtMs+21600000).toLocaleString()}{Date.now()>=firstBuy.executedAtMs+21600000?' · 已超时，请核对未补录卖出':''}</p><p>时间以首笔买入{firstBuy.timeApproximate?'近似记录':'记录'}为准；提示不会代替实际卖出或补录。</p></>}
    </div>}
    {selected.map(r=><button key={r.action.eventId} className="mr-2 p-1 border rounded" onClick={()=>correct(r)}>更正 {r.action.fill!.side} {r.action.fill!.quantity} BTC · {r.action.fill!.fillId.slice(0,8)}</button>)}
    {summary && fills.length>0 && <div className="space-y-1 border-t border-[#383e4c] pt-2"><p>手工补录净已实现收益：{money(summary.realizedNetUsdt)}</p><p>整笔净收益：{summary.wholeTradeNetPct === null ? "待全部退出且费用齐全" : `${summary.wholeTradeNetPct.toFixed(4)}%`}</p><p>已记录手续费折合：{money(summary.feeUsdt)}</p><p>剩余 BTC：{summary.inventory === null ? '未知（费用不全）' : summary.inventory.toFixed(8)} · {summary.closed ? '已全部退出' : '未确认全部退出'}</p>
      <p>信号至首笔入场：{latency.signalToEntryMs === null ? '未知' : `${latency.signalToEntryMs/1000} 秒`}</p><p>前台接收至入场：{latency.receivedToEntryMs === null ? '未知' : `${latency.receivedToEntryMs/1000} 秒`}；点击通知至入场：{latency.openedToEntryMs === null ? '未知' : `${latency.openedToEntryMs/1000} 秒`}</p><p>信号价至首笔成交价变化：{firstBuy && signalPrice ? `${((firstBuy.price/signalPrice-1)*100).toFixed(4)}%` : '未知'}（含等待期间行情变化，非纯滑点）</p><p className="text-[#9aa0a6]">净收益按成交价及手续费计算，执行价差只作诊断，不再重复扣减；手工数据未经交易所核验。</p></div>}
    <details><summary>本机机会与成交日记：{rows.length} 条 · 待同步 {rows.filter(r=>r.status==='pending').length} · 被拒绝 {rows.filter(r=>r.status==='rejected').length}</summary>
      <div className="max-h-72 overflow-y-auto space-y-2 mt-2">{[...rows].reverse().map(r=><div key={r.action.eventId} className="border-t border-[#383e4c] pt-2 break-all"><p>{eventNames[r.action.recordType] || '旧版事件'} · {new Date(r.action.actedAtMs).toLocaleString()} · {r.status==='acked'?'服务器确认':r.status==='rejected'?'校验拒绝，记录仍保留':'等待同步'}</p><p>{r.action.alertId}</p>{r.action.fill && <p>{r.action.fill.side} {r.action.fill.quantity} BTC @ {r.action.fill.price}；费用 {r.action.fill.commission ?? '未知'} {r.action.fill.commissionAsset}</p>}{r.action.replacesEventId && <p>更正原事件：{r.action.replacesEventId}</p>}{rows.some(other=>other.status!=='rejected' && other.action.replacesEventId===r.action.eventId) && <p>已被后续更正替代，不重复计入</p>}{r.error && <p className="text-[#f28b82]">{r.error}</p>}{r.action.note && <p className="text-[#9aa0a6]">{r.action.note}</p>}</div>)}</div>
    </details>
    {summary && summary.slippage.map(s=><p key={s.fillId} className="text-[#9aa0a6]">成交 {s.fillId.slice(0,8)} 执行价差成本：{money(s.quoteDifferenceUsdt)}；基准距成交 {s.benchmarkAgeMs === null?'未知':`${s.benchmarkAgeMs/1000} 秒`}（正值不利，负值改善）</p>)}
  </section>;
}
