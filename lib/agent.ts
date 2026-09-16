import policy from './reference/policy.json';
import schemas from './reference/tool-schema.json';
import {CartlyTools,clone,changes,WRITES} from './tools';
import {runtime,persist,Session,snapshot,Event,setBusy} from './session';
const labels:Record<string,string>={verify_user:'Verify customer identity',get_order:'Fetch order details',list_orders:'Look up customer orders',search_policy:'Search the support policy',check_serviceability:'Check delivery coverage',get_refund_history:'Check refund history',check_evidence:'Check uploaded evidence',update_address:'Update delivery address',cancel_order:'Cancel the order',create_return:'Create a return pickup',issue_refund:'Issue the refund',issue_coupon:'Issue a ₹100 coupon',escalate_to_human:'Queue a human handoff'};
function cost(u:any){const input=u.input_tokens||0,cached=u.input_tokens_details?.cached_tokens||0,write=u.input_tokens_details?.cache_write_tokens||0;return ((input-cached-write)*10+cached+write*12.5+(u.output_tokens||0)*50)/1e6}
export async function runAgent(id:string,s:Session,message:string,emit:(e:any)=>void,signal:AbortSignal){
 const activity=(type:string,title:string,detail:string,data?:unknown,status='complete'):Event=>{const e={id:crypto.randomUUID(),type,title,detail,data,status};s.events.push(e);emit({type:'activity',data:e});return e};
 const update=(e:Event,status:string,data?:unknown)=>{e.status=status;if(data!==undefined)e.data=data;emit({type:'activity',data:e})};
 const tools=new CartlyTools(s.state,s.verified);let modelEvent:Event|null=null;
 s.turns++;s.messages.push({role:'user',content:message});s.input.push({role:'user',content:message});emit({type:'message',data:{role:'user',content:message}});
 activity('context','Load conversation context',`${s.messages.length-1} previous messages · ${s.verified?'customer '+s.verified+' verified':'identity not verified'}`,{previous_messages:s.messages.length-1,tool_results:s.toolLog.length,verified_user:s.verified,memory:'Session history only. No long-term memory lookup.'});
 activity('policy','Include the full policy',`Policy ${policy.version} and the reference date are included in this request.`,{policy_version:policy.version,prompt:'agent_v1.1',today:s.state.config.today,timezone:'IST',source:'Full system prompt; this is not a search_policy tool call.'});
 await persist(id,s);
 try{for(let round=0;round<20;round++){
  if(signal.aborted)throw Error('The connection was interrupted. Start a new conversation to continue.');
  const body={model:'gpt-6-astra',input:s.input,instructions:policy.prompt+'\n\nYou can read policy and order facts, but you cannot execute returns, refunds, cancellations, address changes, or coupons. Tell the customer to use the exact proposal and approval controls in the Cartly app.',tools:(schemas as any[]).filter(tool=>!WRITES.has(tool.name)),parallel_tool_calls:false,max_output_tokens:8192,reasoning:{effort:'high'},store:false,include:['reasoning.encrypted_content']};
  const payload=JSON.stringify(body);
  // Every input byte bounds at most one token; use the highest configured input rate.
  const reserve=new TextEncoder().encode(payload).length*12.5/1e6+8192*50/1e6;
  const limit=Number(runtime().DEMO_BUDGET_USD||'3');
  await runtime().DB.prepare("INSERT OR IGNORE INTO demo_budget (id, spent, reserved) VALUES ('shared_demo', 0, 0)").run();
  const held=await runtime().DB.prepare("UPDATE demo_budget SET reserved = reserved + ? WHERE id = 'shared_demo' AND spent + reserved + ? <= ?").bind(reserve,reserve,Number.isFinite(limit)?limit:3).run();
  if(!held.meta.changes)throw Error('The shared demo has reached its spending allowance. No new model request was made.');
  modelEvent=activity('model','Agent is responding',`Model ${s.model} · request ${round+1} in this turn`,undefined,'running');await persist(id,s);
  let settlement=reserve,observed=false;let raw:any;
  try{const r=await fetch('https://api.openai.com/v1/responses',{method:'POST',headers:{Authorization:`Bearer ${runtime().OPENAI_API_KEY}`,'Content-Type':'application/json'},body:payload,signal:AbortSignal.any([signal,AbortSignal.timeout(180000)])});
   if(!r.ok){settlement=0;const status=r.status;await r.body?.cancel();throw Error(status===429?'The model is currently rate-limited or out of credit. Try again later.':status===401?'The hosted API connection needs attention.':'The model service could not complete this request. Please try again later.')}
   raw=await r.json();if(raw.usage){settlement=cost(raw.usage);s.cost+=settlement;observed=true}if(raw.status!=='completed')throw Error('The model response was incomplete. Start a new conversation to continue.');
  }finally{await runtime().DB.prepare("UPDATE demo_budget SET reserved = MAX(0, reserved - ?), spent = spent + ? WHERE id = 'shared_demo'").bind(reserve,settlement).run();}
  s.model=raw.model||s.model;update(modelEvent,'complete',{model:s.model,usage:raw.usage||null,estimated_cost_usd:observed?settlement:null});
  s.input.push(...(raw.output||[]));const calls:any[]=[];let said=false;
  for(const item of raw.output||[]){if(item.type==='function_call')calls.push(item);if(item.type==='message'){const text=(item.content||[]).filter((c:any)=>c.type==='output_text').map((c:any)=>c.text).join('');if(text){said=true;s.messages.push({role:'assistant',content:text});emit({type:'message',data:{role:'assistant',content:text}})}}}
  if(!calls.length){if(!said)throw Error('The agent returned no message. Start a new conversation to continue.');await persist(id,s);emit({type:'snapshot',data:snapshot(s)});return}
  for(const call of calls){let args:any;try{args=JSON.parse(call.arguments)}catch{args={invalid_json:call.arguments}}const event=activity('tool',labels[call.name]||call.name,call.name,{arguments:args},'running');await persist(id,s);
   const before=clone(tools.state),result=WRITES.has(call.name)?{ok:false,error:{message:'This action requires an exact proposal and customer approval in the Cartly app.'}}:tools.call(call.name,args),delta=changes(before,tools.state);s.state=tools.state;s.verified=tools.verified;s.calls++;if(!WRITES.has(call.name))s.toolLog.push(tools.logs[tools.logs.length-1]);
   s.input.push({type:'function_call_output',call_id:call.call_id,output:JSON.stringify(result)});
   if(result.ok&&call.name==='get_order'&&!s.seenOrders.includes(args.order_id))s.seenOrders.push(args.order_id);
   update(event,result.ok?'complete':'error',{arguments:args,...result});if(delta.length)activity('state','Save session changes',`${delta.length} change${delta.length===1?'':'s'} applied to this demo session`,delta);
   if(result.ok&&call.name==='escalate_to_human')s.ended=true;
   await persist(id,s);emit({type:'snapshot',data:snapshot(s,true)});
  }
 }
 throw Error('The agent reached its tool-call limit. Start a new conversation to continue.');
 }catch(e:any){if(modelEvent?.status==='running')update(modelEvent,'error');const message=e.name==='AbortError'?'The connection was interrupted. Start a new conversation to continue.':e.message;s.ended=true;activity('error','Conversation paused',message);emit({type:'error',message});
 }finally{if(s.turns>=20)s.ended=true;await persist(id,s);await setBusy(id,0);emit({type:'snapshot',data:snapshot(s)});emit({type:'done'})}
}
