"""Descriptions of the existing tool interface, without additional agent coaching."""
import inspect
from cartly.tools import CartlySession, TOOLS

DESCRIPTIONS = {
 'verify_user':'Checks user ID against registered email or phone.',
 'get_order':'Reads order details and items.', 'list_orders':'Lists the verified user’s orders.',
 'search_policy':'Retrieves policy sections matching a query or rule number.',
 'check_serviceability':'Checks whether a pincode is serviceable.',
 'get_refund_history':'Reads refunds in the last 90 days; optionally includes all refunds on an order.',
 'check_evidence':'Checks whether an item has an uploaded evidence photo.',
 'update_address':'Changes an order’s delivery address.',
 'cancel_order':'Cancels an order and triggers its refund.',
 'create_return':'Schedules item pickup and returns a refund quote.',
 'issue_refund':'Issues an item refund.', 'issue_coupon':'Issues a ₹100 coupon.',
 'escalate_to_human':'Queues a handoff with the request, facts, triggering rule, and customer-facing explanation.'}

def schemas():
    result=[]
    for name in TOOLS:
        fields={}
        for key,p in inspect.signature(getattr(CartlySession,'_'+name)).parameters.items():
            if key=='self':continue
            kind='boolean' if key=='confirmed' else 'number' if key=='amount' else 'string'
            spec={'type':kind}
            if key=='address':
                props={k:{'type':'string'} for k in ['line1','line2','city','state','pincode','country']}
                spec={'type':'object','properties':props,'required':list(props),'additionalProperties':False}
            elif p.default is None:spec={'type':[kind,'null']}
            if key=='reason':spec['enum']=['change_of_mind','damaged','defective','wrong_item']
            fields[key]=spec
        result.append({'type':'function','name':name,'description':DESCRIPTIONS[name],'strict':True,
                       'parameters':{'type':'object','properties':fields,'required':list(fields),'additionalProperties':False}})
    return result
