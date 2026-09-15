"""Blind, schema-constrained scenario recheck. Does not modify scenario fixtures."""
import argparse
import hashlib
import json
import re
from collections import Counter,defaultdict
from concurrent.futures import ThreadPoolExecutor,as_completed
from pathlib import Path
from simulation.model_client import ModelClient,ModelError,ROOT
from simulation.self_check import payload_for

FIELDS=('outcome_type','order_id','item_id','reason','refund_amount','refund_method','shipping_refunded','escalation_rule')
OUTCOMES=['return','immediate_refund','cancel','address_update','coupon','escalate','decline_no_change','clarify_then_resolve']
SCHEMA={'type':'object','additionalProperties':False,'required':list(FIELDS),'properties':{
 'outcome_type':{'type':'string','enum':OUTCOMES},'order_id':{'type':['string','null']},'item_id':{'type':['string','null']},
 'reason':{'type':['string','null'],'enum':['change_of_mind','damaged','defective','wrong_item','cancellation',None]},
 'refund_amount':{'type':['number','null']},'refund_method':{'type':['string','null'],'enum':['UPI','Card','Cartly Wallet',None]},
 'shipping_refunded':{'type':'boolean'},'escalation_rule':{'type':['string','null']}}}
INSTRUCTIONS='''Independently decide the correct FINAL action for this Cartly customer using ONLY the provided policy, the user's world data and the full hidden facts. You have no prior decision, expected answer or scenario labels. Treat all hidden facts as known after necessary clarification. Assume the customer verifies and explicitly confirms an allowed action after its exact amount and method are explained. If a hidden fact says the customer will not supply evidence, do not invent an upload. Evaluate the current conversation, not a future pickup event. Never use user-stated prices instead of database prices. Read all applicable rules and the complete facts before choosing.
Return exactly the eight fields in the supplied JSON schema, without explanation or extra fields.
Conventions, identical for all cases:
- outcome_type: return means schedule pickup with an automatic later refund; immediate_refund means refund now with no pickup; cancel, address_update, coupon, escalate and decline_no_change are final actions. clarify_then_resolve is reserved for genuinely missing necessary facts even after reading all hidden facts, not merely an initially vague message whose hidden facts resolve it.
- order_id: the order the customer requests, even if inaccessible. Find it in the hidden facts. Never substitute another order owned by the user.
- item_id and reason: populated only for return/immediate_refund. For cancel item_id=null and reason=cancellation. For all other outcomes both are null. reason uses the provided enum.
- refund_amount and refund_method: the exact current or scheduled refund for return/immediate_refund/cancel; null for all other outcomes. A coupon is not a refund, so these fields are null for coupon.
- shipping_refunded: whether shipping is INCLUDED in this current or scheduled refund, not whether a prior shipping refund exists. False if no refund. Shipping can be refunded only once.
- escalation_rule: null unless outcome_type=escalate. Use the specific rule that requires escalation (e.g. H1, H2, E10, G2 or A3), not G3 (handoff contents). Prefer H2 to E9 for cumulative-order limits; do not substitute generic G2 for a more specific trigger.
Do not output intermediate actions, read-tool calls, wording, or database mutations. Do not infer policy ambiguity just because the customer is vague; use the full facts.'''


def select_fields(value):return {k:value[k] for k in FIELDS}
def target_order_id(s):
    refs=[]
    for f in s['hidden_facts']:refs.extend(re.findall(r'\bO\d{4}\b',f['fact']))
    refs=list(dict.fromkeys(refs))
    if len(refs)!=1:raise ValueError(s['scenario_id']+': primary order reference must be unambiguous')
    return refs[0]

