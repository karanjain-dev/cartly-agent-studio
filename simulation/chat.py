"""Terminal customer chat: the human types the support side. No support agent."""
import argparse
import json
from pathlib import Path
from simulation.customer import SimulatedCustomer, ALLOWED_PROFILE, STOP
from simulation.model_client import ModelClient, ModelError, ROOT

def customer_profile(scenario):
    return {k:scenario[k] for k in ALLOWED_PROFILE}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('scenario_id',nargs='?')
    parser.add_argument('--model',default='gpt-4.1-mini')
    parser.add_argument('--list-dev',action='store_true')
    args=parser.parse_args()
    scenarios=json.loads((ROOT/'scenarios/scenarios.json').read_text())
    if args.list_dev:
        for s in scenarios:
            if s['split']=='dev':print(s['scenario_id'],s['category'])
        return 0
    s=next((s for s in scenarios if s['scenario_id']==args.scenario_id),None)
    if s is None:parser.error('Choose a scenario ID; --list-dev lists development IDs.')
    # Discard the full scenario before the model-facing object is created.
    profile=customer_profile(s);del s,scenarios
    customer=SimulatedCustomer(profile,client=ModelClient(args.model))
    config=json.loads((ROOT/'data/config.json').read_text())
    logs=ROOT/'logs/customer_chats';logs.mkdir(parents=True,exist_ok=True)
    n=1
    while (logs/f'chat_{n:04}.json').exists():n+=1
    path=logs/f'chat_{n:04}.json'
    print('You are the support representative. Type /quit to end. Maximum 20 customer turns.')
    try:
        print('Customer:',customer.reply())
        while not customer.stopped:
            try:text=input('Support: ').strip()
            except EOFError:break
            if text=='/quit':break
            if not text:continue
            try:print('Customer:',customer.reply(text))
            except ModelError as exc:
                print('Model error:',exc);break
    except (ModelError,KeyboardInterrupt) as exc:
        print('Chat ended:',str(exc))
    finally:
        path.write_text(json.dumps({'scenario_id':args.scenario_id,'timestamp':config['reference_datetime'],
            'model':args.model,'turns':customer.turns,'conversation':customer.history,'trace':customer.trace},ensure_ascii=False,indent=2)+'\n')
        print('Transcript:',path)
    return 0

if __name__=='__main__':raise SystemExit(main())
