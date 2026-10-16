import assert from 'node:assert/strict';
const data=new Map<string,string>();
Object.defineProperty(globalThis,'localStorage',{configurable:true,writable:true,value:{getItem:(k:string)=>data.get(k)||null,setItem:(k:string,v:string)=>data.set(k,v),removeItem:(k:string)=>data.delete(k)}});
let focusedId:string|null=null;
Object.assign(globalThis,{
 window:{dispatchEvent:(e:any)=>{if(e?.type==='cryptog-focus-message')focusedId=e.detail?.id;return true;}},
 CustomEvent:class{type:string;detail:any;constructor(t:string,o?:any){this.type=t;this.detail=o?.detail;}}
});
const {ingestMessage,messages,readMessage,markAllAsRead,clearReadMessages,focusMessage,getAndClearPendingFocus,isNoiseCategory,clearNoiseMessages,markNoiseAsRead}=await import('../src/services/inbox');
ingestMessage({eventId:'one',title:'Crypto-G 机会观察',body:'not a buy',expiresAt:'1792039000000'});
ingestMessage({eventId:'one',title:'duplicate'});
assert.equal(messages().length,1);assert.equal(messages()[0].body,'not a buy');assert.equal(messages()[0].read,false);
readMessage('one');assert.equal(messages()[0].read,true);
ingestMessage({eventId:'two',title:'Crypto-G 每小时摘要',body:'summary'});assert.equal(messages().find(m=>m.id==='two')?.category,'摘要');
ingestMessage({eventId:'ai_one',eventType:'AI_BUY_ALERT',title:'Crypto-G AI买入预警',body:'AI buy'});assert.equal(messages().find(m=>m.id==='ai_one')?.category,'AI');
assert.equal(isNoiseCategory('观察'), true);
assert.equal(isNoiseCategory('摘要'), true);
assert.equal(isNoiseCategory('失效'), true);
assert.equal(isNoiseCategory('AI'), false);
assert.equal(isNoiseCategory('入场'), false);
markNoiseAsRead();
assert.equal(messages().find(m=>m.id==='two')?.read, true);
clearNoiseMessages();
assert.equal(messages().some(m=>isNoiseCategory(m.category)), false);
focusMessage('ai_one');assert.equal(focusedId,'ai_one');
assert.equal(getAndClearPendingFocus(),'ai_one');
assert.equal(getAndClearPendingFocus(),null);
markAllAsRead();assert.ok(messages().every(m=>m.read));
clearReadMessages();assert.equal(messages().length,0);
console.log('Inbox persistence, deduplication, read history, categories and focusMessage passed');