def projected_expected(s,world):
    orders={o['order_id']:o for o in world['orders']};oid=target_order_id(s)
    mapping={'return_scheduled':'return','refunded':'immediate_refund','cancelled':'cancel','address_updated':'address_update',
             'coupon_issued':'coupon','escalated':'escalate','declined':'decline_no_change'}
    output=[]
    for state in s['acceptable_end_states']:
        d=dict.fromkeys(FIELDS);d.update(outcome_type=mapping[state['resolution']],order_id=oid,shipping_refunded=False)
        mutations=state['changes'];refund=state.get('refund')
        if refund:d.update(refund_amount=refund['amount'],refund_method=refund['method'])
        if d['outcome_type'] in {'return','immediate_refund','cancel'}:
            row=next(c for c in mutations if c['table'] in {'returns','refunds'})
            d['item_id']=row['key'].get('item_id');d['reason']=row['values']['reason']
            if row['table']=='refunds':d['shipping_refunded']=row['values']['shipping_refunded']
            elif d['reason']!='change_of_mind':
                prior=[r for r in world['refunds'] if r['order_id']==oid and r['status']=='completed']
                d['shipping_refunded']=orders[oid]['shipping_fee']>0 and not any(r['shipping_refunded'] for r in prior)
        if d['outcome_type']=='escalate':
            # Original states require nonempty rule_triggered, but do not store its
            # value. Project only escalation-trigger rules already in rules_tested.
            triggers=[r for r in s['rules_tested'] if r in {'A3','H1','H2','E9','E10','G2'}]
            if not triggers:raise ValueError(s['scenario_id']+': escalation trigger missing in original metadata')
            for rule in triggers:output.append({**d,'escalation_rule':rule})
        else:output.append(d)
    return output

def coverage(scenarios):
    orders=defaultdict(list)
    for s in scenarios:orders[target_order_id(s)].append(s['scenario_id'])
    return {'distinct_users':len({s['user_id'] for s in scenarios}),'distinct_orders':len(orders),
            'orders_used_more_than_twice':[{'order_id':oid,'scenario_count':len(ids),'scenario_ids':ids} for oid,ids in sorted(orders.items()) if len(ids)>2]}

def collect(*,model='gpt-4.1-mini',workers=4):
    path=ROOT/'scenarios/scenarios.json';original=path.read_bytes();scenarios=json.loads(original)
    world={n:json.loads((ROOT/'data'/(n+'.json')).read_text()) for n in ['config','users','orders','order_items','refunds','returns','serviceable_pincodes']}
    policy=(ROOT/'policy.md').read_text();out=ROOT/'scenarios/structured_check';out.mkdir(exist_ok=True)
    expected={s['scenario_id']:projected_expected(s,world) for s in scenarios}
    (out/'expected_projection.json').write_text(json.dumps(expected,ensure_ascii=False,indent=2)+'\n')
    def one(s,pass_no):
        payload=payload_for(s,world,policy)
        digest=hashlib.sha256(json.dumps({'instructions':INSTRUCTIONS,'schema':SCHEMA,'payload':payload},sort_keys=True).encode()).hexdigest()
        dst=out/f'{s["scenario_id"]}_pass{pass_no}.json'
        if dst.exists():
            prev=json.loads(dst.read_text())
            if prev.get('input_sha256')==digest and prev.get('requested_model')==model and prev['status']=='completed':return prev
        rec={'scenario_id':s['scenario_id'],'pass':pass_no,'split':s['split'],'input_sha256':digest,'requested_model':model}
        try:
            response=ModelClient(model).complete(INSTRUCTIONS,payload,max_tokens=600,response_schema=SCHEMA)
            decision=response.pop('value')
            if set(decision)!=set(FIELDS):raise ModelError('Decision does not have exactly eight fields')
            rec.update(status='completed',decision=decision,**response)
        except ModelError as exc:rec.update(status='error',error=str(exc))
        dst.write_text(json.dumps(rec,ensure_ascii=False,indent=2)+'\n');return rec
    records=[]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures=[pool.submit(one,s,n) for s in scenarios for n in [1,2]]
        for f in as_completed(futures):
            records.append(f.result())
            if len(records)%10==0:print(f'Structured decisions: {len(records)}/80',flush=True)
    report={'scenario_sha256':hashlib.sha256(original).hexdigest(),'model':model,'completed_calls':sum(r['status']=='completed' for r in records),
            'errors':[r for r in records if r['status']=='error'],'coverage':coverage(scenarios)}
    (out/'collection.json').write_text(json.dumps(report,indent=2)+'\n')
    assert path.read_bytes()==original,'Scenarios changed during collection'
    print(json.dumps({'completed_calls':report['completed_calls'],'errors':len(report['errors']),'coverage':report['coverage']},indent=2))
    return 1 if report['errors'] else 0

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--model',default='gpt-4.1-mini');p.add_argument('--workers',type=int,default=4)
    args=p.parse_args();raise SystemExit(collect(model=args.model,workers=args.workers))
