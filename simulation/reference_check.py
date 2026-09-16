"""Compare the deterministic oracle to saved labels without editing fixtures."""
import hashlib
import json
from simulation.reference_calculator import calculate_scenario
from simulation.structured_check import ROOT, projected_expected


def matches(calculated, expected):
    a, b = dict(calculated), dict(expected)
    if a['outcome_type'] == b['outcome_type'] == 'decline_no_change':
        a['item_id'] = b['item_id'] = None
    return a == b


def main():
    path = ROOT/'scenarios/scenarios.json'
    original = path.read_bytes()
    scenarios = json.loads(original)
    world = {n:json.loads((ROOT/'data'/f'{n}.json').read_text()) for n in
             ['config','users','orders','order_items','refunds','returns','serviceable_pincodes']}
    assert '# Cartly Customer Support Policy v0.5' in (ROOT/'policy.md').read_text()
    rows = []
    for s in scenarios:
        decision = calculate_scenario(world, s['user_id'], s['hidden_facts'])
        expected = projected_expected(s, world)
        status = 'CONFIRMED' if any(matches(decision, e) for e in expected) else 'SCENARIO_WRONG'
        rows.append(dict(scenario_id=s['scenario_id'], split=s['split'], status=status,
                         expected=expected, calculated=decision))
    counts = {sp:{status:sum(r['split']==sp and r['status']==status for r in rows)
                  for status in ['CONFIRMED','SCENARIO_WRONG']} for sp in ['dev','heldout']}
    report = dict(policy_version='v0.5', scenario_sha256=hashlib.sha256(original).hexdigest(), counts=counts,
                  note='Expected states use the existing eight-field projection; no outcome labels enter the calculator. Escalation alternatives retain the prior projection convention.',
                  dev_results=[r for r in rows if r['split']=='dev'],
                  heldout_results=[{k:r[k] for k in ['scenario_id','status']} for r in rows if r['split']=='heldout'])
    out = ROOT/'scenarios/reference_check';out.mkdir(exist_ok=True)
    (out/'report.json').write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n')
    assert path.read_bytes()==original
    print(json.dumps(report, indent=2, ensure_ascii=False))

if __name__=='__main__':main()
