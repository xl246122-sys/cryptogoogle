import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {parseWaveMessage} from '../src/services/waveState';
import {parseCloudSignal} from '../src/services/signalValidity';
import {WaveMessageDetails} from '../src/components/WaveMessageDetails';
const fixtures=JSON.parse(readFileSync('tests/fixtures/wave_push_contract.json','utf8'));
for(const raw of fixtures){
 const parsed=parseWaveMessage(raw);assert.ok(parsed);
 assert.equal(parsed.tradeEligible,false);assert.equal(parseCloudSignal(raw),null);
 assert.ok(raw.title.includes('研究观察·未验证'));
 const html=renderToStaticMarkup(<WaveMessageDetails data={parsed} now={parsed.issuedAtMs}/>);
 assert.ok(html.includes(parsed.phase==='INVALIDATED'?'已撤销':'研究观察·未验证'));
 if(parsed.phase==='REBOUND_CONFIRMED'){assert.ok(html.includes('不是保证收益'));assert.equal(parsed.risk?.status,'PASS_RESEARCH_ONLY');}
}
console.log('Live research sender FCM fields parse and render in V1.59; never become BUY.');
