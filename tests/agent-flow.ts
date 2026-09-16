import assert from 'node:assert/strict';
import {test} from 'node:test';
import {runAgent} from '../lib/agent';
import {fresh,snapshot,persist} from '../lib/session';
import {agentTool,createProposal,acceptAndExecute,decisionFor,invalidateProposal} from '../lib/guarded-flow';
import {PATCH} from '../app/api/proposal/route';
import {env,sqlite} from './mock-runtime';
import reference from '../lib/reference/policy.json';
import {WRITES} from '../lib/tools';

const request={kind:'return' as const,orderId:'O0011',itemId:'I0011',reason:'change_of_mind' as const,unused:true};
function verified(user='U018'){const s=fresh();s.verified=user;return s}
const fcall=(name:string,args:unknown)=>({type:'function_call',call_id:crypto.randomUUID(),name,arguments:JSON.stringify(args)});
const reply=(text:string)=>({type:'message',content:[{type:'output_text',text}]});
let replies:any[]=[],bodies:any[]=[];
globalThis.fetch=async(_url:any,options:any)=>{
 bodies.push(JSON.parse(options.body));const output=replies.shift();assert.ok(output,'Unexpected model call');
 return Response.json({status:'completed',model:'gpt-6-astra',output:[output],usage:{input_tokens:100,output_tokens:10}});
};
function save(id:string,s:any,busy=0){sqlite.prepare('INSERT OR REPLACE INTO demo_sessions(id,payload,busy) VALUES (?,?,?)').run(id,JSON.stringify(s),busy)}
function http(id:string,p:any,overrides:any={}) {return new Request('https://cartly.example/api/proposal',{method:'PATCH',headers:{origin:'https://cartly.example',cookie:'cartly_session='+id,'content-type':'application/json'},body:JSON.stringify({proposalId:p.id,termsHash:p.termsHash,accept:true,...overrides})})}

