import {readFileSync} from 'node:fs';import assert from 'node:assert/strict';import{CartlyTools,changes,clone}from'../.sites-runtime/tools.mjs';
const cases=JSON.parse(readFileSync(new URL('../.sites-runtime/parity.json',import.meta.url),'utf8'));let calls=0;
for(const test of cases){const session=new CartlyTools();for(let n=0;n<test.calls.length;n++){const[name,args]=test.calls[n],before=clone(session.state),result=session.call(name,args);assert.deepEqual({result,changes:changes(before,session.state),verified:session.verified},test.expected[n],test.name+' / '+name);calls++}}
console.log(`PASS: ${cases.length} sequences, ${calls} tool calls agree with the existing Python tools.`);
