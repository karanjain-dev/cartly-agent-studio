"""Dev-only baseline pipeline. Heldout requires an explicit --heldout flag."""
import argparse
import copy
import hashlib
import json
import re
from functools import partial
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,as_completed
from cartly.tools import CartlySession
from simulation.model_client import ModelClient, ModelError, ROOT
from simulation.customer import SimulatedCustomer, STOP
from simulation.chat import customer_profile
from evaluation.agent import SupportAgent
from evaluation.costs import cost,RATES,SOURCES
from evaluation.grader import grade
from evaluation.judge import judge
from evaluation.scorecard import scorecard,KNOWN_LIMITATIONS
from evaluation.environment import build_agent_prompt, reference_environment, policy_version

AGENT_PROFILES={'gpt-6-astra':{'reasoning_effort':'high'},
                'gpt-5.6-terra':{'reasoning_effort':'low'}}


def write(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')

def protected_hashes():
    manifest=json.loads((ROOT/'evaluation/protected_files.json').read_text())
    return {p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in manifest}

def data_version():
    files={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((ROOT/'data').glob('*.json'))}
    return 'sha256:'+hashlib.sha256(json.dumps(files,sort_keys=True).encode()).hexdigest()


def select_scenarios(all_scenarios,ids=None,heldout=False):
    if ids:
        unknown=set(ids)-{s['scenario_id'] for s in all_scenarios}
        if unknown:raise ValueError('Unknown scenario IDs: '+', '.join(sorted(unknown)))
        selected=[s for s in all_scenarios if s['scenario_id'] in ids]
    else:selected=[s for s in all_scenarios if heldout or s['split']=='dev']
    if not heldout and any(s['split']=='heldout' for s in selected):
        raise ValueError('Heldout scenarios require the explicit --heldout flag')
    return selected


class Recorder:
    def __init__(self,folder,timestamp):self.folder=folder;self.timestamp=timestamp;self.records=[]
    def __call__(self,role,request,response):
        rec={'timestamp':self.timestamp,'role':role,'request':copy.deepcopy(request),'response':copy.deepcopy(response),
             'cost_usd':cost(response['model'],response.get('usage',{}))}
        self.records.append(rec)
        with (self.folder/'api_calls.jsonl').open('a') as f:f.write(json.dumps(rec,ensure_ascii=False)+'\n')


class LoggedClient:
    """Observe the existing simulator/client without altering prompts or behavior."""
    def __init__(self,role,model,recorder):self.role=role;self.client=ModelClient(model);self.recorder=recorder
    def complete(self,instructions,payload,**kwargs):
        response=self.client.complete(instructions,payload,**kwargs)
        self.recorder(self.role,{'instructions':instructions,'payload':payload,**kwargs},response)
        return response


def run_conversation(scenario,trial,folder,run_name,model,*,customer_model='gpt-4.1-mini'):
    folder.mkdir(parents=True,exist_ok=False)
    session=CartlySession(guarded=False,log_dir=folder/'session_logs')  # __init__ resets a fresh data copy.
    before=session.state
    recorder=Recorder(folder,session.timestamp)
    simulator=SimulatedCustomer(customer_profile(scenario),client=LoggedClient('simulator',customer_model,recorder),
                                environment=reference_environment(before['config']))
    policy=(ROOT/'policy.md').read_text()
    prompt=(ROOT/'prompts/agent_v1.1.md').read_text()
    assert prompt==build_agent_prompt(before['config'],policy)
    reasoning_effort=AGENT_PROFILES[model]['reasoning_effort']
    agent=SupportAgent(session,prompt,model,recorder,reasoning_effort=reasoning_effort)
    transcript=[];error=None;stop_reason=None;stage='simulator';error_origin=None
    tags={'run_name':run_name,'scenario_id':scenario['scenario_id'],'scenario_split':scenario['split'],
          'trial_number':trial,'agent_model_requested':model,'agent_model':None,'simulator_model_requested':customer_model,
          'simulator_reasoning_effort':'none' if customer_model=='gpt-5.6-luna' else None,
          'simulator_model':None,'prompt_version':'agent_v1.1','policy_version':policy_version(policy),
          'current_date':before['config']['today'],'harness_version':'v3','harness_revision':'v3.2',
          'data_version':data_version(),'tool_mode':'unguarded','reasoning_effort':reasoning_effort,'timestamp':session.timestamp}
    write(folder/'metadata.json',tags);write(folder/'initial_state.json',before)
    def checkpoint():
        write(folder/'transcript.json',transcript);write(folder/'tool_log.json',session.logs)
        write(folder/'final_state.json',session.state);write(folder/'simulator_trace.json',simulator.trace)
    try:
        customer_text=simulator.reply()
        transcript.append({'role':'customer','content':customer_text,'turn':simulator.turns})
        checkpoint()
        for _ in range(20):
            if customer_text==STOP or simulator.stopped:
                stop_reason=simulator.trace[-1].get('stop_reason',simulator.trace[-1].get('forced_stop','customer_ended'))
                break
            stage='agent'
            start_event=len(transcript)
            support=agent.reply(customer_text,transcript)
            checkpoint()
            if any(e['role']=='tool' and e['tool_name']=='escalate_to_human' and e.get('ok') for e in transcript[start_event:]):
                stop_reason='escalation_completed'
                break
            stage='simulator'
            customer_text=simulator.reply(support)
            transcript.append({'role':'customer','content':customer_text,'turn':simulator.turns})
            checkpoint()
            if customer_text==STOP or simulator.stopped:
                stop_reason=simulator.trace[-1].get('stop_reason',simulator.trace[-1].get('forced_stop','customer_ended'))
                break
        if stop_reason is None:stop_reason='turn_limit'
        if stop_reason=='turn_limit':
            error='Conversation turn limit reached';error_origin='turn_limit'
    except Exception as exc:
        error=str(exc)
        if str(exc).startswith(('Agent exceeded 20 tool rounds','Agent conversation turn limit')):error_origin='turn_limit'
        else:error_origin='api' if 'API' in str(exc) or (stage=='agent' and isinstance(exc,ModelError)) else stage
    finally:checkpoint()
    try:judgment=judge(scenario,transcript,LoggedClient('judge','gpt-4.1-mini',recorder))
    except Exception as exc:
        judgment={'status':'error','error':str(exc),'communication':[],'authorization':[],'clarification':[]}
        error=str(exc);error_origin='api' if 'API' in str(exc) else 'runner'
    result=grade(scenario,before,session.state,transcript,judgment,run_error=error)
    if error_origin=='turn_limit':result['failure_type']='state'
    result['status']='invalid_run' if error and error_origin!='turn_limit' else 'valid_run'
    if result['status']=='invalid_run':
        result['diagnostic_grade']=copy.deepcopy(result)
        result['diagnostic_grade']['failure_type']=None
        for field in ['outcome_pass','harmful_action','escalated','expected_escalation','escalation_correct','unnecessary_escalation','communication_pass','failure_type']:
            result[field]=None
    roles={role:sorted({r['response']['model'] for r in recorder.records if r['role']==role}) for role in ['agent','simulator','judge']}
    tags.update(agent_model=roles['agent'][0] if len(roles['agent'])==1 else roles['agent'],
                simulator_model=roles['simulator'][0] if len(roles['simulator'])==1 else roles['simulator'],
                judge_model=roles['judge'],stop_reason=stop_reason,error_origin=error_origin)
    result.update(**tags,category=scenario['category'],turns=agent.turns,
                  api_cost_usd=sum(r['cost_usd'] for r in recorder.records),
                  cost_by_role={role:sum(r['cost_usd'] for r in recorder.records if r['role']==role) for role in roles},
                  api_call_counts={role:sum(r['role']==role for r in recorder.records) for role in roles})
    write(folder/'metadata.json',tags);write(folder/'result.json',result)
    return result


def run_trial(scenario,trial,folder,run_name,model,*,conversation_fn=run_conversation,max_attempts=2):
    """One logical trial, at most two fresh attempts. Never reuse dirty state."""
    folder.mkdir(parents=True,exist_ok=False)
    attempts=[]
    for attempt in range(1,max_attempts+1):
        attempt_folder=folder/f'attempt{attempt}'
        try:
            result=conversation_fn(scenario,trial,attempt_folder,run_name,model)
        except Exception as exc:
            # Includes setup, serialization, grader, or runner errors.
            attempt_folder.mkdir(parents=True,exist_ok=True)
            saved=[]
            api_path=attempt_folder/'api_calls.jsonl'
            if api_path.exists():
                for line in api_path.read_text().splitlines():
                    try:saved.append(json.loads(line))
                    except ValueError:pass
            result={'status':'invalid_run','scenario_id':scenario['scenario_id'],'scenario_split':scenario['split'],
                    'category':scenario['category'],'trial_number':trial,'run_name':run_name,
                    'run_error':str(exc),'error_origin':'runner','failure_type':None,
                    'api_cost_usd':sum(c.get('cost_usd',0) for c in saved),'turns':None,
                    **{k:None for k in ['outcome_pass','harmful_action','escalated','expected_escalation','escalation_correct','unnecessary_escalation','communication_pass']}}
        attempt_folder.mkdir(parents=True,exist_ok=True)
        result['attempt_number']=attempt
        write(attempt_folder/'result.json',result)
        attempts.append(result)
        if result['status']!='invalid_run':break
        print(f"Invalid {scenario['scenario_id']} attempt {attempt}: {result.get('error_origin')} — {result.get('run_error')}",flush=True)
    final=copy.deepcopy(attempts[-1])
    final['attempts']=[{k:r.get(k) for k in ['attempt_number','status','error_origin','run_error','api_cost_usd']} for r in attempts]
    final['total_attempt_cost_usd']=sum(r['api_cost_usd'] for r in attempts)
    write(folder/'result.json',final)
    return final


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run-name',required=True);p.add_argument('--scenarios',nargs='+')
    p.add_argument('--trials',type=int,default=3);p.add_argument('--heldout',action='store_true')
    p.add_argument('--workers',type=int,default=1,choices=range(1,5))
    p.add_argument('--agent-model',default='gpt-5.6-terra',choices=sorted(AGENT_PROFILES))
    p.add_argument('--customer-model',default='gpt-4.1-mini',choices=sorted(RATES))
    p.add_argument('--max-attempts',type=int,default=2,choices=[1,2])
    args=p.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]+',args.run_name):p.error('Use a simple run name')
    if args.trials<1:p.error('trials must be positive')
    scenarios=json.loads((ROOT/'scenarios/scenarios.json').read_text())
    try:selected=select_scenarios(scenarios,args.scenarios,args.heldout)
    except ValueError as exc:p.error(str(exc))
    available=json.loads((ROOT/'evaluation/available_models.json').read_text())['models']
    if args.agent_model not in available:p.error('Agent model is not in the API-key model inventory')
    if args.customer_model not in available:p.error('Customer model is not in the API-key model inventory')
    original=protected_hashes();out=ROOT/'runs'/args.run_name
    out.mkdir(parents=True,exist_ok=False)
    write(out/'manifest.json',{'run_name':args.run_name,'scenario_ids':[s['scenario_id'] for s in selected],
          'customer_model':args.customer_model,'agent_model':args.agent_model,'max_attempts':args.max_attempts,
          'harness_version':'v3','harness_revision':'v3.2','workers':args.workers,'trials':args.trials,'heldout_explicit':args.heldout,'protected_files':original,'data_version':data_version(),
          'pricing_usd_per_million':RATES,'pricing_sources':SOURCES,'known_limitations':KNOWN_LIMITATIONS,
          'cost_note':'Token-usage estimate at standard API rates, not a billing invoice. Includes reported cache reads/writes and all observed simulator retries.'})
    results=[]
    jobs=[(s,trial) for s in selected for trial in range(1,args.trials+1)]
    def execute(job):
        s,trial=job
        print(f"Starting {s['scenario_id']} trial {trial}",flush=True)
        return run_trial(s,trial,out/f"{s['scenario_id']}_trial{trial}",args.run_name,args.agent_model,
                         conversation_fn=partial(run_conversation,customer_model=args.customer_model),max_attempts=args.max_attempts)
    try:
        # Sessions, model histories and artifact folders are independent. Only
        # the coordinator writes aggregate results, so completed jobs cannot race.
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures=[pool.submit(execute,job) for job in jobs]
            for future in as_completed(futures):
                result=future.result();results.append(result)
                results.sort(key=lambda r:(r['scenario_id'],r['trial_number']))
                write(out/'results.json',results)
                write(out/'scorecard.json',scorecard(results))
                print(json.dumps({k:result[k] for k in ['scenario_id','trial_number','status','outcome_pass','harmful_action','communication_pass','turns','api_cost_usd']}),flush=True)
    finally:
        assert protected_hashes()==original,'Protected project files changed during the run'
    write(out/'results.json',results)
    print('Scorecard:',out/'scorecard.json')

if __name__=='__main__':main()
