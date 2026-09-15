"""Reproduce the stress scorecard from an explicit, transcript-grounded review.

No model calls and no rewriting of original results. Review judgments are data,
not claimed to be deterministic language understanding. Exact financial/state
checks still use the existing calculator and grader.
"""
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from evaluation.stress import deterministic_grade, preservation

OUT = ROOT/'runs/stress_v1_baseline'


def read(path):
    return json.loads(path.read_text())


def main():
    raw = read(OUT/'results.json')
    review = read(OUT/'transcript_review.json')
    scenarios = {s['scenario_id']: s for s in read(ROOT/'scenarios/stress_v1.json')}
    prechecks = {p['scenario_id']: p for p in read(OUT/'precheck.json')}
    rows = []
    for r in raw:
        sid = r['scenario_id']; s = scenarios[sid]; folder = OUT/sid
        transcript = read(folder/'transcript.json')
        v = review['cases'][sid]
        for evidence in v['evidence']:
            event = transcript[evidence['event_index']]
            assert evidence['quote'] in event.get('content', ''), (sid, 'quote mismatch')
        assert len(v['communication']) == len(s['must_communicate'])
        assert {c['index'] for c in v['communication']} == set(range(len(s['must_communicate'])))
        row = {k:r[k] for k in ['scenario_id','grading','stress_type','turns','api_cost_usd','end_reason']}
        row.update(raw_status=r['status'], raw_pass=r['pass'], raw_fault=r['fault'],
                   review_method=review['method'], summary=v['summary'],
                   customer_deviations=v['customer_deviations'], observations=v['observations'])
        if s['grading'] == 'graded':
            # The business decisions come unchanged from the pre-run calculator.
            g = deterministic_grade(s,read(folder/'initial_state.json'),read(folder/'final_state.json'),
                                    transcript,prechecks[sid]['reference_decisions'],v['authorization'])
            row['deterministic_replay'] = g
            failures = list(g['failures'])
            for override in v.get('checker_overrides', []):
                assert override['policy_basis'] and override['evidence_indices']
                matches = [f for f in failures if f.get('event_index') == override['event_index']
                           and f['reason'] == override['failure_reason']]
                assert len(matches) == 1, (sid, 'unmatched override')
                failures.remove(matches[0])
            row['checker_overrides'] = v.get('checker_overrides', [])
            failures += v['agent_failures']
            if not all(c['pass'] for c in v['communication']):
                failures.append({'reason':'Required communication missing'})
            if r['end_reason'] in {'invalid_run','budget_stop','turn_limit'}:
                failures.append({'reason':r['end_reason']})
            row['failures'] = failures
            row['pass'] = not failures
            row['fault'] = v['failure_attribution'] if failures else None
            if failures:
                assert row['fault'] in {'AGENT','FAKE CUSTOMER','CHECKER'}
        else:
            row.update(pass_=None, fault=None, actual_changes=r['actual_changes'])
            row['pass'] = row.pop('pass_')
        rows.append(row)
    graded = [r for r in rows if r['grading']=='graded']
    passed = sum(r['pass'] for r in graded)
    api_rows = [json.loads(line) for p in OUT.glob('H*/api_calls.jsonl') for line in p.read_text().splitlines()]
    cost_by_role = {role:sum(r.get('cost_usd',0) for r in api_rows if r['role']==role)
                    for role in sorted({r['role'] for r in api_rows})}
    models = {role:sorted({r['response']['model'] for r in api_rows if r['role']==role and 'response' in r})
              for role in cost_by_role}
    budget = read(OUT/'budget.json')
    assert abs(sum(cost_by_role.values())-budget['observed_cost_usd'])<1e-8
    assert budget['observed_cost_usd']+budget['uncertain_reserved_usd'] <= 3
    summary = {
        'run_name':'stress_v1_baseline', 'scope':'stress_v1 only; no dev or heldout results',
        'accuracy_method':review['method'], 'graded_attempted':len(graded),
        'graded_passed':passed, 'graded_failed':len(graded)-passed,
        'accuracy':passed/len(graded) if graded else None,
        'failed_by_fault':dict(Counter(r['fault'] for r in graded if not r['pass'])),
        'raw_checker_errors':sum(r['status']=='checker_error' for r in raw),
        'customer_script_deviation_case_ids':[r['scenario_id'] for r in rows if r['customer_deviations']],
        'observation_case_ids':[r['scenario_id'] for r in rows if r['grading']=='observe_only'],
        'skipped_case_ids':[sid for sid,p in prechecks.items() if p['status']=='SKIP'],
        'total_api_cost_usd':budget['observed_cost_usd'],
        'cost_by_role_usd':cost_by_role, 'resolved_models':models,
        'preservation':preservation(), 'trials_per_case':1, 'pass3':None,
    }
    for name, value in [('reviewed_results.json',rows),('scorecard.json',summary)]:
        (OUT/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(summary,ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
