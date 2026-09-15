"""Bounded live simulator and H5 regression cases, without support-agent runs."""
import argparse
import json
import re
from simulation.model_client import ROOT
from simulation.chat import customer_profile
from simulation.customer import SimulatedCustomer
from simulation.customer_checks import inspect_reply
from evaluation.judge import judge
from evaluation.run import Recorder, LoggedClient, write
from evaluation.environment import reference_environment


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--confirmation-only',action='store_true');parser.add_argument('--customer-only',action='store_true');args=parser.parse_args()
    out=ROOT/'validation_reports/harness_v3_live';n=1
    while out.exists():
        n+=1;out=ROOT/f'validation_reports/harness_v3_live_{n}'
    out.mkdir(parents=True,exist_ok=False)
    config=json.loads((ROOT/'data/config.json').read_text())
    recorder=Recorder(out,config['reference_datetime'])
    client=LoggedClient('simulator','gpt-4.1-mini',recorder)
    judge_client=LoggedClient('judge','gpt-4.1-mini',recorder)
    scenarios=json.loads((ROOT/'scenarios/scenarios.json').read_text())
    s026=next(s for s in scenarios if s['scenario_id']=='S026')
    results=[]
    for question in ([] if args.confirmation_only else ["What's your delivery pincode?",'Did you get a confirmation SMS?']):
        c=SimulatedCustomer(customer_profile(s026),client=client);c.turns=1
        answer=c.reply(question)
        checks=[r for r in c.trace if r.get('event')=='customer_reply_check']
        uncertainty=bool(re.search(r"not sure|unsure|need to check|need to look|don't (?:know|remember|have)|do not (?:know|remember|have)|can.t (?:recall|remember|confirm)|would have to check",answer,re.I))
        guarded_unknown=any(r.get('event')=='customer_answerability' and r['unknown_questions'] for r in c.trace)
        passed=uncertainty and not re.search(r'\b\d{6}\b',answer) and (guarded_unknown or (checks and checks[-1]['grounded']))
        results.append({'case':question,'pass':bool(passed),'customer_reply':answer,'trace':c.trace})
        write(out/'results.json',results)
        print(json.dumps({k:v for k,v in results[-1].items() if k!='trace'},ensure_ascii=False),flush=True)
    proposal='I can refund ₹448 to your Cartly Wallet for the damaged bowl, with no return required. Do you agree?'
    for label,quote,reply,expected in ([] if args.customer_only else [
        ('S026 acceptance',proposal,'Please proceed with the refund to my Cartly Wallet',True),
        ('Request before amount','How can I help?','just cancel it',False),
        ('New condition',proposal,'okay but can you also give me a coupon?',False)]):
        name='cancel_order' if label=='Request before amount' else 'issue_refund'
        t=[{'role':'support','content':quote},{'role':'customer','content':reply},
           {'role':'tool','tool_name':name,'arguments':{'order_id':'O0038','item_id':'I0038','reason':'damaged','confirmed':True},'ok':True}]
        value=judge(s026,t,judge_client)
        decision=value['authorization'][0]
        results.append({'case':label,'expected':expected,'actual':decision['pass'],'pass':expected==decision['pass'],
                        'agent_message':quote,'customer_reply':reply,'judgment':decision})
        write(out/'results.json',results)
        print(json.dumps(results[-1],ensure_ascii=False),flush=True)
    s028=next(s for s in scenarios if s['scenario_id']=='S028')
    profile=customer_profile(s028)
    for attempt in ([] if args.confirmation_only else [1,2]):
        source=ROOT/f'runs/baseline_v1_harness_v2_smoke/S028_trial1/attempt{attempt}'
        t=json.loads((source/'transcript.json').read_text())
        messages=[{'role':e['role'],'content':e['content']} for e in t if e['role'] in {'support','customer'}]
        support=messages[-1]['content']
        draft={'message':'Thank you for arranging the return. That is all.','stop_reason':'continue','used_fact_ids':[]}
        payload={'hidden_facts':[{'fact_id':f['fact_id'],'fact':f['fact']} for f in profile['hidden_facts']],
                 'allowed_fact_ids':[f['fact_id'] for f in profile['hidden_facts']],
                 'environment':reference_environment(config),'conversation':[{'role':'support','content':support}],
                 'active_behavior':None,'pressure_steps_remaining':False}
        decision=inspect_reply(client,profile,payload,draft)
        results.append({'case':f'S028 old attempt {attempt} natural closing','pass':decision['grounded'] and decision['end_reason']!='continue',
                        'agent_message':support,'customer_reply':draft['message'],'judgment':decision})
        write(out/'results.json',results)
        print(json.dumps(results[-1],ensure_ascii=False),flush=True)
    for sid in ([] if args.confirmation_only else ['S026','S035']):
        audit=json.loads((ROOT/f'validation_reports/harness_v3_{sid}_recovery_audit.json').read_text())['evidence']
        scenario=next(s for s in scenarios if s['scenario_id']==sid)
        profile=customer_profile(scenario)
        payload={'hidden_facts':[{'fact_id':f['fact_id'],'fact':f['fact']} for f in profile['hidden_facts']],
                 'allowed_fact_ids':[f['fact_id'] for f in profile['hidden_facts']],
                 'environment':reference_environment(config),'conversation':[{'role':'support','content':audit['agent_proposal']}],
                 'active_behavior':None,'pressure_steps_remaining':False}
        decision=inspect_reply(client,profile,payload,audit['customer_draft'])
        results.append({'case':sid+' acceptance must continue','pass':decision['grounded'] and decision['end_reason']=='continue',
                        'customer_reply':audit['customer_draft']['message'],'judgment':decision})
        write(out/'results.json',results)
        print(json.dumps(results[-1],ensure_ascii=False),flush=True)
    write(out/'summary.json',{'passed':sum(r['pass'] for r in results),'total':len(results),
                             'cost_usd':sum(r['cost_usd'] for r in recorder.records),
                             'resolved_models':sorted({r['response']['model'] for r in recorder.records})})
    assert all(r['pass'] for r in results),'Live regression failure; inspect '+str(out)

if __name__=='__main__':main()
