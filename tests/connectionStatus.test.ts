import test from 'node:test';
import assert from 'node:assert/strict';
import {parseConnectionStatus} from '../src/services/connectionStatus';
import {editedConnection,saveConnection} from '../src/services/serverConnection';
test('status distinguishes this phone, other device, unknown and stale market',()=>{
 const m={ok:true,schema:1,runtimeHealthy:true,feedHealthy:true,snapshot:{atMs:10000},exitNotificationHealthy:true};
 const d={ok:true,registered:true,matchesCurrentDevice:true,pushEnabled:true};
 assert.equal(parseConnectionStatus(m,d,10001).binding,'bound');
 assert.equal(parseConnectionStatus(m,{...d,matchesCurrentDevice:false},10001).binding,'other');
 assert.equal(parseConnectionStatus(m,{...d,matchesCurrentDevice:null},10001).binding,'unknown');
 assert.equal(parseConnectionStatus(m,{...d,registered:false},10001).binding,'unbound');
 assert.equal(parseConnectionStatus(m,d,20001).backendHealthy,false);
 assert.equal(parseConnectionStatus(m,d,1).backendHealthy,false);
 assert.throws(()=>parseConnectionStatus(m,{ok:true}));
});
test('blank credential preserves saved secret only on same server',()=>{
 const original=globalThis.localStorage;const values=new Map<string,string>();
 Object.defineProperty(globalThis,'localStorage',{configurable:true,value:{getItem:(k:string)=>values.get(k),setItem:(k:string,v:string)=>values.set(k,v)}});
 try{
  saveConnection({url:'https://example.test',token:'a'.repeat(32)});
  assert.equal(editedConnection('https://example.test','').token,'a'.repeat(32));
  assert.throws(()=>editedConnection('https://other.test',''));
  assert.throws(()=>editedConnection('https://example.test/path',''));
 }finally{Object.defineProperty(globalThis,'localStorage',{configurable:true,value:original});}
});
