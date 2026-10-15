import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {parseCloudSignal} from '../src/services/signalValidity';
const payload=JSON.parse(readFileSync('tests/experimental_payload.json','utf8'));
assert.ok(parseCloudSignal(payload));
const rules=JSON.parse(payload.tradeRules);rules.minNetTp1=.1;
assert.equal(parseCloudSignal({...payload,tradeRules:JSON.stringify(rules)}),null);
console.log('Experimental Python payload accepted; weakened floor rejected');
