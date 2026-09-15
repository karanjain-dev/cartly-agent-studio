"""Two independent, blind model decisions per scenario. Never edits scenarios."""
import argparse
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from simulation.model_client import ModelClient, ModelError, ROOT

INSTRUCTIONS='''You independently adjudicate a Cartly customer request. Read ONLY the provided policy, the world data for this user, and full hidden facts. No tools, outside assumptions, or other cases. Assume the customer will provide their known credentials and explicitly confirm an allowed action after its exact amount/method is explained. Adjudicate the end of this conversation, not hypothetical pickup completion. Never invent facts. If behavior says the customer refuses evidence, do not assume they later upload it. An item cannot be refunded twice. Use database prices. Report ambiguities honestly. All reason values must be exactly change_of_mind, damaged, defective, wrong_item, or cancellation.
Return JSON with resolution, changes, refund, no_other_changes, explanation, rules. resolution is one of return_scheduled, refunded, cancelled, address_updated, coupon_issued, escalated, declined. changes is a list of {table,operation,key,values}. Omit generated IDs and timestamps. Use ONLY the following canonical business-change shapes:
- return: table returns, operation insert, key {order_id,item_id}, values {reason,pickup_status:"scheduled"}.
- refund: table refunds, operation insert, key {order_id,item_id}, values {reason,amount,shipping_refunded,method,status:"completed"}. item_id is null for cancellation. method is UPI, Card, or Cartly Wallet.
- cancellation also updates table orders, key {order_id}, values {status:"Cancelled"}.
- address: table orders, operation update, key {order_id}, values {delivery_address: the complete provided address object}.
- coupon: table coupons, operation insert, key {order_id}, values {amount:100}; also update orders with {coupon_issued:true,coupon_amount:previous+100}.
- escalation: table escalations, operation insert, key {order_id: requested order ID}, values {required_nonempty:["user_request","facts_found","rule_triggered","what_user_was_told"]}. List escalation rules separately under rules, not inside changes.
- decline: no changes, no refund.
refund is null unless a refund is issued or a return is scheduled; otherwise it is {amount,method,timing} with timing immediate or after_pickup. A return's refund is a future quote, not an immediate database refund. no_other_changes is true. explanation is concise. rules is a list of supporting rule numbers. If policy leaves multiple acceptable choices, select one and explain. Do not create any action not justified by the policy.'''

def payload_for(scenario,world,policy):
    uid=scenario['user_id'];orders=[o for o in world['orders'] if o['user_id']==uid];ids={o['order_id'] for o in orders}
    return {'policy':policy,'world_data_for_user':{'config':world['config'],'user':next(u for u in world['users'] if u['user_id']==uid),
        'orders':orders,'order_items':[i for i in world['order_items'] if i['order_id'] in ids],
        'refunds':[r for r in world['refunds'] if r['user_id']==uid],
        'returns':[r for r in world['returns'] if r['order_id'] in ids],
        'serviceable_pincodes':world['serviceable_pincodes']},'full_hidden_facts':scenario['hidden_facts']}

def canonical(value):
    d={k:value.get(k) for k in ['resolution','changes','refund','no_other_changes']}
    if isinstance(d['changes'],list):d['changes']=sorted(d['changes'],key=lambda x:json.dumps(x,sort_keys=True))
    return d

def run(*,model='gpt-4.1-mini',workers=4,output_dir=None):
    scenarios_path=ROOT/'scenarios/scenarios.json';raw=scenarios_path.read_bytes();scenarios=json.loads(raw)
    world={n:json.loads((ROOT/'data'/(n+'.json')).read_text()) for n in ['config','users','orders','order_items','refunds','returns','serviceable_pincodes']}
    policy=(ROOT/'policy.md').read_text();out=Path(output_dir or ROOT/'scenarios/self_check');out.mkdir(parents=True,exist_ok=True)
    # All requests are prepared without labels/outcomes. Each pass is a fresh API call;
    # neither decision sees the other decision. Expected outcomes are read only after.
    requests=[(s,pass_no,payload_for(s,world,policy)) for s in scenarios for pass_no in [1,2]]
    def check(request):
        s,pass_no,payload=request;path=out/f'{s["scenario_id"]}_pass{pass_no}.json'
        digest=hashlib.sha256((INSTRUCTIONS+json.dumps(payload,sort_keys=True)).encode()).hexdigest()
        if path.exists():
            previous=json.loads(path.read_text())
            if previous.get('input_sha256')==digest and previous.get('requested_model')==model and previous.get('status')=='completed':return previous
        record={'scenario_id':s['scenario_id'],'pass':pass_no,'split':s['split'],'input_sha256':digest,'requested_model':model}
        try:
            response=ModelClient(model).complete(INSTRUCTIONS,payload,max_tokens=2600)
            decision=response.pop('value');record.update(status='completed',decision=decision,**response)
        except ModelError as exc:record.update(status='error',error=str(exc))
        path.write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n');return record
    records=[]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures=[pool.submit(check,r) for r in requests]
        for f in as_completed(futures):
            records.append(f.result())
            if len(records)%10==0:print(f'Independent decisions recorded: {len(records)}/80',flush=True)
    records.sort(key=lambda r:(r['scenario_id'],r['pass']))
    disagreements=[];errors=[]
    for s in scenarios:
        for r in [r for r in records if r['scenario_id']==s['scenario_id']]:
            if r['status']!='completed':errors.append({'scenario_id':s['scenario_id'],'pass':r['pass'],'error':r['error']});continue
            if not any(canonical(r['decision'])==canonical(expected) for expected in s['acceptable_end_states']):
                disagreements.append({'scenario_id':s['scenario_id'],'split':s['split'],'pass':r['pass'],'expected':s['acceptable_end_states'],'decision':r['decision']})
    report={'scenario_sha256':hashlib.sha256(raw).hexdigest(),'policy_version':'v0.5','model':model,'required_calls':80,
            'completed_calls':sum(r['status']=='completed' for r in records),'error_count':len(errors),'errors':errors,
            'disagreeing_scenarios':sorted({d['scenario_id'] for d in disagreements}),'disagreement_count':len(disagreements),'disagreements':disagreements,
            'comparison':'Exact canonical business changes; generated IDs/timestamps excluded. No expected outcome was sent to either model call.'}
    (out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    assert scenarios_path.read_bytes()==raw,'Self-check must not edit scenarios'
    # Console report intentionally excludes heldout content.
    print(json.dumps({k:v for k,v in report.items() if k not in ['disagreements','errors']},indent=2))
    if errors:print('Model errors:',json.dumps(errors[:2]))
    return 1 if errors else 0

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--model',default='gpt-4.1-mini');p.add_argument('--workers',type=int,default=4)
    a=p.parse_args();raise SystemExit(run(model=a.model,workers=a.workers))
