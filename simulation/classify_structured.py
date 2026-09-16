"""Post-hoc classification with explicit database/hidden-fact evidence."""
import hashlib
import json
import re
from collections import Counter
from datetime import date,datetime,timedelta
from decimal import Decimal
from simulation.model_client import ROOT
from simulation.structured_check import FIELDS,select_fields,target_order_id,coverage,projected_expected

BUCKETS=['MATCH','SCENARIO_SUSPECT','POLICY_AMBIGUOUS','MODEL_ERROR']

def verify_decision(s,d,world):
    """Verify concrete factual/arithmetic contradictions without using expected states.

    No claim about model reasoning is inferred. Each finding records the observable
    fact and the contradicted decision. Pure policy interpretation is not treated
    as evidence of a factual model error.
    """
    findings=[]
    oid=target_order_id(s);orders={o['order_id']:o for o in world['orders']};items={i['item_id']:i for i in world['order_items']}
    o=orders[oid];kind=d['outcome_type'];reason=d['reason'];today=date.fromisoformat(world['config']['today'])
    facts={f['fact_id']:f['fact'] for f in s['hidden_facts']}
    def bad(field,fact):findings.append({'field':field,'evidence':fact})
    if kind not in {'return','immediate_refund'} and d['item_id'] is not None:
        bad('item_id','Output-field mistake: item_id must be null for this non-item-mutation outcome under the shared eight-field conventions.')
    if kind not in {'return','immediate_refund','cancel'} and d['reason'] is not None:
        bad('reason','Output-field mistake: reason must be null when no return/refund/cancellation is proposed.')
    if kind not in {'return','immediate_refund','cancel'}:
        for field in ['refund_amount','refund_method']:
            if d[field] is not None:bad(field,'Output-field mistake: no refund is proposed, so this field must be null.')
    if kind!='escalate' and d['escalation_rule'] is not None:
        bad('escalation_rule','Output-field mistake: escalation_rule must be null for a non-escalation outcome.')
    if d['order_id']!=oid:bad('order_id',f'Customer identifies {oid}; decision identifies {d["order_id"]}.')
    if o['user_id']!=s['user_id']:
        if kind in {'return','immediate_refund','cancel','address_update','coupon'}:bad('outcome_type',f'{oid} belongs to {o["user_id"]}, not verified user {s["user_id"]} (A2).')
        return findings
    prior=[r for r in world['refunds'] if r['order_id']==oid and r['status']=='completed']
    shipping=Decimal(str(o['shipping_fee'])) if not any(r['shipping_refunded'] for r in prior) else Decimal(0)
    it=items.get(d['item_id'])
    candidates=[i for i in world['order_items'] if i['order_id']==oid and not any(r['item_id']==i['item_id'] for r in prior)]
    claim_item=it or (candidates[0] if len(candidates)==1 else None)
    if kind=='escalate' and d['escalation_rule']=='E6' and claim_item:
        price=Decimal(str(claim_item['price']))*claim_item['quantity']
        if price<=2000 or claim_item['evidence_photo_uploaded']:
            bad('escalation_rule',f'Database item {claim_item["item_id"]} has value ₹{price} and evidence_photo_uploaded={claim_item["evidence_photo_uploaded"]}; E6 does not require missing evidence here.')
    if kind in {'return','immediate_refund'}:
        if not it or it['order_id']!=oid:
            bad('item_id',f'Item {d["item_id"]} is not an item on {oid}.');return findings
        if any(r['item_id']==it['item_id'] for r in prior):bad('item_id',f'{it["item_id"]} already has a completed refund on {oid}.')
        value=Decimal(str(it['price']))*it['quantity']
        if reason=='change_of_mind':amount=value-99;included=False
        elif reason in {'damaged','defective','wrong_item'}:amount=value+shipping;included=shipping>0
        else:bad('reason','A return/refund needs a valid claim reason.');return findings
        if d['refund_amount'] is None or Decimal(str(d['refund_amount']))!=amount:
            bad('refund_amount',f'Database item value ₹{value}; shipping newly refundable ₹{shipping}; reason {reason} gives ₹{amount}, not {d["refund_amount"]} (E3/E4/E12/H4).')
        if d['shipping_refunded']!=included:bad('shipping_refunded',f'Database shipping/history imply shipping included={included} for {reason} (E12).')
        method='Cartly Wallet' if o['payment_method']=='COD' else o['payment_method']
        if d['refund_method']!=method:bad('refund_method',f'Database payment method {o["payment_method"]} requires refund method {method} (E7).')
        if kind=='return' and reason in {'damaged','defective','wrong_item'} and value<500:
            bad('outcome_type',f'Database item value ₹{value} is below ₹500 and the claim is {reason}, satisfying E5 immediate-refund conditions.')
        if kind=='immediate_refund' and not (reason in {'damaged','defective','wrong_item'} and value<500):
            bad('outcome_type',f'Database item value ₹{value} and claim {reason} do not satisfy E5 immediate-refund conditions.')
        delivered=date.fromisoformat(o['actual_delivery_date']) if o['actual_delivery_date'] else None
        if delivered:
            age=(today-delivered).days;window=7 if it['category']=='electronics' else 10
            if age>window:bad('outcome_type',f'Database dates give age {age} calendar days, greater than {window}-day {it["category"]} window (E1/H1).')
            if it['category'] in {'innerwear','perishables','personalized'}:
                elapsed=(datetime.fromisoformat(world['config']['reference_datetime'])-datetime.fromisoformat(o['actual_delivery_at'])).total_seconds()/3600
                if elapsed>48 or reason=='change_of_mind':bad('outcome_type',f'Database category {it["category"]}, elapsed {elapsed:g} hours, claim {reason}: E2 exception does not apply.')
        if reason in {'damaged','defective','wrong_item'} and value>2000 and not it['evidence_photo_uploaded']:
            bad('outcome_type',f'{it["item_id"]} has value ₹{value}, no uploaded photo, and customer fact: {facts.get("photo","not provided")} (E6).')
        cumulative=sum(Decimal(str(r['amount'])) for r in prior)+amount
        if cumulative>5000:bad('outcome_type',f'Completed order refunds plus proposed refund = ₹{cumulative}, above ₹5,000 (H2).')
        history=[r for r in world['refunds'] if r['user_id']==s['user_id'] and r['status']=='completed' and r['reason']!='cancellation' and today-timedelta(days=90)<=date.fromisoformat(r['date'])<=today]
        if len(history)>=3:bad('outcome_type',f'Database contains {len(history)} qualifying refunds in 90 days (E10).')
        condition=facts.get('condition','').lower()
        if reason=='change_of_mind' and ('has been used' in condition or 'wore the' in condition):bad('outcome_type','Hidden condition fact: '+facts['condition']+' (E4).')
        problem=facts.get('problem','')
        actual_reason='damaged' if problem=='The item arrived broken.' else 'defective' if problem=='The item does not function as described.' else None
        if actual_reason and reason!=actual_reason:bad('reason',f'Hidden problem fact identifies {actual_reason}: {problem}')
        if reason=='wrong_item':
            differences=[k for k in ['product_name','size','color','quantity'] if it.get('ordered_'+k)!=it.get('delivered_'+k)]
            if not differences:bad('reason','All ordered/delivered product, size, color and quantity attributes match (E11).')
        request=facts.get('request','').lower()
        if any(word in request for word in ['instalments','loyalty points','exchange']):
            bad('outcome_type','The hidden customer-request fact asks for a different service, not a return/refund: '+facts['request'])
    if kind=='cancel':
        value=sum(Decimal(str(i['price']))*i['quantity'] for i in world['order_items'] if i['order_id']==oid)+shipping
        if d['refund_amount'] is None or Decimal(str(d['refund_amount']))!=value:bad('refund_amount',f'Database order item total plus shipping is ₹{value}, not {d["refund_amount"]} (C1/E12/H4).')
        method='Cartly Wallet' if o['payment_method']=='COD' else o['payment_method']
        if d['refund_method']!=method:bad('refund_method',f'Database payment method requires {method}.')
        if d['shipping_refunded']!=(shipping>0):bad('shipping_refunded',f'Cancellation shipping inclusion must be {shipping>0}.')
        if o['status'] not in {'Placed','Packed'}:bad('outcome_type',f'Database state is {o["status"]}, so C1 does not authorize cancellation.')
    if kind=='coupon':
        end=date.fromisoformat(o['actual_delivery_date']) if o['actual_delivery_date'] else today
        late=(end-date.fromisoformat(o['promised_delivery_date'])).days
        if late<=5:bad('outcome_type',f'Database promised/actual dates give {late} days late; F1 requires more than 5.')
    # Hidden safety/legal statements are specific facts; ignoring them is auditable.
    relevant=' '.join(facts.values()).lower()
    if kind not in {'escalate','clarify_then_resolve'} and ('electric shock' in relevant or 'legal action' in relevant):
        bad('outcome_type','Hidden facts explicitly contain '+('an electric-shock safety incident' if 'electric shock' in relevant else 'a legal-action statement')+' (G2).')
    return findings

