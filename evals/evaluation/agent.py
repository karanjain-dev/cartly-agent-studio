"""Baseline agent: exact saved system prompt plus all unguarded Cartly tools."""
import json
from evaluation.api import request
from evaluation.tool_schema import schemas
from evaluation.state import changes
from simulation.model_client import ModelError

class SupportAgent:
    def __init__(self, session, prompt, model, recorder, *, transport=request):
        if session.guarded:raise ValueError('Baseline requires unguarded tools')
        self.session=session;self.prompt=prompt;self.model=model;self.recorder=recorder
        self.transport=transport;self.input=[];self.resolved_models=set();self.turns=0

    def reply(self, customer_text, transcript):
        if self.turns>=20:raise ModelError('Agent conversation turn limit reached')
        self.turns+=1
        self.input.append({'role':'user','content':customer_text})
        text=[]
        # Bounds internal tool loops separately from customer/support exchanges.
        for round_no in range(20):
            body={'model':self.model,'input':self.input,'instructions':self.prompt,
                  'tools':schemas(),'parallel_tool_calls':False,'max_output_tokens':8192,
                  'reasoning':{'effort':'high'},'store':False,'include':['reasoning.encrypted_content']}
            raw=self.transport('responses',body)
            self.recorder('agent',body,raw)
            self.resolved_models.add(raw['model'])
            if raw.get('status')!='completed':raise ModelError('Agent response incomplete: '+str(raw.get('incomplete_details')))
            self.input.extend(raw.get('output',[]))
            calls=[]
            for item in raw.get('output',[]):
                if item['type']=='function_call':calls.append(item)
                elif item['type']=='message':
                    message=''.join(c.get('text','') for c in item.get('content',[]) if c['type']=='output_text')
                    if message:
                        text.append(message);transcript.append({'role':'support','content':message,'turn':self.turns})
            if not calls:
                if not text:raise ModelError('Agent returned no customer-facing text')
                return '\n'.join(text)
            for call in calls:
                before=self.session.state
                try:
                    args=json.loads(call['arguments'])
                    if not isinstance(args,dict):raise ValueError('Expected an object')
                    result=self.session.call(call['name'],**args)
                except (ValueError,TypeError):
                    args={'invalid_json':call['arguments']}
                    result=self.session.call(call['name'],**args)
                transcript.append({'role':'tool','tool_name':call['name'],'arguments':args,
                                   'call_id':call['call_id'],'turn':self.turns,'changes':changes(before,self.session.state),**result})
                self.input.append({'type':'function_call_output','call_id':call['call_id'],
                                   'output':json.dumps(result,ensure_ascii=False)})
        raise ModelError('Agent exceeded 20 tool rounds within one conversation turn')
