"""Retry an audited simulator/runner malfunction once; retain the first attempt."""
import argparse
import copy
import json
from simulation.model_client import ROOT
from evaluation.run import run_conversation,write,protected_hashes
from evaluation.scorecard import scorecard


def recover(run_name,scenario_id,evidence):
    # This entry point is for an explicitly audited harness error, not outcome retries.
    if evidence.get('error_origin') not in {'simulator','runner','api'} or not evidence.get('reason') or not evidence.get('evidence'):
        raise ValueError('A concrete infrastructure-error audit is required')
    root=ROOT/'runs'/run_name
    results=json.loads((root/'results.json').read_text())
    index=next(n for n,r in enumerate(results) if r['scenario_id']==scenario_id and r['trial_number']==1)
    final=results[index];trial=root/f'{scenario_id}_trial1'
    if len(final['attempts'])!=1 or (trial/'attempt2').exists():raise ValueError('The single allowed retry is already used')
    s=next(s for s in json.loads((ROOT/'scenarios/scenarios.json').read_text()) if s['scenario_id']==scenario_id)
    if s['split']!='dev':raise ValueError('This recovery entry point is dev-only')
    first_path=trial/'attempt1/result.json';first=json.loads(first_path.read_text())
    write(trial/'attempt1/pre_audit_result.json',first)
    write(trial/'attempt1/infrastructure_error_audit.json',evidence)
    first['diagnostic_grade']=copy.deepcopy(first)
    first.update(status='invalid_run',run_error=evidence['reason'],error_origin=evidence['error_origin'])
    for key in ['outcome_pass','harmful_action','escalated','expected_escalation','escalation_correct','unnecessary_escalation','communication_pass','failure_type']:
        first[key]=None
    write(first_path,first)
    original=protected_hashes()
    write(trial/'attempt2_manifest.json',{'protected_files':original,'retry_reason':evidence,'harness_revision':'v3.1'})
    try:
        second=run_conversation(s,1,trial/'attempt2',run_name,final['agent_model_requested'])
    finally:
        assert protected_hashes()==original,'Protected files changed during recovery'
    second['attempt_number']=2;second['harness_revision']='v3.1'
    write(trial/'attempt2/result.json',second)
    final=copy.deepcopy(second)
    final['attempts']=[{k:r.get(k) for k in ['attempt_number','status','error_origin','run_error','api_cost_usd']} for r in [first,second]]
    final['total_attempt_cost_usd']=first['api_cost_usd']+second['api_cost_usd']
    write(trial/'result.json',final)
    results[index]=final
    write(root/'results.json',results);write(root/'scorecard.json',scorecard(results))
    print(json.dumps({k:final[k] for k in ['scenario_id','status','outcome_pass','harmful_action','communication_pass','turns','api_cost_usd']}))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('run_name');p.add_argument('scenario_id');p.add_argument('--audit',required=True)
    a=p.parse_args();recover(a.run_name,a.scenario_id,json.loads((ROOT/a.audit).read_text()))
