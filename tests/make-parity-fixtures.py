"""Create independent Python-tool expectations without changing project inputs."""
import json,sys,tempfile
from pathlib import Path
site=Path(__file__).resolve().parents[1]
root=site.parent if (site.parent/'cartly/tools.py').exists() else site/'evals'
sys.path.insert(0,str(root))
from cartly.tools import CartlySession,TOOLS
from evaluation.state import changes
world=json.loads((site/'lib/reference/world.json').read_text())
fixture=tempfile.TemporaryDirectory()
data_dir=Path(fixture.name)/'data';data_dir.mkdir()
for name,value in world.items():
 (data_dir/(name+'.json')).write_text(json.dumps(value,ensure_ascii=False))
policy_path=Path(fixture.name)/'policy.md'
policy_path.write_text(json.loads((site/'lib/reference/policy.json').read_text())['policy'])
cases=[]
def case(name,calls):
 with tempfile.TemporaryDirectory() as logs:
  s=CartlySession(log_dir=logs,data_dir=data_dir,policy_path=policy_path);out=[]
  for tool,args in calls:
   before=s.state;result=s.call(tool,**args);out.append({'result':result,'changes':changes(before,s.state),'verified':s.verified_user_id})
  cases.append({'name':name,'calls':calls,'expected':out})
def verify(uid):
 u=next(u for u in world['users'] if u['user_id']==uid);return ['verify_user',{'user_id':uid,'email':u['email']}]
for o in world['orders']:
 owned=verify(o['user_id']);iid=next(i['item_id'] for i in world['order_items'] if i['order_id']==o['order_id'])
 case(o['order_id']+' reads',[owned,['get_order',{'order_id':o['order_id']}],['check_evidence',{'order_id':o['order_id'],'item_id':iid}],['get_refund_history',{'order_id':o['order_id']}],['list_orders',{}]])
case('privacy',[['get_order',{'order_id':'O0011'}],verify('U018'),['get_order',{'order_id':'O0075'}],['get_order',{'order_id':'UNKNOWN'}],['create_return',{'order_id':'O0075','item_id':'I0011','reason':'damaged','confirmed':True}]])
case('return plus duplicate',[verify('U018'),['create_return',{'order_id':'O0011','item_id':'I0011','reason':'change_of_mind','confirmed':False}],['create_return',{'order_id':'O0011','item_id':'I0011','reason':'change_of_mind','confirmed':True,'amount':999999}],['create_return',{'order_id':'O0011','item_id':'I0011','reason':'change_of_mind','confirmed':True}]])
case('refund plus duplicate',[verify('U018'),['issue_refund',{'order_id':'O0011','item_id':'I0011','reason':'damaged','confirmed':True,'amount':1}],['issue_refund',{'order_id':'O0011','item_id':'I0011','reason':'damaged','confirmed':True}]])
case('policy and serviceability',[['search_policy',{'query':'E1'}],['search_policy',{'query':'shipping'}],['check_serviceability',{'pincode':'560001'}],['check_serviceability',{'pincode':'999999'}]])
case('cancel',[verify('U014'),['cancel_order',{'order_id':'O0075','confirmed':True,'amount':1}],['cancel_order',{'order_id':'O0075','confirmed':True}]])
address={'line1':'Flat 302, Lake View Apartments','line2':'Near the main post office','city':'Bengaluru','state':'Karnataka','pincode':'560001','country':'India'}
case('address',[verify('U013'),['update_address',{'order_id':'O0074','address':address,'confirmed':True}],['update_address',{'order_id':'O0074','address':{**address,'pincode':'999999'},'confirmed':True}]])
case('coupon',[verify('U031'),['issue_coupon',{'order_id':'O0092','confirmed':True}],['issue_coupon',{'order_id':'O0092','confirmed':True}]])
case('handoff',[verify('U018'),['escalate_to_human',{'order_id':'O0011','user_request':'Please help','facts_found':['Delivered'],'rule_triggered':'G2','what_user_was_told':'Human support will review.'}],['escalate_to_human',{'user_request':''}]])
case('clear identity',[verify('U018'),['verify_user',{'user_id':'U018','email':'wrong@example.com'}],['get_order',{'order_id':'O0011'}]])
# Exercise all existing seeded shipping-refunded orders and COD returnable records.
for o in world['orders']:
 if any(r['order_id']==o['order_id'] and r['shipping_refunded'] for r in world['refunds']) or o['payment_method']=='COD':
  items=[i for i in world['order_items'] if i['order_id']==o['order_id']]
  for i in items:case(o['order_id']+' refund '+i['item_id'],[verify(o['user_id']),['issue_refund',{'order_id':o['order_id'],'item_id':i['item_id'],'reason':'damaged','confirmed':True}]])
p=site/'.sites-runtime/parity.json';p.parent.mkdir(exist_ok=True);p.write_text(json.dumps(cases,ensure_ascii=False));print(f'{len(cases)} Python reference sequences prepared')
