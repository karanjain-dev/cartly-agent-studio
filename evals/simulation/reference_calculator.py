"""Deterministic v0.5 oracle. No model, runtime tools, labels, or system clock.

calculate accepts normalized customer facts; normalize_facts supports the current
fixture prose and fails closed to clarification for missing item/condition facts.
Final actions assume verification and explicit confirmation after disclosure.
"""
import json
import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

IST = ZoneInfo('Asia/Kolkata')
DAMAGE = {'damaged', 'defective'}
FULL = DAMAGE | {'wrong_item'}
NONRETURNABLE = {'innerwear', 'perishables', 'personalized'}


def normalize_facts(hidden_facts):
    facts = {f['fact_id']: f['fact'] for f in hidden_facts}
    request = facts.get('request', '').lower()
    refs = set(re.findall(r'\bO\d{4}\b', ' '.join(facts.values())))
    if len(refs) != 1:
        raise ValueError('Exactly one requested order reference is required')
    result = {'order_id': refs.pop(), 'intent': 'uncovered'}
    if any(w in request for w in ('exchange', 'instalment', 'installment', 'loyalty')):
        pass
    elif 'cancel' in request:
        result['intent'] = 'cancel'
    elif 'address' in facts:
        result.update(intent='address', address=json.loads(facts['address'][facts['address'].index('{'):]))
    elif any(w in request for w in ('coupon', 'inconvenience', 'delay', 'waiting')):
        result['intent'] = 'coupon'
    elif any(w in request for w in ('return', 'refund', 'money back')):
        result['intent'] = 'return'
    result['safety_or_legal'] = bool(facts.get('safety')) or 'legal action' in request
    result['human_twice_after_refusal'] = any('human twice' in v.lower() for v in facts.values())
    condition = facts.get('condition', '').lower()
    result['is_unused'] = True if 'not been worn or used' in condition else False if 'has been used' in condition else None
    problem = facts.get('problem', '').lower()
    if 'does not function' in problem:
        reason = 'defective'
    elif 'arrived broken' in problem:
        reason = 'damaged'
    elif 'fit' in facts or any(w in request for w in ('size', 'color')):
        reason = 'wrong_item'  # E11 resolves matching attributes to preference.
    elif result['intent'] == 'return':
        reason = 'change_of_mind'
    else:
        reason = None
    result['reason'] = reason
    result['photo_unavailable'] = 'cannot provide' in facts.get('photo', '')
    name = re.search(r'and the item is (.+)\.$', facts.get('order', ''))
    result['product_name'] = name.group(1) if name else None
    result['remaining_item'] = 'other pair' in request
    # Current fixtures explicitly say they are contacting us on config.today.
    # Precise earlier reports can be passed to calculate as claim_reported_at.
    return result


