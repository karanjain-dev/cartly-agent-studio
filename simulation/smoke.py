"""Live dev-only customer smoke checks with scripted human-side test messages."""
import json
from pathlib import Path
from simulation.chat import customer_profile
from simulation.customer import SimulatedCustomer, STOP
from simulation.model_client import ROOT

def main():
    scenarios=json.loads((ROOT/'scenarios/scenarios.json').read_text());out=[]
    scripts={
      'S028':['Please provide your user ID and registered email.','Which order and item is this about?',
              'Has the kurta been worn or used?',
              'The receipt shows ₹1,499. After the ₹99 pickup fee, the refund is ₹1,400 to UPI after pickup. Do you agree?',
              'I understand, but the receipt amount is ₹1,499. I can arrange the return for ₹1,400 to UPI after pickup. Please confirm.',
              'Your return is now scheduled. The ₹1,400 refund will go to UPI after pickup completes.'],
      'S035':['Please provide your user ID and registered email.','What is the order ID?',
              'Does the delivered size differ from the size you ordered, or is it a fit issue?',
              'I can arrange a return for the wrong size delivered. You will receive ₹1,548 to UPI after pickup, including shipping. Do you confirm?',
              'Your return is now scheduled. The refund of ₹1,548 to UPI will happen automatically after pickup.']}
    for sid,turns in scripts.items():
        scenario=next(s for s in scenarios if s['scenario_id']==sid)
        assert scenario['split']=='dev'
        c=SimulatedCustomer(customer_profile(scenario));c.reply()
        for turn in turns:
            if c.stopped:break
            c.reply(turn)
        out.append({'scenario_id':sid,'conversation':c.history,'trace':c.trace,'stopped':c.stopped})
        print(sid,'live customer turns',c.turns,'stopped',c.stopped,flush=True)
    path=ROOT/'validation_reports/live_customer_smoke.json';path.write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
    assert all(r['stopped'] for r in out),'Live conversations did not stop after completion'
    assert all('now scheduled' in r['conversation'][-2]['content'] for r in out),'Customer stopped on an offer instead of completion'
    return 0
if __name__=='__main__':raise SystemExit(main())
