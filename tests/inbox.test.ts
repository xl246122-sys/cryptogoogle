import assert from 'node:assert/strict';
const data=new Map<string,string>();
Object.defineProperty(globalThis,'localStorage',{configurable:true,writable:true,value:{getItem:(k:string)=>data.get(k)||null,setItem:(k:string,v:string)=>data.set(k,v),removeItem:(k:string)=>data.delete(k)}});
let focusedId:string|null=null;
Object.assign(globalThis,{
 window:{dispatchEvent:(e:any)=>{if(e?.type==='cryptog-focus-message')focusedId=e.detail?.id;return true;}},
 CustomEvent:class{type:string;detail:any;constructor(t:string,o?:any){this.type=t;this.detail=o?.detail;}}
});
const {ingestMessage,messages,readMessage,markAllAsRead,clearReadMessages,focusMessage,getAndClearPendingFocus,isNoiseCategory,clearNoiseMessages,markNoiseAsRead}=await import('../src/services/inbox');
ingestMessage({eventId:'one',title:'Crypto-G 条件接近',body:'not a buy',expiresAt:'1792039000000'});
ingestMessage({eventId:'one',title:'duplicate'});
assert.equal(messages().length,1);assert.equal(messages()[0].body,'not a buy');assert.equal(messages()[0].read,false);
readMessage('one');assert.equal(messages()[0].read,true);
ingestMessage({eventId:'two',title:'Crypto-G 每小时摘要',body:'summary'});assert.equal(messages().find(m=>m.id==='two'),undefined);
ingestMessage({eventId:'ai_one',eventType:'AI_BUY_ALERT',title:'Crypto-G AI买入预警',body:'AI buy'});assert.equal(messages().find(m=>m.id==='ai_one')?.category,'AI买入预警');
assert.equal(isNoiseCategory('观察'), true);
assert.equal(isNoiseCategory('摘要'), true);
assert.equal(isNoiseCategory('失效'), true);
assert.equal(isNoiseCategory('AI'), false);
assert.equal(isNoiseCategory('入场'), false);
markNoiseAsRead();
assert.equal(messages().find(m=>m.id==='two'), undefined);
clearNoiseMessages();
assert.equal(messages().some(m=>isNoiseCategory(m.category)), false);
focusMessage('ai_one');assert.equal(focusedId,'ai_one');
assert.equal(getAndClearPendingFocus(),'ai_one');
assert.equal(getAndClearPendingFocus(),null);
markAllAsRead();assert.ok(messages().every(m=>m.read));
clearReadMessages();assert.equal(messages().length,0);
console.log('Inbox persistence, deduplication, read history, categories and focusMessage passed');

const {clearAllMessages,autoClearMessages}=await import('../src/services/inbox');
const now=Date.now();
ingestMessage({eventId:'clear-me',eventType:'AI_BUY_ALERT',timestamp:now});
clearAllMessages(now+1);
ingestMessage({eventId:'clear-me',eventType:'AI_BUY_ALERT',timestamp:now});
assert.equal(messages().length,0);
ingestMessage({eventId:'new',eventType:'AI_BUY_ALERT',timestamp:now+2});
assert.equal(messages().length,1);
autoClearMessages(now+3*60*60*1000+2);
assert.equal(messages().length,1,'Three-hour cycle must not erase persistent history');

const normalize=(await import('../src/services/inbox')).normalizedCategory;
assert.equal(normalize('阶段预警'),'准备入场');
assert.equal(normalize('退出'),'离场');
assert.equal(normalize('失效','机会失效'),'');
ingestMessage({eventId:'test-hidden',signalType:'BUY',title:'测试买入',timestamp:Date.now()+20000000});
assert.equal(messages().some(m=>m.id==='test-hidden'),false);

const {deleteMessage}=await import('../src/services/inbox');
ingestMessage({eventId:'swipe-delete',eventType:'AI_BUY_ALERT',timestamp:Date.now()+30000000});
assert.ok(messages().some(m=>m.id==='swipe-delete'));
deleteMessage('swipe-delete');
ingestMessage({eventId:'swipe-delete',eventType:'AI_BUY_ALERT',timestamp:Date.now()+30000000});
assert.equal(messages().some(m=>m.id==='swipe-delete'),false,'Deleted messages must not return after cloud synchronization');

const diagnostic={testId:'diagnostic-visible',eventType:'DIAGNOSTIC_TEST',title:'买入预警测试（非真实信号）',body:'只检查通知、声音和振动，不需要交易。',timestamp:Date.now()+31000000};
ingestMessage(diagnostic);ingestMessage(diagnostic);
assert.equal(messages().filter(m=>m.id===diagnostic.testId).length,1);
assert.equal(messages().find(m=>m.id===diagnostic.testId)?.category,'推送测试');
focusMessage(diagnostic.testId);assert.equal(getAndClearPendingFocus(),diagnostic.testId);
readMessage(diagnostic.testId);assert.ok(messages().find(m=>m.id===diagnostic.testId)?.read);
assert.equal(messages().find(m=>m.id===diagnostic.testId)?.body,diagnostic.body);
const {parseCloudSignal}=await import('../src/services/signalValidity');
assert.equal(parseCloudSignal({...diagnostic,signalType:'BUY',symbol:'BTCUSDT'}),null);
