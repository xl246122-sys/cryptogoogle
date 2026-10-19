import type {LibraryAction, JournalEntry} from './modelLibrary';
export const LEGACY_PAPER_STRATEGY='QUICK_PAPER_V1';
export const PAPER_STRATEGY='QUICK_PAPER_V2';
export interface PaperCost {costModelVersion: string; frictionPct: number; applicableAtMs: number; source?: string}
export function paperSummary(rows:JournalEntry[], strategy=PAPER_STRATEGY) {
 let quantity=0,cost=0,realized=0,costReserve=0;
 for(const {action:a,status} of rows){
  if(a.strategy!==strategy || status==='rejected')continue;
  if(a.recordType==='SIM_BUY' && a.entryPrice && a.positionSize){quantity+=a.positionSize/a.entryPrice;cost+=a.positionSize; costReserve+=a.positionSize*(a.costSnapshot?.frictionPct ?? .24)/100;}
  if(a.recordType==='USER_CLOSE' && a.entryPrice && a.exitPrice && a.positionSize){
   const sold=a.positionSize/a.entryPrice; const allocated=quantity>0?costReserve*sold/quantity:0; quantity-=sold;cost-=a.positionSize;costReserve-=allocated;
   realized+=sold*a.exitPrice-a.positionSize-(strategy===LEGACY_PAPER_STRATEGY?(sold*a.exitPrice+a.positionSize)*.00055:allocated);
  }
 }
 return {quantity:Math.max(0,quantity),cost:Math.max(0,cost),realized};
}
export function paperAction(side:'BUY'|'SELL',price:number,quoteAt:number,now:number,rows:JournalEntry[],id:string,cost:PaperCost={costModelVersion:"cost-v2.1",frictionPct:.24,applicableAtMs:now}):LibraryAction {
 if(!Number.isFinite(price)||price<=0||!Number.isFinite(quoteAt)||now-quoteAt>10000||now<quoteAt)throw new Error('行情过期或不可用，请等待更新');
 if(!Number.isFinite(cost.frictionPct)||cost.frictionPct<.24||cost.applicableAtMs>now)throw new Error("模拟成本快照无效");
 const s=paperSummary(rows);
 const common={alertId:id,actedAtMs:now,quoteAtMs:quoteAt,strategy:PAPER_STRATEGY,costSnapshot:cost,note:'一键模拟；参考成交价，往返成本按买入快照扣除；含手续费及滑点假设，非实际成交'};
 if(side==='BUY')return {...common,recordType:'SIM_BUY',entryPrice:price,positionSize:500};
 if(s.quantity<=1e-12)throw new Error('暂无可卖出的模拟持仓');
 const quantity=Math.min(s.quantity,500/price);
 return {...common,recordType:'USER_CLOSE',entryPrice:s.cost/s.quantity,exitPrice:price,positionSize:quantity*(s.cost/s.quantity),exitSource:'APP_BUTTON'};
}
