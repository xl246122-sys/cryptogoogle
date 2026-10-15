import test from 'node:test';
import assert from 'node:assert/strict';
import {paperAction,paperSummary} from '../src/services/quickPaper';
import type {JournalEntry} from '../src/services/modelLibrary';
const rows:JournalEntry[]=[];
const add=(side:'BUY'|'SELL',price:number,time:number)=>{const action=paperAction(side,price,time,time,rows,'paper-test');rows.push({action:{...action,eventId:String(time)},status:'pending'});return action;};
test('fixed buys, partial sale, remaining liquidation and cost accounting',()=>{
 add('BUY',100,1000);add('BUY',100,2000);
 assert.equal(paperSummary(rows).quantity,10);
 const partial=add('SELL',125,3000);assert.equal(partial.positionSize,400);
 assert.equal(paperSummary(rows).quantity,6);
 add('SELL',50,4000);
 assert.equal(paperSummary(rows).quantity,0);
 assert.throws(()=>add('SELL',50,5000));
 assert.ok(Math.abs(paperSummary(rows).realized-(-200.99))<1e-8);
});
test('stale invalid and future quote are rejected',()=>{
 for(const [price,at,now] of [[0,1,1],[NaN,1,1],[100,1,10002],[100,2,1]])assert.throws(()=>paperAction('BUY',price,at,now,[],'paper-test'));
});
test('real trades and rejected simulation do not become paper inventory',()=>{
 const action=paperAction('BUY',100,1,1,[],'paper-test');
 assert.equal(paperSummary([{action:{...action,eventId:'x'},status:'rejected'}]).quantity,0);
 assert.equal(paperSummary([{action:{...action,strategy:'REAL',eventId:'x'},status:'acked'}]).quantity,0);
});

