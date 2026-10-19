import type {TradeSignal} from '../types/crypto';
export function netPlan(signal:TradeSignal, amount:number) {
  const rule=signal.tradeRules;
  if(rule?.ruleVersion!=='short-horizon-v2' || rule.tp1Fraction!==.5)return null;
  const cost=rule.costSnapshot?.frictionPct??rule.frictionPct??signal.analysis?.estimatedFriction;
  const floor=rule.costSnapshot?.bnbDiscount===true && rule.costSnapshot.bnbVerified===true ? .19 : .24;
  const entry=signal.entryMax;
  if(![entry,signal.targetTP1,signal.targetTP2,signal.stopLoss,cost].every(x=>typeof x==='number'&&Number.isFinite(x)&&x>0)
    || cost!<floor || signal.stopLoss>=entry!)return null;
  const tp1Net=(signal.targetTP1/entry!-1)*100-cost!;
  const tp2Net=(signal.targetTP2/entry!-1)*100-cost!;
  const wholeTp2=.5*tp1Net+.5*tp2Net;
  const wholeBreakeven=.5*tp1Net;
  const remainingNetForTarget=(.8-.5*tp1Net)/.5;
  const requiredRemainderPrice=entry!*(1+(remainingNetForTarget+cost!)/100);
  const stopNetPct=(1-signal.stopLoss/entry!)*100+cost!;
  return {entry:entry!,cost:cost!,tp1Net,wholeTp2,wholeBreakeven,remainingNetForTarget,requiredRemainderPrice,
    targetInsidePlan:requiredRemainderPrice<=signal.targetTP2,stopNetPct,
    stopUsdt:Number.isFinite(amount)&&amount>0?amount*stopNetPct/100:null,
    wholeTp2Usdt:Number.isFinite(amount)&&amount>0?amount*wholeTp2/100:null};
}
export function percent(value:number|null|undefined) {return typeof value==='number'&&Number.isFinite(value)?`${value>=0?'+':''}${value.toFixed(3)}%`:'未知';}
