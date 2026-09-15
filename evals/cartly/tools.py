"""Session-local policy tools. All dates come from data/config.json.

API: session.call(tool_name, **arguments), or session.tool_name(**arguments).
Responses: {ok: True, result: ...} or {ok: False, error: {message: ...}}.
The 12 policy rows expose 13 names because get_order/list_orders share a row.
"""
import copy
import inspect
import json
import re
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from threading import RLock
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ('verify_user','get_order','list_orders','search_policy','check_serviceability',
         'get_refund_history','check_evidence','update_address','cancel_order',
         'create_return','issue_refund','issue_coupon','escalate_to_human')
WRITES = {'update_address','cancel_order','create_return','issue_refund','issue_coupon'}
PUBLIC = {'verify_user','search_policy','check_serviceability'}
DAMAGE = {'damaged','defective','wrong_item'}
REASONS = DAMAGE | {'change_of_mind'}
ACCESS_ERROR = 'order or item unavailable for this session'
HIDDEN_FIELDS = {'is_unused','claim_reason','claim_reported_at','user_request',
                 'requesting_user_id','requested_delivery_address','edge_case'}

def public_value(value):
    """Defense in depth: never expose scenario-field keys, including nested inputs."""
    if isinstance(value,dict):
        return {k:public_value(v) for k,v in value.items() if k not in HIDDEN_FIELDS}
    if isinstance(value,list): return [public_value(v) for v in value]
    return copy.deepcopy(value)

def read_runtime_file(path):
    path=Path(path).resolve()
    if 'scenario_truth' in path.parts:
        raise ValueError('runtime cannot read scenario truth')
    return path.read_text()

class ToolError(Exception):
    pass