test('multi-turn chat -> verification -> order -> question -> proposal -> approval -> continued chat',async()=>{
 const s=fresh(),events:any[]=[];save('one',s,1);
 replies=[fcall('verify_user',{user_id:'U018',email:'customer018@example.com'}),fcall('get_order',{order_id:'O0011'}),reply('Is the kurta unused?')];
 await runAgent('one',s,'I want to return O0011. My user ID is U018 and email is customer018@example.com.',e=>events.push(e),new AbortController().signal);
 assert.equal(s.messages.at(-1)?.content,'Is the kurta unused?');
 replies=[fcall('decide_policy',request),fcall('propose_action',request)];
 await runAgent('one',s,'Yes, it is unused.',e=>events.push(e),new AbortController().signal);
 assert.equal(s.proposal?.decision.amount,1400);assert.equal(s.proposal?.decision.method,'UPI');
 assert.equal(snapshot(s).changes.length,0);assert.match(s.proposal!.terms,/unused/);
 assert.ok(events.some(e=>e.type==='activity'&&e.data.type==='guardrail'&&e.data.data?.rule==='E9/H2'));
 await acceptAndExecute(s,s.proposal!.id,s.proposal!.termsHash,true);
 assert.equal(s.proposal!.status,'executed');
 assert.equal(s.state.returns.length,fresh().state.returns.length+1);
 assert.equal(s.state.refunds.length,fresh().state.refunds.length);
 assert.ok(s.input.some(x=>x.role==='assistant'&&x.content.includes('Return created')));
 replies=[reply('The refund will happen automatically after pickup.')];
 await runAgent('one',s,'When will my refund arrive?',()=>{},new AbortController().signal);
 assert.equal(s.ended,false);assert.equal(events.at(-1).type,'done');
 assert.ok(bodies.every(b=>b.instructions.startsWith(reference.prompt)&&b.tools.some((t:any)=>t.name==='propose_action')&&!b.tools.some((t:any)=>WRITES.has(t.name))));
 assert.equal(sqlite.prepare('SELECT busy FROM demo_sessions WHERE id=?').get('one')?.busy,0);
 assert.equal((sqlite.prepare('SELECT * FROM demo_budget').get() as any).reserved,0);
});
test('identity is not inferred from the selected demo',async()=>{
 const s=fresh();assert.equal(snapshot(s).verifiedUser,null);assert.equal(snapshot(s).orders.length,0);
 assert.equal((await agentTool(s,'get_order',{order_id:'O0011'})).error.message,'verification required');
 await assert.rejects(createProposal(s,request),/verification required/);
});
test('cross-customer and nonexistent order have identical error',async()=>{
 const s=verified();
 assert.equal((await agentTool(s,'get_order',{order_id:'O0075'})).error.message,(await agentTool(s,'get_order',{order_id:'DOES-NOT-EXIST'})).error.message);
 assert.equal((await agentTool(s,'verify_user',{user_id:'U014',email:'customer014@example.com'})).ok,false);
});
test('model cannot directly mutate orders, even with confirmed=true',async()=>{
 const s=verified();
 for(const name of WRITES)assert.equal((await agentTool(s,name,{order_id:'O0011',item_id:'I0011',reason:'damaged',confirmed:true})).ok,false);
 assert.equal(snapshot(s).changes.length,0);assert.equal(s.toolLog.length,WRITES.size);
});
test('wrong terms hash fails without changes',async()=>{
 const s=verified(),p=await createProposal(s,request);
 await assert.rejects(acceptAndExecute(s,p!.id,'wrong',true),/terms/);assert.equal(snapshot(s).changes.length,0);
});
test('another message invalidates the old proposal',async()=>{
 const s=verified(),p=await createProposal(s,request);invalidateProposal(s);
 await assert.rejects(acceptAndExecute(s,p!.id,p!.termsHash,true),/no longer available/);assert.equal(snapshot(s).changes.length,0);
});
test('double acceptance is idempotent',async()=>{
 const s=verified(),p=await createProposal(s,request);
 await acceptAndExecute(s,p!.id,p!.termsHash,true);const calls=s.calls;
 await acceptAndExecute(s,p!.id,p!.termsHash,true);assert.equal(s.calls,calls);assert.equal(s.state.returns.filter((r:any)=>r.item_id==='I0011').length,1);
});
test('rejection leaves order unchanged and chat continues',async()=>{
 const s=verified(),p=await createProposal(s,request);await acceptAndExecute(s,p!.id,p!.termsHash,false);
 assert.equal(s.proposal!.status,'rejected');assert.equal(snapshot(s).changes.length,0);assert.equal(s.ended,false);
});
test('changed database values make proposal stale',async()=>{
 const s=verified(),p=await createProposal(s,request);s.state.order_items.find((i:any)=>i.item_id==='I0011').price++;
 await acceptAndExecute(s,p!.id,p!.termsHash,true);assert.equal(s.proposal!.status,'stale');assert.equal(s.state.returns.length,fresh().state.returns.length);
});
test('amount, method and shipping come from database',()=>{
 const s=verified();const d=decisionFor(s,{...request,reason:'damaged',amount:1} as any);
 assert.equal(d.amount,1548);assert.equal(d.method,'UPI');assert.equal(d.shippingRefunded,true);
 s.state.refunds.push({order_id:'O0011',item_id:'OTHER',user_id:'U018',status:'completed',reason:'damaged',date:s.state.config.today,amount:100,shipping_refunded:true});
 assert.equal(decisionFor(s,{...request,reason:'damaged'}).amount,1499);
});
test('windows, photo, history, cumulative limit and wrong-item checks',()=>{
 const s=verified(),o=s.state.orders.find((o:any)=>o.order_id==='O0011'),i=s.state.order_items.find((i:any)=>i.item_id==='I0011');
 o.actual_delivery_date='2026-09-04';assert.equal(decisionFor(s,request).outcome,'decline');
 assert.equal(decisionFor(s,{...request,reason:'damaged'}).outcome,'escalate');
 o.actual_delivery_date='2026-09-05';i.price=2500;i.evidence_photo_uploaded=false;
 assert.deepEqual(decisionFor(s,{...request,reason:'damaged'}).rules,['E6']);
 i.evidence_photo_uploaded=true;i.price=6000;assert.deepEqual(decisionFor(s,{...request,reason:'damaged'}).rules,['E9','H2']);
 i.price=1499;assert.deepEqual(decisionFor(s,{...request,reason:'wrong_item'}).rules,['E11']);
 for(let n=0;n<3;n++)s.state.refunds.push({user_id:'U018',order_id:'OTHER',reason:'damaged',status:'completed',date:s.state.config.today});
 assert.deepEqual(decisionFor(s,request).rules,['E10']);
});
test('unused fact is required and non-returnable categories are checked',()=>{
 const s=verified();assert.equal(decisionFor(s,{...request,unused:undefined}).outcome,'clarify');
 assert.equal(decisionFor(s,{...request,unused:false}).outcome,'decline');
 s.state.order_items.find((i:any)=>i.item_id==='I0011').category='innerwear';
 assert.deepEqual(decisionFor(s,request).rules,['E2']);
 assert.deepEqual(decisionFor(s,{...request,reason:'damaged'}).rules,['E2']);
});
test('under ₹500 claim uses immediate refund and COD wallet',async()=>{
 const s=verified(),i=s.state.order_items.find((i:any)=>i.item_id==='I0011'),o=s.state.orders.find((o:any)=>o.order_id==='O0011');i.price=399;o.payment_method='COD';
 const p=await createProposal(s,{...request,reason:'defective'});assert.equal(p!.decision.action,'issue_refund');assert.equal(p!.decision.amount,448);assert.equal(p!.decision.method,'Cartly Wallet');
 await acceptAndExecute(s,p!.id,p!.termsHash,true);assert.equal(s.state.refunds.at(-1).amount,448);assert.equal(s.state.returns.length,fresh().state.returns.length);
});
test('Packed cancellation above ₹5,000 is exempt and still requires approval',async()=>{
 const s=verified('U014');s.state.order_items.find((i:any)=>i.order_id==='O0075').price=7000;
 const p=await createProposal(s,{kind:'cancel',orderId:'O0075'});assert.equal(p!.decision.amount,7049);
 assert.equal(s.state.orders.find((o:any)=>o.order_id==='O0075').status,'Packed');
 await acceptAndExecute(s,p!.id,p!.termsHash,true);assert.equal(s.state.orders.find((o:any)=>o.order_id==='O0075').status,'Cancelled');
});
test('late coupon threshold and one per order',async()=>{
 const s=verified('U031'),p=await createProposal(s,{kind:'coupon',orderId:'O0092'});assert.equal(p!.decision.amount,100);
 await acceptAndExecute(s,p!.id,p!.termsHash,true);assert.equal(decisionFor(s,{kind:'coupon',orderId:'O0092'}).outcome,'decline');
 const clean=verified('U031');clean.state.orders.find((o:any)=>o.order_id==='O0092').promised_delivery_date='2026-09-10';
 assert.equal(decisionFor(clean,{kind:'coupon',orderId:'O0092'}).outcome,'decline');
});
test('address requires Placed, full address and serviceable pincode',async()=>{
 const s=verified('U014'),o=s.state.orders.find((o:any)=>o.order_id==='O0075'),address={...o.delivery_address};
 assert.equal(decisionFor(s,{kind:'address',orderId:o.order_id,address}).outcome,'decline');
 o.status='Placed';assert.equal(decisionFor(s,{kind:'address',orderId:o.order_id}).outcome,'clarify');
 const p=await createProposal(s,{kind:'address',orderId:o.order_id,address});assert.equal(p!.decision.action,'update_address');
 await acceptAndExecute(s,p!.id,p!.termsHash,true);assert.deepEqual(o.delivery_address,address);
});
test('concurrent approval requests serialize and cannot create duplicate returns',async()=>{
 const id='11111111-1111-1111-1111-111111111111',s=verified(),p=await createProposal(s,request);save(id,s);
 const responses=await Promise.all([PATCH(http(id,p)),PATCH(http(id,p))]);
 assert.equal(responses.filter(r=>r.ok).length,1);assert.equal(responses.filter(r=>r.status===409).length,1);
 const retry=await PATCH(http(id,p));assert.equal(retry.status,200);
 const saved=JSON.parse((sqlite.prepare('SELECT payload FROM demo_sessions WHERE id=?').get(id) as any).payload);
 assert.equal(saved.state.returns.filter((r:any)=>r.item_id==='I0011').length,1);
 const wrongOrigin=new Request(http(id,p),{headers:{origin:'https://other.example'}});assert.equal((await PATCH(wrongOrigin)).status,403);
});
test('pending chat lock blocks acceptance and snapshot hides internal input',async()=>{
 const id='22222222-2222-2222-2222-222222222222',s=verified(),p=await createProposal(s,request);save(id,s,1);
 assert.equal((await PATCH(http(id,p))).status,409);
 assert.ok(!('input' in snapshot(s)));assert.ok(!JSON.stringify(snapshot(s)).includes('edge_case'));
});
test('shared spending gate stops model calls and releases lock',async()=>{
 env.DEMO_BUDGET_USD='0';const s=fresh(),events:any[]=[],before=bodies.length;save('blocked',s,1);
 await runAgent('blocked',s,'Hello',e=>events.push(e),new AbortController().signal);
 assert.equal(bodies.length,before);assert.ok(events.some(e=>e.type==='error'&&e.message.includes('spending allowance')));
 assert.equal(sqlite.prepare('SELECT busy FROM demo_sessions WHERE id=?').get('blocked')?.busy,0);
 env.DEMO_BUDGET_USD='3';
});
