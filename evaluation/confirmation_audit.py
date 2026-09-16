"""Recheck saved actions using only the proposal and next customer reply."""
import argparse
import copy
import json
from simulation.model_client import ROOT
from evaluation.run import Recorder,LoggedClient,write
from evaluation.judge import judge_inputs,authorization_judgments
from evaluation.grader import grade
from evaluation.scorecard import scorecard
from evaluation.report import render


def audit(run_name):
    root=ROOT/'runs'/run_name
    results=json.loads((root/'results.json').read_text())
    scenarios={s['scenario_id']:s for s in json.loads((ROOT/'scenarios/scenarios.json').read_text())}
    for index,final in enumerate(results):
        if final['status']=='invalid_run':continue
        attempt=final['attempts'][-1]['attempt_number']
        trial=root/f"{final['scenario_id']}_trial{final['trial_number']}";folder=trial/f'attempt{attempt}'
        r=json.loads((folder/'result.json').read_text())
        authorization=r['communication_checks'].get('authorization',[])
        if not authorization or all('agent_event_index' in a for a in authorization):continue
        recorder=Recorder(folder,r['timestamp'])
        transcript=json.loads((folder/'transcript.json').read_text())
        scenario=scenarios[r['scenario_id']]
        judgments=authorization_judgments(transcript,judge_inputs(scenario,transcript)['actions'],LoggedClient('judge','gpt-4.1-mini',recorder))
        write(folder/'authorization_before_scope_fix.json',authorization)
        write(folder/'h5_judgments.json',judgments)
        judgment={**r['communication_checks'],'authorization':judgments}
        g=grade(scenario,json.loads((folder/'initial_state.json').read_text()),json.loads((folder/'final_state.json').read_text()),transcript,judgment,run_error=r['run_error'])
        r.update(g)
        extra_cost=sum(call['cost_usd'] for call in recorder.records)
        r['api_cost_usd']+=extra_cost;r['cost_by_role']['judge']+=extra_cost;r['api_call_counts']['judge']+=len(recorder.records)
        r['confirmation_judge_scope']='proposal_and_next_reply_only'
        write(folder/'result.json',r)
        new=copy.deepcopy(r)
        new['attempts']=copy.deepcopy(final['attempts']);new['attempts'][-1]['api_cost_usd']=r['api_cost_usd']
        new['total_attempt_cost_usd']=sum(a['api_cost_usd'] for a in new['attempts'])
        write(trial/'result.json',new);results[index]=new
        write(root/'results.json',results);write(root/'scorecard.json',scorecard(results))
        print(json.dumps({'scenario_id':r['scenario_id'],'outcome_pass':r['outcome_pass'],'harmful_action':r['harmful_action'],'judgments':judgments},ensure_ascii=False),flush=True)
    render(root)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('run_name');a=p.parse_args();audit(a.run_name)
