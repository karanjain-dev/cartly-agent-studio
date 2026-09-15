"""Three live semantic-gate regression checks; no agent conversations."""
import json
from simulation.model_client import ROOT
from simulation.chat import customer_profile
from simulation.customer import SimulatedCustomer
from evaluation.run import Recorder,LoggedClient,write

def main():
    s=next(s for s in json.loads((ROOT/'scenarios/scenarios.json').read_text()) if s['scenario_id']=='S035')
    out=ROOT/'validation_reports/semantic_gate_v2';n=1
    while out.exists():
        n+=1;out=ROOT/f'validation_reports/semantic_gate_v2_{n}'
    out.mkdir(parents=True,exist_ok=False)
    recorder=Recorder(out,json.loads((ROOT/'data/config.json').read_text())['reference_datetime'])
    results=[]
    for question,expected in [("Is the size you received different from what you ordered?",True),
                              ("Did we send a different size, or does it just not fit?",True),
                              ("What's the problem?",False)]:
        c=SimulatedCustomer(customer_profile(s),client=LoggedClient('simulator_gate','gpt-4.1-mini',recorder))
        c.turns=1;c._release(question)
        actual='problem' in c.released
        results.append({'question':question,'expected_release':expected,'actual_release':actual,'pass':actual==expected,'decisions':c.trace[-1]['decisions']})
    write(out/'results.json',results)
    print(json.dumps(results,indent=2))
    assert all(r['pass'] for r in results)

if __name__=='__main__':main()
