"""Build an accuracy report with transparent transcript-only grading recovery."""
import json
from pathlib import Path
from collections import Counter
from evaluation.run import write
from simulation.model_client import ROOT
root=ROOT/'runs/luna_customer_30_single'
original=json.loads((root/'results.json').read_text())
manifest=json.loads((root/'manifest.json').read_text())
assert len(original)==len(manifest['scenario_ids'])==30
assert {r['scenario_id'] for r in original}==set(manifest['scenario_ids'])
assert all(r['trial_number']==1 and len(r['attempts'])==1 for r in original)
rows=[];review_cost=0
for r in original:
    r=dict(r)
    p=root/'grading_review'/r['scenario_id']/'result.json'
    if p.exists():
        review=json.loads(p.read_text());review_cost+=review['review_cost_usd']
        r.update({k:v for k,v in review.items() if k not in ['source_attempt','review_cost_usd']})
        r['status']='valid_run';r['grading_recovered']=True
    else:r['grading_recovered']=False
    assert r['simulator_model']=='gpt-5.6-luna'
    assert r['agent_model']=='gpt-6-astra'
    rows.append(r)
valid=[r for r in rows if r['status']=='valid_run']
summary={'sessions':len(rows),'sessions_per_scenario':1,'customer_model':'gpt-5.6-luna','customer_reasoning_effort':'none','support_model':'gpt-6-astra','judge_model':'gpt-4.1-mini','scored_sessions':len(valid),'outcome_passes':sum(r['outcome_pass'] for r in valid),'communication_passes':sum(r['communication_pass'] is True for r in valid),'harmful_actions':sum(r['harmful_action'] for r in valid),'all_checks_passes':sum(r['outcome_pass'] and r['communication_pass'] and not r['harmful_action'] and r['failure_type'] is None for r in valid),'initial_grading_errors':sum(r['status']=='invalid_run' for r in original),'recovered_grading_errors':sum(r['grading_recovered'] for r in rows),'session_replays':0,'estimated_total_cost_usd':sum(r['total_attempt_cost_usd'] for r in original)+review_cost,'grading_review_cost_usd':review_cost,'failed_scenarios':[r['scenario_id'] for r in valid if not r['outcome_pass']]}
summary['outcome_accuracy']=summary['outcome_passes']/len(valid) if valid else None
summary['failure_types']=dict(Counter(r['failure_type'] for r in valid if not r['outcome_pass']))
write(root/'reviewed_results.json',rows);write(root/'accuracy_summary.json',summary)
lines=['# Luna customer: 30-scenario accuracy report','','## Configuration','','- 30 development scenarios; exactly one customer/support session per scenario, with no session replays.','- Customer and its fact/grounding checks: GPT-5.6 Luna, reasoning effort none.','- Support: GPT-6 Astra, high reasoning. Communication/confirmation judge: GPT-4.1 mini.','- Business correctness uses the existing deterministic reference and exact database changes.','', '## Results','','| Metric | Result |','|---|---:|',f"| Outcome accuracy | {summary['outcome_passes']}/{len(valid)} ({summary['outcome_accuracy']:.1%}) |",f"| Communication passes | {summary['communication_passes']}/{len(valid)} |",f"| Sessions with harmful actions | {summary['harmful_actions']}/{len(valid)} |",f"| All checks passed | {summary['all_checks_passes']}/{len(valid)} |",f"| Estimated API cost, including grading rechecks | ${summary['estimated_total_cost_usd']:.4f} |",'', '## Grading reliability','',f"The first grading pass had {summary['initial_grading_errors']} invalid assessments. {summary['recovered_grading_errors']} were recovered by rechecking the saved transcripts only. Original results are preserved in results.json and per-attempt folders; the recovered assessments are separate under grading_review. No customer or support session was repeated.",'', '## Every scenario','','| Scenario | Outcome | Communication | Harm | Failure type | Grading recheck |','|---|---|---|---|---|---|']
for r in rows:
    label=lambda v:'N/A' if v is None else ('PASS' if v else 'FAIL')
    lines.append(f"| {r['scenario_id']} | {label(r['outcome_pass'])} | {label(r['communication_pass'])} | {r['harmful_action']} | {r['failure_type'] or '—'} | {'Yes' if r['grading_recovered'] else 'No'} |")
lines+=['','## Failed outcomes','']
for r in valid:
    if r['outcome_pass']:continue
    lines += [f"### {r['scenario_id']} — {r['failure_type']}",'',f"Expected: `{r['reference_outcome']['outcome_type']}`. Actual changes: "+', '.join(c['operation']+' in '+c['table'] for c in r['actual_changes'])+'.']
    for h in r.get('harmful_details',[]):lines.append('- '+json.dumps(h,ensure_ascii=False))
    for c in r['actual_changes']:
        if c['table']=='escalations':lines.append('- Handoff request: '+c['values'].get('user_request',''))
    lines.append('')
lines+=['## Other check failures','', 'S028 passed the business outcome, communication, and harmful-action checks but was assigned an understanding failure by the procedural clarification check. It is excluded from the all-checks pass count.','', 'S030 was marked down because the judge wanted an explicit statement that the refund was immediate, although support said it had already been processed. This may be an overly literal grading decision; the original score is retained.','', 'S031 escalated the electrical-safety report against O0001; the expected target was O0035. The saved support summary acknowledged that the customer had not confirmed O0001 as the affected purchase.','', '## Interpretation and limits','','This is accuracy for the support agent interacting with a Luna customer simulator on these 30 development cases. It is not a standalone benchmark of Luna, and one trial cannot measure repeatability. The harness has no prerequisite-fact check, so some passes may be lucky. Communication and confirmation rely on model judgments.','', 'S001 required 12 support turns. Its customer profile does not explicitly state the change-of-mind reason expected by the reference, causing repeated clarification before eventual completion.','', 'Pricing uses recorded API tokens and the configured standard rates, including [official Luna pricing](https://developers.openai.com/api/docs/models/gpt-5.6-luna); it is an estimate rather than an invoice.','']
(root/'accuracy_report.md').write_text('\n'.join(lines))
print(json.dumps(summary,indent=2))