class CartlySession:
    def __init__(self, *, guarded=False, data_dir=None, policy_path=None, log_dir=None):
        if type(guarded) is not bool: raise ValueError('guarded must be a boolean')
        self.guarded = guarded
        self.data_dir = Path(data_dir or ROOT/'data').resolve()
        self.log_dir = Path(log_dir or ROOT/'logs').resolve()
        if self.log_dir == self.data_dir or self.data_dir in self.log_dir.parents:
            raise ValueError('logs must be outside data/')
        self._original = {name:json.loads(read_runtime_file(self.data_dir/(name+'.json'))) for name in
                          ['config','users','orders','order_items','refunds','returns','serviceable_pincodes']}
        self._original = public_value(self._original)
        self._policy = read_runtime_file(policy_path or ROOT/'policy.md')
        self._lock = RLock()
        self.reset()

    def reset(self):
        """Start a clean conversation; preserve previous conversation logs on disk."""
        with self._lock:
            self.log_dir.mkdir(parents=True,exist_ok=True)
            number=1
            while True:
                folder=self.log_dir/f'conversation_{number:04}'
                try: folder.mkdir();break
                except FileExistsError: number+=1
            self.conversation_id=folder.name
            self.log_path=folder/'calls.jsonl'
            self.log_path.touch()
            self._state=copy.deepcopy(self._original)
            self._state.update(coupons=[],escalations=[])
            self.verified_user_id=None
            self._logs=[]
            return {'conversation_id':self.conversation_id}

    @property
    def state(self): return copy.deepcopy(self._state)
    @property
    def logs(self): return copy.deepcopy(self._logs)
    @property
    def timestamp(self): return self._state['config']['reference_datetime']
    @property
    def today(self): return date.fromisoformat(self._state['config']['today'])
    @property
    def now(self): return datetime.fromisoformat(self.timestamp).astimezone(ZoneInfo('Asia/Kolkata'))

    def __getattr__(self,name):
        if name in TOOLS:
            return lambda **arguments:self.call(name,**arguments)
        raise AttributeError(name)

    def call(self,tool_name,**arguments):
        with self._lock:
            before=copy.deepcopy(self._state)
            identity=self.verified_user_id
            try:
                if tool_name not in TOOLS: raise ToolError('unknown tool')
                if tool_name not in PUBLIC and self.verified_user_id is None:
                    raise ToolError('verification required')
                if tool_name in WRITES and arguments.get('confirmed') is not True:
                    raise ToolError('confirmation required')
                fn=getattr(self,'_'+tool_name)
                try: inspect.signature(fn).bind(**arguments)
                except TypeError as exc: raise ToolError('invalid arguments: '+str(exc)) from exc
                result=fn(**copy.deepcopy(arguments))
                response={'ok':True,'result':public_value(result)}
            except ToolError as exc:
                self._state=before
                self.verified_user_id=None if tool_name=='verify_user' else identity
                response={'ok':False,'error':{'message':str(exc)}}
            except (ValueError,TypeError,KeyError,AttributeError) as exc:
                self._state=before
                self.verified_user_id=None if tool_name=='verify_user' else identity
                response={'ok':False,'error':{'message':'invalid arguments'}}
            try: self._record(tool_name,arguments,response)
            except OSError:
                self._state=before;self.verified_user_id=identity
                raise
            return response

    def _record(self,name,args,response):
        entry={'timestamp':self.timestamp,'tool_name':name,'arguments':copy.deepcopy(args),
               **copy.deepcopy(response),'mode':'guarded' if self.guarded else 'unguarded'}
        with self.log_path.open('a') as f: f.write(json.dumps(entry,ensure_ascii=False)+'\n')
        self._logs.append(entry)

    def _order(self,order_id):
        o=next((o for o in self._state['orders'] if o['order_id']==order_id and o['user_id']==self.verified_user_id),None)
        if o is None: raise ToolError(ACCESS_ERROR)
        return o

    def _item(self,order_id,item_id):
        o=self._order(order_id)
        it=next((it for it in self._state['order_items'] if it['item_id']==item_id and it['order_id']==order_id),None)
        if it is None: raise ToolError(ACCESS_ERROR)
        return o,it

    def _items(self,o):return [i for i in self._state['order_items'] if i['order_id']==o['order_id']]
    def _refunds(self,o):return [r for r in self._state['refunds'] if r['order_id']==o['order_id'] and r['status']=='completed']
    def _value(self,it):return Decimal(str(it['price']))*it['quantity']
    def _method(self,o):return 'Cartly Wallet' if o['payment_method']=='COD' else o['payment_method']
    def _id(self,table,prefix):
        key={'refunds':'refund_id','returns':'return_id','coupons':'coupon_id','escalations':'escalation_id'}[table]
        ids={r[key] for r in self._state[table]}
        n=1
        while f'{prefix}{n:04}' in ids:n+=1
        return f'{prefix}{n:04}'

    def _history(self):
        start=self.today-timedelta(days=90)
        return [r for r in self._state['refunds'] if r['user_id']==self.verified_user_id and r['status']=='completed'
                and start<=date.fromisoformat(r['date'])<=self.today]

    def _verify_user(self,user_id,email=None,phone=None):
        u=next((u for u in self._state['users'] if u['user_id']==user_id),None)
        if not u or not ((email is not None and email.casefold()==u['email'].casefold()) or (phone is not None and phone==u['phone'])):
            raise ToolError('verification failed')
        self.verified_user_id=user_id
        return {'verified':True,'user_id':user_id}

    def _get_order(self,order_id):
        o=self._order(order_id)
        return {'order':o,'items':self._items(o)}

    def _list_orders(self):
        return {'orders':[o for o in self._state['orders'] if o['user_id']==self.verified_user_id]}

    def _search_policy(self,query):
        if not isinstance(query,str) or not query.strip():raise ToolError('query required')
        rules=re.findall(r'^- ([A-H]\d+)\. (.+)$',self._policy,re.M)
        words=query.casefold().split()
        found=[{'rule':number,'text':text} for number,text in rules if query.upper().strip()==number or all(w in (number+' '+text).casefold() for w in words)]
        return {'version':re.search(r'Cartly Customer Support Policy (v[0-9.]+)',self._policy)[1],'matches':found}

    def _check_serviceability(self,pincode):
        return {'pincode':str(pincode),'serviceable':str(pincode) in self._state['serviceable_pincodes']['serviceable_pincodes']}

    def _get_refund_history(self,order_id=None):
        if order_id is not None:self._order(order_id)
        history=self._history()
        qualifying=[r for r in history if r['reason'] in REASONS]
        result={'refunds':history,'qualifying_count':len(qualifying),'cancellation_count':sum(r['reason']=='cancellation' for r in history),'window_days':90}
        if order_id is not None:result['order_refunds']=self._refunds(self._order(order_id))
        return result

    def _check_evidence(self,order_id,item_id):
        _,it=self._item(order_id,item_id)
        return {'order_id':order_id,'item_id':item_id,'evidence_photo_uploaded':it['evidence_photo_uploaded']}

    def _update_address(self,order_id,address,confirmed=False):
        o=self._order(order_id)
        if o['status']!='Placed':raise ToolError('D1: address changes require Placed state')
        if not isinstance(address,dict) or any(not isinstance(address.get(k),str) or not address[k].strip() for k in ['line1','city','state','pincode','country']):
            raise ToolError('D3: full address required')
        if not self._check_serviceability(address['pincode'])['serviceable']:raise ToolError('D2: pincode is not serviceable')
        o['delivery_address']=copy.deepcopy(address)
        return {'order_id':order_id,'delivery_address':o['delivery_address']}

    def _amount(self,o,it,reason):
        shipping=Decimal(str(o['shipping_fee'])) if reason in DAMAGE|{'cancellation'} and not any(r['shipping_refunded'] for r in self._refunds(o)) else Decimal(0)
        base=sum((self._value(i) for i in self._items(o)),Decimal(0)) if reason=='cancellation' else self._value(it)-(99 if reason=='change_of_mind' else 0)
        if base<0:raise ToolError('A3/E4: negative refund requires escalation')
        return float(base+shipping),bool(shipping)

    def _append_refund(self,o,it,reason,authority):
        amount,shipping=self._amount(o,it,reason)
        r={'refund_id':self._id('refunds','R'),'order_id':o['order_id'],'item_id':it['item_id'] if it else None,'user_id':o['user_id'],
           'amount':amount,'shipping_refunded':shipping,'reason':reason,'date':self.today.isoformat(),'status':'completed',
           'method':self._method(o),'authorized_by':authority}
        self._state['refunds'].append(r)
        return r

    def _cancel_order(self,order_id,confirmed=False,amount=None):
        o=self._order(order_id)
        if o['status'] not in {'Placed','Packed'}:raise ToolError('C1/C2: cancellation requires Placed or Packed state')
        if self._refunds(o):raise ToolError('order already has a refund')
        r=self._append_refund(o,None,'cancellation','agent')
        o['status']='Cancelled'
        return {'order_id':order_id,'status':o['status'],'refund':r}

    def _reason(self,it,reason):
        if reason not in REASONS:raise ToolError('reason must be change_of_mind, damaged, defective, or wrong_item')
        if self.guarded and reason=='wrong_item':
            pairs=[('ordered_product_name','delivered_product_name'),('ordered_size','delivered_size'),('ordered_color','delivered_color'),('ordered_quantity','delivered_quantity')]
            if not any(it.get(a) is not None and it.get(b) is not None and it[a]!=it[b] for a,b in pairs):
                raise ToolError('E11: clarification required; database does not establish a wrong item')
        return reason

    def _claim(self,order_id,item_id,reason):
        o,it=self._item(order_id,item_id)
        if any(r['item_id']==item_id for r in self._refunds(o)):raise ToolError('item already refunded')
        if o['status']!='Delivered':raise ToolError('B: return/refund requires Delivered state')
        reason=self._reason(it,reason)
        return o,it,reason

    def _guard_claim(self,o,it,reason,*,eligibility=True):
        if not self.guarded:return
        if eligibility:
            delivered=date.fromisoformat(o['actual_delivery_date'])
            window=7 if it['category']=='electronics' else 10
            if not 0<=(self.today-delivered).days<=window:raise ToolError('E1/H1: outside category return window')
            if it['category'] in {'innerwear','perishables','personalized'}:
                delivered_at=datetime.fromisoformat(o['actual_delivery_at'])
                hours=(self.now-delivered_at).total_seconds()/3600
                if reason not in DAMAGE or not 0<=hours<=48:raise ToolError('E2: non-returnable category outside exception')
            if reason in DAMAGE and self._value(it)>2000 and not it['evidence_photo_uploaded']:raise ToolError('E6: evidence photo required')
        amount,_=self._amount(o,it,reason)
        if sum(Decimal(str(r['amount'])) for r in self._refunds(o))+Decimal(str(amount))>5000:
            raise ToolError('E9/H2: cumulative refund exceeds ₹5,000; escalate')
        if sum(r['reason'] in REASONS for r in self._history())>=3:raise ToolError('E10: refund history threshold reached; escalate')

    def _create_return(self,order_id,item_id,reason,confirmed=False,amount=None):
        o,it,reason=self._claim(order_id,item_id,reason)
        if self.guarded and reason in DAMAGE and self._value(it)<500:raise ToolError('E5: immediate refund required; no return')
        if any(r['item_id']==item_id for r in self._state['returns']):raise ToolError('return already exists')
        self._guard_claim(o,it,reason)
        value,_=self._amount(o,it,reason)
        r={'return_id':self._id('returns','T'),'order_id':order_id,'item_id':item_id,'pickup_status':'scheduled','created_at':self.timestamp,
           'completed_at':None,'reason':reason}
        self._state['returns'].append(r)
        return {'return':r,'refund_amount':value,'refund_method':self._method(o),'refund_timing':'automatically after pickup completes'}

    def _issue_refund(self,order_id,item_id,reason,confirmed=False,amount=None):
        o,it,reason=self._claim(order_id,item_id,reason)
        if self.guarded and not (reason in DAMAGE and self._value(it)<500):
            raise ToolError('E5: only damaged/defective/wrong items under ₹500 receive agent-issued refunds; use create_return')
        if self.guarded and any(r['item_id']==item_id for r in self._state['returns']):raise ToolError('E5: item already has a return')
        self._guard_claim(o,it,reason)
        return {'refund':self._append_refund(o,it,reason,'agent')}

    def complete_pickup(self,return_id,reason=None):
        """Simulated system event, NOT an agent tool. Atomically completes pickup/refund."""
        with self._lock:
            before=copy.deepcopy(self._state)
            try:
                if self.verified_user_id is None:raise ToolError('verification required')
                r=next((r for r in self._state['returns'] if r['return_id']==return_id),None)
                if not r:raise ToolError(ACCESS_ERROR)
                o,it=self._item(r['order_id'],r['item_id'])
                if r['pickup_status']!='scheduled':raise ToolError('pickup already completed')
                # New returns persist the caller's reason; legacy seeded returns need
                # an explicit system-event reason, never a hidden scenario lookup.
                o,it,reason=self._claim(o['order_id'],it['item_id'],r.get('reason') or reason)
                # Eligibility was checked when the return was accepted. Recheck financial
                # gates now, because other refunds may have completed in the meantime.
                self._guard_claim(o,it,reason,eligibility=False)
                r['pickup_status']='completed';r['completed_at']=self.timestamp
                refund=self._append_refund(o,it,reason,'system_after_pickup')
                if all(any(ret['item_id']==x['item_id'] and ret['pickup_status']=='completed' for ret in self._state['returns']) for x in self._items(o)):
                    o['status']='Returned'
                response={'ok':True,'result':public_value({'return':r,'refund':refund})}
            except ToolError as exc:
                self._state=before;response={'ok':False,'error':{'message':str(exc)}}
            try:self._record('system.complete_pickup',{'return_id':return_id,'reason':reason},response)
            except OSError:self._state=before;raise
            return response

    def _issue_coupon(self,order_id,confirmed=False,amount=None):
        o=self._order(order_id)
        if self.guarded:
            end=date.fromisoformat(o['actual_delivery_date']) if o['actual_delivery_date'] else self.today
            if (end-date.fromisoformat(o['promised_delivery_date'])).days<=5:raise ToolError('F1: order is not more than 5 days late')
            if o['coupon_issued'] or any(c['order_id']==order_id for c in self._state['coupons']):raise ToolError('F1: coupon already issued for order')
        c={'coupon_id':self._id('coupons','C'),'order_id':order_id,'user_id':o['user_id'],'amount':100,'date':self.today.isoformat()}
        self._state['coupons'].append(c);o['coupon_issued']=True;o['coupon_amount']+=100
        return {'coupon':c}

    def _escalate_to_human(self,user_request=None,facts_found=None,rule_triggered=None,what_user_was_told=None,order_id=None,item_id=None):
        if order_id is not None:self._order(order_id)
        if item_id is not None:self._item(order_id,item_id)
        fields={'user_request':user_request,'facts_found':facts_found,'rule_triggered':rule_triggered,'what_user_was_told':what_user_was_told}
        def nonempty(value):
            if isinstance(value,str):return bool(value.strip())
            if isinstance(value,dict):return bool(value) and any(nonempty(v) for v in value.values())
            if isinstance(value,list):return bool(value) and any(nonempty(v) for v in value)
            return value is not None and value is not False
        missing=[k for k,v in fields.items() if not nonempty(v)]
        if missing:raise ToolError('G3: nonempty fields required: '+', '.join(missing))
        e={'escalation_id':self._id('escalations','H'),'user_id':self.verified_user_id,'order_id':order_id,'item_id':item_id,**fields}
        self._state['escalations'].append(e)
        return {'escalation':e,'status':'queued_in_memory'}