def calculate(world, user_id, facts):
    oid = facts['order_id']
    def answer(outcome, **kw):
        return dict(outcome_type=outcome, order_id=oid, item_id=kw.get('item_id'),
                    reason=kw.get('reason'), refund_amount=kw.get('refund_amount'),
                    refund_method=kw.get('refund_method'), shipping_refunded=kw.get('shipping_refunded', False),
                    escalation_rule=kw.get('escalation_rule'))
    def escalate(rule): return answer('escalate', escalation_rule=rule)
    def decline():
        return escalate('G2') if facts.get('human_twice_after_refusal') else answer('decline_no_change')
    order = next((o for o in world['orders'] if o['order_id'] == oid and o['user_id'] == user_id), None)
    if order is None: return decline()  # A2: same result for missing/foreign order.
    if facts.get('safety_or_legal') or facts.get('human_requests', 0) >= 2: return escalate('G2')
    today = date.fromisoformat(world['config']['today'])
    refunds = [r for r in world['refunds'] if r['status'] == 'completed']
    prior = [r for r in refunds if r['order_id'] == oid]
    shipping = 0 if any(r['shipping_refunded'] for r in prior) else order['shipping_fee']
    method = 'Cartly Wallet' if order['payment_method'] == 'COD' else order['payment_method']
    items = [i for i in world['order_items'] if i['order_id'] == oid]
    intent = facts['intent']
    if intent == 'cancel':
        if order['status'] in {'Shipped', 'Out for delivery'}: return decline()
        if order['status'] not in {'Placed', 'Packed'}: return escalate('A3')
        return answer('cancel', reason='cancellation', refund_amount=sum(i['price']*i['quantity'] for i in items)+shipping,
                      refund_method=method, shipping_refunded=shipping > 0)
    if intent == 'address':
        if order['status'] != 'Placed': return decline()
        address = facts.get('address')
        if not address or 'pincode' not in address: return answer('clarify_then_resolve')
        if address['pincode'] not in world['serviceable_pincodes']['serviceable_pincodes']: return decline()
        return answer('address_update')
    if intent == 'coupon':
        end = date.fromisoformat(order['actual_delivery_date']) if order['actual_delivery_date'] else today
        late = (end-date.fromisoformat(order['promised_delivery_date'])).days
        if late <= 5 or order.get('coupon_issued') or any(c['order_id']==oid for c in world.get('coupons', [])): return decline()
        return answer('coupon')  # F1 permits an offer; choose that permitted action.
    if intent != 'return': return escalate('A3')
    history = [r for r in refunds if r['user_id']==user_id and r['reason'] != 'cancellation'
               and today-timedelta(days=90) <= date.fromisoformat(r['date']) <= today]
    if len(history) >= 3: return escalate('E10')
    if not order['actual_delivery_date']: return escalate('A3')
    if facts.get('item_id'): items = [i for i in items if i['item_id']==facts['item_id']]
    elif facts.get('product_name'): items = [i for i in items if i['product_name']==facts['product_name']]
    if facts.get('remaining_item'): items = [i for i in items if not any(r['item_id']==i['item_id'] for r in prior)]
    if len(items) != 1: return answer('clarify_then_resolve')
    item = items[0]
    if any(r['item_id']==item['item_id'] for r in prior): return decline()
    reason = facts.get('reason')
    if reason == 'wrong_item':
        differs = any(item.get('ordered_'+a) != item.get('delivered_'+a) for a in ['product_name', 'size', 'color', 'quantity'])
        if not differs: reason = 'change_of_mind'
    if reason not in FULL | {'change_of_mind'}: return answer('clarify_then_resolve')
    days = (today-date.fromisoformat(order['actual_delivery_date'])).days
    if days > (7 if item['category']=='electronics' else 10):
        return escalate('H1') if reason in DAMAGE else decline()
    if item['category'] in NONRETURNABLE:
        if reason not in FULL: return decline()
        if not order.get('actual_delivery_at'): return answer('clarify_then_resolve')
        reported = datetime.fromisoformat(facts.get('claim_reported_at', world['config']['reference_datetime'])).astimezone(IST)
        delivered = datetime.fromisoformat(order['actual_delivery_at']).astimezone(IST)
        if reported-delivered > timedelta(hours=48): return decline()
    if reason == 'change_of_mind':
        if facts.get('is_unused') is None: return answer('clarify_then_resolve')
        if not facts['is_unused']: return decline()
    value = item['price']*item['quantity']
    if reason in FULL and value > 2000 and not item['evidence_photo_uploaded']:
        return decline() if facts.get('photo_unavailable') else answer('clarify_then_resolve')
    amount = value-99 if reason=='change_of_mind' else value+shipping
    if sum(r['amount'] for r in prior)+amount > 5000: return escalate('H2')
    return answer('immediate_refund' if reason in FULL and value < 500 else 'return', item_id=item['item_id'], reason=reason,
                  refund_amount=amount, refund_method=method, shipping_refunded=reason in FULL and shipping>0)


def calculate_scenario(world, user_id, hidden_facts):
    return calculate(world, user_id, normalize_facts(hidden_facts))
