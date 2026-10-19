import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {summarizeFills} from '../src/services/executionLedger';
import {paperAction,paperSummary,LEGACY_PAPER_STRATEGY} from '../src/services/quickPaper';
import type {JournalEntry} from '../src/services/modelLibrary';
const cases=JSON.parse(readFileSync(new URL('./stage_b_cashflows.json',import.meta.url),'utf8'));
for(const c of cases)test(`shared cash flow: ${c.name}`,()=>{
 const r=summarizeFills(c.fills);
 assert.equal(r.closed,true);assert.ok(Math.abs(r.wholeTradeNetPct!-c.expectedPct)<1e-8);
});
test('paper preserves entry cost through split sells and isolates legacy',()=>{
 const cost={costModelVersion:'cost-v2.1',frictionPct:.6,applicableAtMs:1000};
 const buy=paperAction('BUY',100,1000,1000,[],'b',cost);
 const rows:JournalEntry[]=[{action:{...buy,eventId:'b'},status:'acked'}];
 const sell=paperAction('SELL',101,2000,2000,rows,'s');
 rows.push({action:{...sell,eventId:'s'},status:'acked'});
 const remaining=paperAction('SELL',101,3000,3000,rows,'s2');
 rows.push({action:{...remaining,eventId:'s2'},status:'acked'});
 assert.ok(Math.abs(paperSummary(rows).realized-2)<1e-8);
 rows.push({action:{...buy,eventId:'legacy',strategy:LEGACY_PAPER_STRATEGY},status:'acked'});
 assert.equal(paperSummary(rows).quantity,0);assert.equal(paperSummary(rows,LEGACY_PAPER_STRATEGY).quantity,5);
});