def classify(expected,runs,evidence):
    matches=[any(select_fields(d)==select_fields(e) for e in expected) for d in runs]
    if all(matches):return 'MATCH'
    if select_fields(runs[0])==select_fields(runs[1]):return 'SCENARIO_SUSPECT'
    if any(evidence):return 'MODEL_ERROR'
    if any(runs[0][k]!=runs[1][k] for k in ['outcome_type','refund_amount','escalation_rule']):return 'POLICY_AMBIGUOUS'
    # User explicitly approved MODEL_ERROR for remaining output-field mistakes.
    return 'MODEL_ERROR'

def short(d):
    bits=[d['outcome_type']]
    if d['reason']:bits.append(d['reason'])
    if d['refund_amount'] is not None:bits.append('₹'+str(d['refund_amount'])+' '+str(d['refund_method']))
    if d['escalation_rule']:bits.append(d['escalation_rule'])
    return ', '.join(bits)

def main():
    out=ROOT/'scenarios/structured_check';scenarios=json.loads((ROOT/'scenarios/scenarios.json').read_text())
    world={n:json.loads((ROOT/'data'/(n+'.json')).read_text()) for n in ['config','users','orders','order_items','refunds','returns','serviceable_pincodes']}
    collection=json.loads((out/'collection.json').read_text())
    if collection['completed_calls']!=80:raise ValueError('All 80 decisions must complete before classification')
    assert collection['scenario_sha256']==hashlib.sha256((ROOT/'scenarios/scenarios.json').read_bytes()).hexdigest()
    rows=[]
    for s in scenarios:
        runs=[json.loads((out/f'{s["scenario_id"]}_pass{n}.json').read_text())['decision'] for n in [1,2]]
        expected=projected_expected(s,world)
        evidence=[verify_decision(s,d,world) for d in runs]
        bucket=classify(expected,runs,evidence)
        rows.append({'scenario_id':s['scenario_id'],'split':s['split'],'bucket':bucket,'expected':expected,'run_1':runs[0],'run_2':runs[1],
                     'verified_model_errors':{'run_1':evidence[0],'run_2':evidence[1]}})
    counts={b:{sp:sum(r['bucket']==b and r['split']==sp for r in rows) for sp in ['dev','heldout']} for b in BUCKETS}
    report={'schema_fields':list(FIELDS),'completed_calls':80,'scenario_sha256':collection['scenario_sha256'],'bucket_counts':counts,'coverage':coverage(scenarios),
            'classification_precedence':'Both acceptable = MATCH; identical nonmatching decisions = SCENARIO_SUSPECT; otherwise verified factual/math or output-field mistakes = MODEL_ERROR; otherwise primary-field disagreement = POLICY_AMBIGUOUS. Remaining secondary-field disagreements are MODEL_ERROR per user clarification.',
            'expected_projection':'Existing end states projected without modification. Order reference comes from hidden facts; escalation trigger alternatives come from existing rules_tested metadata because the original end states did not constrain that value. Null non-applicable fields, false no-shipping; return amounts describe the planned refund.',
            'scenarios':rows}
    (out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    public={k:v for k,v in report.items() if k!='scenarios'}
    public['heldout_ids_by_bucket']={b:[r['scenario_id'] for r in rows if r['split']=='heldout' and r['bucket']==b] for b in BUCKETS}
    public['dev_review']=[r for r in rows if r['split']=='dev' and r['bucket'] in {'SCENARIO_SUSPECT','POLICY_AMBIGUOUS'}]
    (out/'public_report.json').write_text(json.dumps(public,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'bucket_counts':counts,'heldout_ids_by_bucket':public['heldout_ids_by_bucket'],'coverage':report['coverage']},indent=2))
    for r in public['dev_review']:print(r['scenario_id'],r['bucket'],' | '.join([' / '.join(short(d) for d in r['expected']),short(r['run_1']),short(r['run_2'])]))
if __name__=='__main__':main()
