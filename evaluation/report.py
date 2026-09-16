"""Render saved results, including exact confirmation pairs. No API calls."""
import argparse
import json
from simulation.model_client import ROOT
from evaluation.scorecard import scorecard


def render(folder):
    results=json.loads((folder/'results.json').read_text());card=scorecard(results)
    (folder/'scorecard.json').write_text(json.dumps(card,indent=2,ensure_ascii=False)+'\n')
    o=card['overall']
    def pct(v):return 'N/A' if v is None else f'{v:.1%}'
    def num(v):return 'N/A' if v is None else f'{v:.4f}'
    rows=['# '+folder.name+' scorecard','', '| Metric | Result |','|---|---:|',
          f"| Valid trials | {o['valid_runs']}/{o['requested_trials']} |"]
    for label,key in [('Invalid run rate (final attempt)','invalid_run_rate'),('Invalid attempt rate','invalid_attempt_rate'),
                      ('Outcome pass rate','pass_rate'),('Pass³','pass3'),('Harmful action rate','harmful_action_rate'),
                      ('Correct escalation rate','correct_escalation_rate'),('Unnecessary escalation rate','unnecessary_escalation_rate'),('Communication pass rate','communication_pass_rate')]:
        rows.append(f'| {label} | {pct(o[key])} |')
    rows += [f"| Average support turns (valid only) | {num(o['average_turns'])} |",f"| Valid-run API cost (USD) | {num(o['total_cost_usd'])} |",
             f"| Cost per valid conversation (USD) | {num(o['cost_per_conversation_usd'])} |",
             f"| Total operational API spend, including retries (USD) | {num(o['operational_total_cost_usd'])} |",'',
             'All agent metrics exclude invalid runs. Pass³ requires three valid trials. Correct escalation is N/A when none was required.', '',
             '## Conversations','', '| ID | Status | Outcome | Harm | Communication | Turns | Attempts |','|---|---|---|---|---|---:|---:|']
    for r in results:
        rows.append(f"| {r['scenario_id']} | {r['status']} | {r['outcome_pass']} | {r['harmful_action']} | {r['communication_pass']} | {r['turns']} | {len(r.get('attempts',[r]))} |")
    rows+=['','## Category breakdown','','| Category | Valid trials | Pass | Harm | Communication |','|---|---:|---:|---:|---:|']
    for name,c in card['by_category'].items():rows.append(f"| {name} | {c['valid_runs']} | {pct(c['pass_rate'])} | {pct(c['harmful_action_rate'])} | {pct(c['communication_pass_rate'])} |")
    rows+=['','## Failure types','','| Type | Valid conversations | Outcome pass rate |','|---|---:|---:|']
    for name,c in card['by_failure_type'].items():rows.append(f"| {name} | {c['conversations']} | {pct(c['pass_rate'])} |")
    rows+=['','## Invalid attempt reasons','']
    reasons=o['invalid_attempt_reasons']
    rows += [f'- {reason}: {count}' for reason,count in reasons.items()] or ['None.']
    rows+=['','## Exact confirmation pairs','']
    for r in results:
        trial_folder=folder/f"{r['scenario_id']}_trial{r['trial_number']}"
        for attempt in r.get('attempts',[r]):
            ap=trial_folder/f"attempt{attempt.get('attempt_number',1)}"/'result.json'
            record=json.loads(ap.read_text()) if ap.exists() else r
            rows += [f"### {r['scenario_id']} — attempt {attempt.get('attempt_number',1)}",'']
            checks=record.get('confirmation_checks',record.get('diagnostic_grade',{}).get('confirmation_checks',[]))
            if not checks:rows+=['No Tier 2 or Tier 3 call.','']
            for c in checks:
                rows += [f"**{c['tool']}** — confirmation {'PASS' if c['pass'] else 'FAIL'}",'', '**Agent proposal:**','',
                         '\n'.join('> '+line for line in c['agent_message'].splitlines()),'', '**Customer reply:**','',
                         '\n'.join('> '+line for line in c['customer_reply'].splitlines()),'']
                if c['problems']:rows+=['Problems: '+ '; '.join(c['problems']),'']
                if c.get('acceptance_judgment'):rows+=['H5 judge: '+c['acceptance_judgment'].get('reasoning','')+' '+c['acceptance_judgment']['evidence'],'']
    rows+=['## Lowest pass³','']
    if not o['lowest_pass3']:rows+=['Not measured until each scenario has three valid trials.','']
    else:
        rows+=['| Scenario | Pass³ |','|---|---:|']
        rows += [f"| {r['scenario_id']} | {r['pass3']} |" for r in o['lowest_pass3'][:5]]
    rows+=['','## Known limitations','']+[f'- {s}' for s in card['known_limitations']]
    (folder/'scorecard.md').write_text('\n'.join(rows))
    return card

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('run_name');a=p.parse_args();render(ROOT/'runs'/a.run_name)
