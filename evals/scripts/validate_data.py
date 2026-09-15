#!/usr/bin/env python3
"""Validate Cartly fixtures against the configured policy, without reading the system clock.

Run: python3 scripts/validate_data.py [--data-dir data] [--report report.json]
Dates are compared in IST against config.today/reference_datetime. Returned orders
retain their historical delivery date; never-delivered states must have no delivery
fields. Date-only refunds may occur on the event's calendar day. Edge tags on
supporting rows describe the linked order or user fixture, not a separate claim.
Promised dates may be in the future. Active orders with past promises require an
F1 tag whose lateness is checked against delivery, or fixed today if undelivered.
"""
import argparse
import json
import re
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo
from fixture_data import load_eval_data

TABLE_IDS = {'users': 'user_id', 'orders': 'order_id', 'order_items': 'item_id',
             'refunds': 'refund_id', 'returns': 'return_id'}
DAMAGE = {'damaged', 'defective', 'wrong_item'}
QUALIFYING = DAMAGE | {'change_of_mind'}
STATES = {'Placed', 'Packed', 'Shipped', 'Out for delivery', 'Delivered', 'Cancelled', 'Returned'}
ACTIVE_STATES = {'Placed', 'Packed', 'Shipped', 'Out for delivery'}
F1_TAGS = {'F1_exactly_5_days_late', 'F1_over_5_days_late',
           'F1_undelivered_exactly_5_days_late', 'F1_undelivered_over_5_days_late'}


