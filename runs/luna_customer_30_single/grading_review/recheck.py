"""Recheck a failed judge on a saved transcript; no customer/agent replay."""
import json
from pathlib import Path
from evaluation.run import LoggedClient, Recorder, write
from evaluation.judge import judge
from evaluation.grader import grade
from simulation.model_client import ROOT
root=ROOT/'runs/luna_customer_30_single'
scenarios={s['scenario_id']:s for s in json.loads((ROOT/'scenarios/scenarios.json').read_text())}
for trial in sorted(root.glob('S*_trial1')):
    sid=trial.name.split('_')[0]
    if not (trial/'result.json').exists() or (root/'grading_review'/sid/'result.json').exists():continue
    folder=root/f'{sid}_trial1/attempt1'
    original=json.loads((folder/'result.json').read_text())
    if original['status']!='invalid_run' or original['run_error']!='Judge omitted or duplicated communication checks':continue
    out=root/'grading_review'/sid
    out.mkdir(exist_ok=False)
    recorder=Recorder(out,original['timestamp'])
    transcript=json.loads((folder/'transcript.json').read_text())
    judgment=judge(scenarios[sid],transcript,LoggedClient('judge','gpt-4.1-mini',recorder))
    result=grade(scenarios[sid],json.loads((folder/'initial_state.json').read_text()),json.loads((folder/'final_state.json').read_text()),transcript,judgment)
    write(out/'result.json',{'scenario_id':sid,'source_attempt':str(folder.relative_to(root)), 'review_type':'judge_only_no_session_replay','original_error':original['run_error'],'review_cost_usd':sum(r['cost_usd'] for r in recorder.records),**result})
    print(json.dumps({'scenario_id':sid,**{k:result[k] for k in ['outcome_pass','harmful_action','communication_pass']}}))
