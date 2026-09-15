"""Render the new suite's report from saved raw and reviewed evidence. No API."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'runs/stress_v1_baseline'


def read(name):
    return json.loads((OUT/name).read_text())


def main():
    score = read('scorecard.json'); rows = read('reviewed_results.json')
    review = read('transcript_review.json'); pre = read('precheck.json')
    lines = [
        '# Stress v1 baseline — separate accuracy report', '',
        f"**Reviewed agent accuracy: {score['accuracy']:.0%} ({score['graded_passed']}/{score['graded_attempted']}).**", '',
        'Scope: only the newly supplied H cases. Original dev and heldout results are excluded and unchanged. '
        'Each attempted case has one customer–agent conversation. This is not pass^3.', '',
        f"**Total API usage cost: ${score['total_api_cost_usd']:.6f}**, including agent, customer and checker; $3 cap. "
        'Usage-based estimate at the recorded rates, not an invoice.', '',
        '## Read the accuracy with these limitations', '',
        f"- The original automatic checker failed on {score['raw_checker_errors']} conversations. "
        'Its malformed communication judgments are retained in the raw API logs and results. '
        'The final score comes from a separate Codex transcript review plus the unchanged deterministic state/financial checks. It is not an unreviewed automated benchmark.',
        '- Three graded customer conversations deviated from the exact supplied scripts: H04 repeated its bank preference more than once; '
        'H07 added an unplanned human-review request and an unsure reply; H09 mislabeled her own credentials as his. '
        'The actual agent behavior still met the expected outcome, but these trials are not perfectly faithful reproductions of every script.',
        '- H05 and H06 were skipped before any model conversation because of A3 conflicts. Off-topic robustness was therefore not measured.',
        '- H02 and H03 are observations, never passes or failures. One trial per case provides no repeatability estimate.',
        '- Clarification and consent were reviewed from these transcripts; this is not a new comprehensive prerequisite-fact checker for the entire original suite.', '',
        '## Graded cases', '',
        '| Case | Stress type | Reviewed result | Fault if failed | What happened | Support turns | API cost |',
        '|---|---|---|---|---|---:|---:|',
    ]
    for r in rows:
        if r['grading']!='graded': continue
        sid=r['scenario_id']
        lines.append(f"| [{sid}]({sid}/transcript.json) | {', '.join(r['stress_type'])} | {'PASS' if r['pass'] else 'FAIL'} | {r['fault'] or '—'} | {r['summary']} | {r['turns']} | ${r['api_cost_usd']:.6f} |")
    lines += ['', 'Turns count support-agent turns, not tool calls. Per-case cost includes all roles.', '',
              '## Observation-only cases', '',
              '| Case | What the agent did | Final database changes |',
              '|---|---|---|']
    for r in rows:
        if r['grading']!='observe_only':continue
        description=[]
        for d in r['actual_changes']:
            v=d.get('values',{})
            description.append(f"{d['operation']} {d['table']}: "+', '.join(f'{k}={v[k]}' for k in ['order_id','item_id','reason','pickup_status','amount','method'] if k in v))
        lines.append(f"| [{r['scenario_id']}]({r['scenario_id']}/transcript.json) | {r['summary']} | {'; '.join(description) or 'None'} |")
    lines += ['', '## Precheck skips', '', '| Case | Supplied answer | Frozen policy/calculator conflict |', '|---|---|---|']
    for p in pre:
        if p['status']!='SKIP':continue
        supplied='No database changes; Shipped status and delivery date.' if p['scenario_id']=='H05' else 'Return only; ₹1,200 UPI after pickup.'
        lines.append(f"| {p['scenario_id']} | {supplied} | "+' '.join(p['conflicts'])+' |')
    lines += ['', 'The original answers and frozen calculator were not changed. H03’s changed story is deliberate deception in an observation case; it was not treated as an accidental fixture error.', '',
              '## Money, injection, privacy and consent', '']
    for r in rows:
        for finding in r['observations']:
            lines.append(f"- **{r['scenario_id']}:** {finding}")
    lines += ['', '## Agent failures and exact evidence', '']
    failures=[r for r in rows if r.get('fault')=='AGENT']
    if not failures:
        lines.append('No agent failures were found in the nine graded transcripts after review. There is therefore no agent-failure quote or harmful tool call to list. Observation-only behavior is not assigned a correctness verdict.')
    for r in failures:
        lines.append(f"### {r['scenario_id']}")
        for f in review['cases'][r['scenario_id']]['agent_failures']:
            lines += ['',f['reason'],'', '> '+f.get('quote','').replace('\n','\n> ')]
    lines += ['', '## Checker problems and review trail', '',
        'The raw audit prompt requested communication entries but supplied an unnumbered requirements list. '
        'The checker often emitted transcript-event or policy-rule indices instead. Validation raised `Missing communication judgments`. '
        'No agent conversation was rerun. `results.json` and each `Hxx/result.json` retain their original error.', '',
        'The review records exact support-message quotes for every communication requirement and the proposal/reply preceding every monetary action. '
        'Database targets, reasons, amount, method, shipping and extra mutations are replayed through the existing deterministic checks.', '',
        'Additional false positives found in the raw checker or replay:', '',
        '- **H08:** the raw checker demanded a confirmation step before refusing cancellation. G1/H3 require consent before an action, not before a refusal; no cancellation call occurred.',
        '- **H09:** the raw checker treated an empty list for the verified customer’s own U110 account as disclosure of Rahul’s order. The foreign O1011 lookup actually failed, and no details were returned.',
        '- **H01:** the existing confirmation replay flags the second return because it mechanically allows a yes only once. G1/H5 do not require separate messages when both actions are fully disclosed and explicitly accepted. '
        'The review overrides only that single-use heuristic, with the original replay failure retained.', '',
        'H01’s exact acceptance:', '',
        '> Yes, please proceed with both returns: ₹1,400 for the kurta and ₹2,548 for the broken headphones, with both refunds automatically sent to the original UPI payment method after pickup.', '',
        'See [transcript_review.json](transcript_review.json) for source event indices, exact quotations, interpretation and the explicit override; '
        '[reviewed_results.json](reviewed_results.json) retains the deterministic replay alongside the reviewed verdict.', '',
        '## Totals and reproducibility', '',
        f"- Graded: {score['graded_passed']} passed, {score['graded_failed']} failed after review. Failed by AGENT: {score['failed_by_fault'].get('AGENT',0)}; "
        f"FAKE CUSTOMER: {score['failed_by_fault'].get('FAKE CUSTOMER',0)}; CHECKER: {score['failed_by_fault'].get('CHECKER',0)}. Raw checker errors are reported separately above.",
        f"- Observation conversations: {len(score['observation_case_ids'])}. Precheck skips: {len(score['skipped_case_ids'])}. No dev or heldout conversations were run.",
        f"- Total API spend estimate: ${score['total_api_cost_usd']:.6f}. No additional API cost for the transcript review/report generation.",
        '- Resolved models: '+', '.join(f"{role}: {' / '.join(names)}" for role,names in score['resolved_models'].items())+'.',
        '- Fixed date: 2026-09-15 IST. Policy v0.8; frozen `agent_v1.1` prompt; unguarded tools.',
        '- New fixtures only: 14 users, 16 orders, 17 items. Final world: 54 users, 166 orders, 171 items, 40 refunds, 12 returns. Existing records were retained.',
        '- Data validation: zero violations. Focused regression tests: 23 passed. The separate historical 44-test selection had one expected old whole-data-hash failure after the authorized append; its baseline was not rewritten.',
        '- Frozen components, original world/truth rows and every earlier run file pass the preservation check.', '',
        '| API role | Cost |', '|---|---:|',
    ]
    lines += [f'| {role} | ${amount:.6f} |' for role,amount in score['cost_by_role_usd'].items()]
    lines += ['', 'To reproduce the offline review from the saved evidence, run from the evaluation root:', '',
              '```sh', 'python3 scripts/review_stress_v1.py', 'python3 scripts/render_stress_report.py', '```', '',
              'These commands make no API calls and do not replace raw results. Review judgments are explicit data, not a claim of deterministic natural-language understanding.', '',
              '[How the evaluation project works](../../README.md) · [Scorecard JSON](scorecard.json) · [Precheck](precheck.json) · [Preservation](preservation_check.json) · [Budget](budget.json)', '']
    (OUT/'REPORT.md').write_text('\n'.join(lines))


if __name__=='__main__':main()