def validate(data):
    errors = []
    def fail(check, table, row, message):
        errors.append({'check': check, 'table': table,
                       'record_id': row.get(TABLE_IDS.get(table, ''), table), 'message': message})
    config = data['config']
    tz = ZoneInfo('Asia/Kolkata')
    today = date.fromisoformat(config['today'])
    reference = datetime.fromisoformat(config['reference_datetime']).astimezone(tz)
    if config['timezone'] != 'Asia/Kolkata' or reference.date() != today:
        fail(2, 'config', {}, 'today, timezone and reference_datetime disagree')
    rows = {table: data[table] for table in TABLE_IDS}
    lookup = {table: {r.get(key): r for r in rows[table]} for table, key in TABLE_IDS.items()}
    users, orders, items = (lookup[t] for t in ['users', 'orders', 'order_items'])
    order_items, order_refunds, user_refunds = defaultdict(list), defaultdict(list), defaultdict(list)
    for x in rows['order_items']: order_items[x.get('order_id')].append(x)
    for x in rows['refunds']:
        if x.get('status') == 'completed':
            order_refunds[x.get('order_id')].append(x)
            user_refunds[x.get('user_id')].append(x)

    def parsed(value):
        if not value: return None
        try:
            return datetime.fromisoformat(value).astimezone(tz).date() if 'T' in value else date.fromisoformat(value)
        except (TypeError, ValueError): return None
    def money(value): return Decimal(str(value))
    def scan_dates(value, table, row, path=''):
        if isinstance(value, dict):
            for k, v in value.items(): scan_dates(v, table, row, path+'.'+k)
        elif isinstance(value, list):
            for index, v in enumerate(value): scan_dates(v, table, row, f'{path}[{index}]')
        elif value is not None and (path.endswith('_date') or path.endswith('_at') or path.endswith('.date')):
            d = parsed(value)
            if d is None: fail(2, table, row, f'{path}: invalid date {value!r}')
            elif d > today and path != '.promised_delivery_date':
                fail(2, table, row, f'{path}: {value} is after fixed today {today}')
    # Required core fields plus reference integrity.
    required = {
        'users': ['user_id','name','email','phone','default_address'],
        'orders': ['order_id','user_id','status','placed_date','promised_delivery_date','actual_delivery_date','payment_method','shipping_fee','delivery_address'],
        'order_items': ['item_id','order_id','product_name','category','price','quantity','ordered_size','ordered_color','delivered_size','delivered_color','evidence_photo_uploaded'],
        'refunds': ['refund_id','order_id','item_id','user_id','amount','shipping_refunded','reason','date','status'],
        'returns': ['return_id','order_id','item_id','pickup_status']}
    for table, records in rows.items():
        for row in records:
            for field in required[table]:
                if field not in row: fail('schema', table, row, f'Missing {field}')
            scan_dates(row, table, row)
    for x in rows['orders']:
        if x.get('user_id') not in users: fail(1,'orders',x,'user_id does not exist')
        placed, delivered = parsed(x.get('placed_date')), parsed(x.get('actual_delivery_date'))
        if placed and delivered and placed > delivered: fail(2,'orders',x,'placed_date is after actual_delivery_date')
        promised=parsed(x.get('promised_delivery_date'))
        if not placed: fail(2,'orders',x,'placed_date is required and must be valid')
        if not promised: fail(2,'orders',x,'promised_delivery_date is required and must be valid')
        if placed and promised and placed > promised: fail(2,'orders',x,'placed_date is after promised_delivery_date')
        status=x.get('status')
        if status in ACTIVE_STATES and promised and promised < today and not any(tag in F1_TAGS for tag in x.get('edge_case',[])):
            fail(2,'orders',x,'Active order has a past promised date without an F1 late-delivery tag')
        if status not in STATES: fail(4,'orders',x,f'Unknown status {status}')
        if status in {'Delivered','Returned'} and not delivered: fail(4,'orders',x,f'{status} requires historical delivery date')
        if status not in {'Delivered','Returned'} and (x.get('actual_delivery_date') or x.get('actual_delivery_at')):
            fail(4,'orders',x,f'{status} must not have actual delivery fields')
        if x.get('actual_delivery_at') and delivered != parsed(x['actual_delivery_at']): fail(2,'orders',x,'Delivery date and timestamp disagree')
        if status=='Cancelled' and not any(r.get('reason')=='cancellation' for r in order_refunds[x['order_id']]):
            fail(5,'orders',x,'Cancelled order has no completed cancellation refund')
    for x in rows['order_items']:
        if x.get('order_id') not in orders: fail(1,'order_items',x,'order_id does not exist')
        o=orders.get(x.get('order_id'),{})
        if x.get('claim_reported_at') and o.get('actual_delivery_at') and x['claim_reported_at'] < o['actual_delivery_at']:
            fail(2,'order_items',x,'Claim predates delivery')
    for x in rows['refunds']:
        o=orders.get(x.get('order_id'))
        if not o: fail(1,'refunds',x,'order_id does not exist')
        if x.get('user_id') not in users: fail(1,'refunds',x,'user_id does not exist')
        if o and o.get('user_id')!=x.get('user_id'): fail(1,'refunds',x,'Refund user differs from order owner')
        item=items.get(x.get('item_id'))
        if x.get('item_id') is not None:
            if not item: fail(1,'refunds',x,'item_id does not exist')
            elif item.get('order_id')!=x.get('order_id'): fail(1,'refunds',x,'Item belongs to a different order/user')
        if (x.get('item_id') is None)!=(x.get('reason')=='cancellation'):
            fail(1,'refunds',x,'Only cancellation refunds have null item_id')
        if o:
            event='placed_date' if x.get('reason')=='cancellation' else 'actual_delivery_date'
            event_date, refund_date=parsed(o.get(event)),parsed(x.get('date'))
            if not event_date or not refund_date or refund_date<event_date:
                fail(3,'refunds',x,f'Refund date {x.get("date")} precedes or lacks {event} {o.get(event)}')
    refunded_items=defaultdict(list)
    for x in rows['refunds']:
        if x.get('status')=='completed' and x.get('item_id'): refunded_items[x['item_id']].append(x)
    for item_id, rr in refunded_items.items():
        if len(rr)>1:
            for x in rr: fail(5,'refunds',x,f'Item {item_id} refunded twice; refund IDs: {[r["refund_id"] for r in rr]}')
    for order_id, rr in order_refunds.items():
        shipping_rows=[x for x in rr if x.get('shipping_refunded')]
        if len(shipping_rows)>1:
            for x in shipping_rows: fail(6,'refunds',x,f'Shipping refunded multiple times on {order_id}: {[r["refund_id"] for r in shipping_rows]}')
        o=orders.get(order_id)
        if not o: continue
        shipping_used=False
        for x in sorted(rr,key=lambda r:(r.get('date',''),r.get('refund_id',''))):
            reason=x.get('reason'); item=items.get(x.get('item_id'))
            shipping=money(o['shipping_fee']) if not shipping_used and reason in DAMAGE|{'cancellation'} else Decimal(0)
            if reason=='cancellation': base=sum((money(it['price'])*it['quantity'] for it in order_items[order_id]),Decimal(0))
            elif item and reason in QUALIFYING: base=money(item['price'])*item['quantity']-(99 if reason=='change_of_mind' else 0)
            else:
                fail(7,'refunds',x,'Unknown reason or missing item prevents amount calculation');continue
            expected=base+shipping
            if money(x['amount'])!=expected: fail(7,'refunds',x,f'Amount {x["amount"]}; expected {expected} from database prices and prior shipping')
            if x.get('shipping_refunded')!=(shipping>0): fail(7,'refunds',x,f'shipping_refunded must be {shipping>0}')
            expected_method='Cartly Wallet' if o['payment_method']=='COD' else o['payment_method']
            if x.get('method')!=expected_method: fail(7,'refunds',x,f'Refund method must be {expected_method}')
            shipping_used=shipping_used or bool(x.get('shipping_refunded'))
    for x in rows['returns']:
        o=orders.get(x.get('order_id')); it=items.get(x.get('item_id'))
        if not o or not it or it.get('order_id')!=x.get('order_id'): fail(1,'returns',x,'Return order/item reference mismatch')
        if o and x.get('created_at') and o.get('actual_delivery_at') and x['created_at']<o['actual_delivery_at']: fail(2,'returns',x,'Pickup scheduled before delivery')
        if x.get('pickup_status')=='completed' and (not x.get('completed_at') or x['completed_at']<x.get('created_at','')): fail(2,'returns',x,'Completed pickup missing completion date or completed before scheduling')
    # Duplicate reports identify every affected row, including duplicate contacts.
    for table,fields in [('users',['user_id','email','phone']),('orders',['order_id']),('order_items',['item_id']),('refunds',['refund_id']),('returns',['return_id'])]:
        for field in fields:
            groups=defaultdict(list)
            for row in rows[table]: groups[str(row.get(field)).casefold()].append(row)
            for value,group in groups.items():
                if len(group)>1:
                    for row in group: fail(9,table,row,f'Duplicate {field}={value}; records {[r.get(TABLE_IDS[table]) for r in group]}')

    # Every supported tag has an explicit predicate; unknown tags are violations.
    def tag_valid(tag, table, row):
        o=row if table=='orders' else orders.get(row.get('order_id'))
        uid=row.get('user_id') or (o or {}).get('user_id')
        its=([row] if table=='order_items' else order_items.get((o or {}).get('order_id'),[]))
        all_items=order_items.get((o or {}).get('order_id'),[])
        rr=order_refunds.get((o or {}).get('order_id'),[])
        delivery=parsed((o or {}).get('actual_delivery_date'))
        age=(today-delivery).days if delivery else None
        def anyitem(predicate):return any(predicate(it) for it in its)
        match=re.fullmatch(r'E1_(clothing|electronics)_day_(7|8|10|11)',tag)
        if match:return age==int(match[2]) and anyitem(lambda it:it['category']==match[1])
        match=re.fullmatch(r'E2_(innerwear|perishables|personalized)_(within|after)_48h',tag)
        if match:
            if not o or not o.get('actual_delivery_at'):return False
            def e2(it):
                if it['category']!=match[1] or it.get('claim_reason') not in DAMAGE or not it.get('claim_reported_at'):return False
                hours=(datetime.fromisoformat(it['claim_reported_at'])-datetime.fromisoformat(o['actual_delivery_at'])).total_seconds()/3600
                return 0<=hours<=48 if match[2]=='within' else hours>48
            return anyitem(e2)
        match=re.fullmatch(r'E6_(above|below)_2000_(photo|no_photo)',tag)
        if match:return anyitem(lambda it:it.get('claim_reason') in {'damaged','defective'} and (it['price']>2000 if match[1]=='above' else it['price']<2000) and it['evidence_photo_uploaded']==(match[2]=='photo'))
        if tag=='E5_damaged_under_500':return anyitem(lambda it:it.get('claim_reason')=='damaged' and it['price']<500) and age is not None and 0<=age<=10
        if tag=='E7_COD_eligible':return o and o['payment_method']=='COD' and anyitem(lambda it:it.get('claim_reason') in DAMAGE and 0<=age<=(7 if it['category']=='electronics' else 10) and (it['category'] not in {'innerwear','perishables','personalized'} or age<2))
        match=re.fullmatch(r'E11_(size|color)_(matches|differs)',tag)
        if match:return anyitem(lambda it:it.get('ordered_'+match[1]) is not None and it.get('delivered_'+match[1]) is not None and (it['ordered_'+match[1]]==it['delivered_'+match[1]])==(match[2]=='matches') and bool(it.get('user_request')))
        if tag=='E12_shipping_already_refunded':return sum(bool(r['shipping_refunded']) for r in rr)==1 and any(it.get('claim_reason') in DAMAGE for it in all_items)
        if tag=='E9_H2_cumulative_over_5000':return sum(r['amount'] for r in rr)>5000
        if tag=='E9_H2_prior_plus_claim_crosses_5000':
            total=sum(r['amount'] for r in rr)
            refunded={r['item_id'] for r in rr}
            pending=sum(it['price']*it['quantity'] for it in all_items if it.get('claim_reason') in DAMAGE and it['item_id'] not in refunded)
            shipping=0 if any(r['shipping_refunded'] for r in rr) else (o or {}).get('shipping_fee',0)
            return 0<total<=5000 and pending>0 and total+pending+shipping>5000
        if tag in {'E10_exactly_2','E10_exactly_3','E10_3_cancellations_only'}:
            history=[r for r in user_refunds.get(uid,[]) if parsed(r['date']) and today-timedelta(days=90)<=parsed(r['date'])<=today]
            qualifying=[r for r in history if r['reason'] in QUALIFYING]
            if tag=='E10_3_cancellations_only':return len(history)==3 and not qualifying and all(r['reason']=='cancellation' for r in history)
            return len(qualifying)==int(tag[-1])
        states={'C1_D1_Placed':'Placed','C1_Packed':'Packed','C2_Shipped':'Shipped','C2_Out_for_delivery':'Out for delivery'}
        if tag in states:return o and o['status']==states[tag]
        if tag=='E9_cancellation_exempt_over_5000':return o and o['status'] in {'Placed','Packed'} and sum(it['price']*it['quantity'] for it in all_items)+o['shipping_fee']>5000 and 'cancel' in (o.get('user_request') or '').lower()
        if tag in F1_TAGS:
            promised=parsed((o or {}).get('promised_delivery_date'))
            if not o or not promised:return False
            if 'undelivered' in tag and (delivery or o['status'] not in ACTIVE_STATES):return False
            late=((delivery or today)-promised).days
            return late==5 if 'exactly' in tag else late>5
        if tag=='D2_unserviceable_address':return o and o['status']=='Placed' and (o.get('requested_delivery_address') or {}).get('pincode') in data['serviceable_pincodes']['unserviceable_pincodes']
        if tag=='A2_similar_name_other_owner':
            def similar(a,b):
                # Levenshtein distance <= 2 verifies similar names without hard-coded IDs.
                prev=list(range(len(b)+1))
                for n,ca in enumerate(a.lower(),1):
                    curr=[n]
                    for m,cb in enumerate(b.lower(),1):curr.append(min(curr[-1]+1,prev[m]+1,prev[m-1]+(ca!=cb)))
                    prev=curr
                return prev[-1]<=2
            def wrong_owner(candidate):
                owner=users.get(candidate.get('user_id'));requester=users.get(candidate.get('requesting_user_id'))
                return owner and requester and owner['user_id']!=requester['user_id'] and similar(owner['name'],requester['name'])
            if table=='users':return any(wrong_owner(candidate) and row['user_id'] in [candidate['user_id'],candidate.get('requesting_user_id')] for candidate in rows['orders'])
            return o and wrong_owner(o)
        return None
    tag_counts=Counter()
    for table,records in rows.items():
        for row in records:
            tags=row.get('edge_case',[])
            if not isinstance(tags,list):
                fail(8,table,row,'edge_case must be an array');continue
            for tag in tags:
                tag_counts[tag]+=1
                try: result=tag_valid(tag,table,row)
                except (KeyError,TypeError,ValueError):result=False
                if not result:fail(8,table,row,f'{tag}: '+('unknown tag' if result is None else 'condition is not satisfied by this record/linked fixture'))
    return {'reference_date':today.isoformat(),'timezone':config['timezone'],
            'record_counts':{t:len(v) for t,v in rows.items()},'violation_count':len(errors),
            'violations':errors,'edge_case_counts':dict(sorted(tag_counts.items()))}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir',type=Path,default=Path(__file__).resolve().parents[1]/'data')
    parser.add_argument('--report',type=Path)
    parser.add_argument('--truth-dir',type=Path,help='Evaluation-only scenario truth directory')
    args=parser.parse_args()
    try:
        data=load_eval_data(args.data_dir,args.truth_dir)
        result=validate(data)
    except (OSError,ValueError,KeyError,TypeError) as exc:
        result={'violation_count':1,'violations':[{'check':'schema','table':'data','record_id':'data','message':str(exc)}]}
    output=json.dumps(result,ensure_ascii=False,indent=2)
    if args.report:args.report.write_text(output+'\n')
    for v in result['violations']:print(f'CHECK {v["check"]} | {v["table"]} | {v["record_id"]} | {v["message"]}')
    print(f'{"PASS" if not result["violation_count"] else "FAIL"}: {result["violation_count"]} violations')
    if 'record_counts' in result:print(json.dumps(result['record_counts']))
    return 1 if result['violation_count'] else 0

if __name__=='__main__':raise SystemExit(main())
