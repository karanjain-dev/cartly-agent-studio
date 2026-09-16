"""Recompute deterministic grading from saved attempts; never calls a model."""
import argparse
import copy
import json
from simulation.model_client import ROOT
from evaluation.grader import grade
from evaluation.run import write
from evaluation.report import render


def regrade(folder):
    scenarios={s['scenario_id']:s for s in json.loads((ROOT/'scenarios/scenarios.json').read_text())}
    results=[]
    for trial in sorted(folder.glob('S*_trial*')):
        attempts=[]
        for path in sorted(trial.glob('attempt*/result.json')):
            r=json.loads(path.read_text());p=path.parent
            if (p/'initial_state.json').exists() and (p/'final_state.json').exists() and 'communication_checks' in r:
                g=grade(scenarios[r['scenario_id']],json.loads((p/'initial_state.json').read_text()),json.loads((p/'final_state.json').read_text()),
                        json.loads((p/'transcript.json').read_text()),r['communication_checks'],run_error=r['run_error'])
                if r['status']=='invalid_run':
                    g['failure_type']=None;g['diagnostic_grade']=copy.deepcopy(g)
                    for key in ['outcome_pass','harmful_action','escalated','expected_escalation','escalation_correct','unnecessary_escalation','communication_pass']:g[key]=None
                elif r.get('error_origin')=='turn_limit':g['failure_type']='state'
                r.update(g);r['grader_version']='harness_v2';write(path,r)
            attempts.append(r)
        if attempts:
            result=copy.deepcopy(attempts[-1])
            result['attempts']=[{k:a.get(k) for k in ['attempt_number','status','error_origin','run_error','api_cost_usd']} for a in attempts]
            result['total_attempt_cost_usd']=sum(a['api_cost_usd'] for a in attempts)
            write(trial/'result.json',result);results.append(result)
    write(folder/'results.json',results)
    return render(folder)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('run_name');a=p.parse_args();print(json.dumps(regrade(ROOT/'runs'/a.run_name)['overall'],indent=2))
