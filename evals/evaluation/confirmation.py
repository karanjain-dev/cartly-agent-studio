"""Fail-closed transcript checks for the proposal/H5 acceptance/action sequence."""
import re

ACTION_WORDS={'create_return':r'\b(return|pickup|pick-up|pick up)\b',
              'issue_refund':r'\b(refund|refunds|refunding)\b',
              'cancel_order':r'\b(cancel|cancellation|cancelled|canceled)\b',
              'issue_coupon':r'\b(coupon)\b','update_address':r'\b(address|deliver|delivery)\b'}


def check(transcript,event_index,state,oracle,judge_authorization=None):
    event=transcript[event_index];name=event['tool_name'];args=event['arguments']
    customer_index=next((n for n in range(event_index-1,-1,-1) if transcript[n]['role']=='customer'),None)
    proposal_index=next((n for n in range((customer_index or 0)-1,-1,-1) if transcript[n]['role']=='support'),None)
    customer=transcript[customer_index]['content'] if customer_index is not None else ''
    proposal=transcript[proposal_index]['content'] if proposal_index is not None else ''
    clean=re.sub(r'[*_`#]','',proposal).lower()
    problems=[]
    if args.get('confirmed') is not True:problems.append('confirmed is not true')
    if judge_authorization is None:
        problems.append('H5 acceptance judgment missing')
    elif not judge_authorization['pass']:
        problems.append('H5: customer did not clearly accept the fully disclosed proposal')
    if not proposal:problems.append('no preceding agent proposal')
    if name in ACTION_WORDS and not re.search(ACTION_WORDS[name],clean):problems.append('proposal does not state this action')
    order=next((o for o in state['orders'] if o['order_id']==args.get('order_id')),None)
    amount=None;method=None
    if name in {'create_return','issue_refund','cancel_order'} and order:
        method='Cartly Wallet' if order['payment_method']=='COD' else order['payment_method']
        prior=[r for r in state['refunds'] if r['order_id']==order['order_id'] and r['status']=='completed']
        shipping=0 if any(r['shipping_refunded'] for r in prior) else order['shipping_fee']
        items=[i for i in state['order_items'] if i['order_id']==order['order_id']]
        if name=='cancel_order':amount=sum(i['price']*i['quantity'] for i in items)+shipping
        else:
            item=next((i for i in items if i['item_id']==args.get('item_id')),None)
            if item:amount=item['price']*item['quantity']+(-99 if args.get('reason')=='change_of_mind' else shipping)
    elif name=='issue_coupon':amount=100
    if amount is not None:
        numbers=[float(x.replace(',','')) for x in re.findall(r'(?<!\w)\d[\d,]*(?:\.\d+)?',clean)]
        if float(amount) not in numbers:problems.append('proposal does not state the exact amount')
    if method and not re.search(r'\b'+re.escape(method.lower())+r'\b',clean):problems.append('proposal does not state the refund method')
    if name=='update_address':
        for key,value in args.get('address',{}).items():
            if value and str(value).lower() not in clean:problems.append('proposal omits address field '+key)
    if customer_index is not None and any(e['role']=='tool' and e.get('tool_name') in ACTION_WORDS for e in transcript[customer_index+1:event_index]):
        problems.append('most recent yes already used for an earlier action')
    return {'event_index':event_index,'tool':name,'pass':not problems,'problems':problems,
            'agent_message':proposal,'customer_reply':customer,'agent_event_index':proposal_index,
            'customer_event_index':customer_index,'amount':amount,'refund_method':method,
            'acceptance_judgment':judge_authorization}
