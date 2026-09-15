"""Small Responses API client. No SDK, no system-clock reads, no secret logging."""
import json
import os
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from threading import Event
import re

ROOT=Path(__file__).resolve().parents[1]

class ModelError(RuntimeError):pass

def api_key():
    key=os.environ.get('OPENAI_API_KEY')
    if not key:
        path=ROOT/'.env'
        if path.exists():
            for line in path.read_text().splitlines():
                if line.startswith('OPENAI_API_KEY=[REDACTED]
                    key=line.split('=',1)[1].strip().strip('"').strip("'");break
    if not key:raise ModelError('OPENAI_API_KEY is missing. Set it in the environment or project .env.')
    return key

class ModelClient:
    def __init__(self,model='gpt-4.1-mini'):
        self.model=model
    def complete(self,instructions,payload,*,max_tokens=2400,response_schema=None):
        body={'model':self.model,'instructions':instructions,'input':'Return a JSON object.\n'+json.dumps(payload,ensure_ascii=False),
              'text':{'format':{'type':'json_object'}},'max_output_tokens':max_tokens,'store':False}
        if response_schema is not None:
            body['text']['format']={'type':'json_schema','name':'cartly_decision','schema':response_schema,'strict':True}
        request=Request('https://api.openai.com/v1/responses',data=json.dumps(body).encode(),
                        headers={'Authorization':'Bearer '+api_key(),'Content-Type':'application/json'})
        for attempt in range(12):
            try:
                with urlopen(request,timeout=90) as response:raw=json.load(response)
                break
            except HTTPError as exc:
                try: detail=json.loads(exc.read()).get('error',{}).get('message','Request rejected')
                except (ValueError,AttributeError):detail='Request rejected'
                if exc.code==429 and attempt<11:
                    match=re.search(r'try again in ([0-9.]+)s',detail)
                    delay=min(60,max(3,float(match[1])+1 if match else 10))
                    Event().wait(delay)  # duration only; never used as a project clock
                    continue
                raise ModelError(f'OpenAI API HTTP {exc.code}: {detail}') from None
            except URLError as exc:raise ModelError('OpenAI API connection failed: '+str(exc.reason)) from None
        texts=[c['text'] for item in raw.get('output',[]) for c in item.get('content',[]) if c.get('type')=='output_text']
        if raw.get('status')!='completed' or not texts:raise ModelError('Model response incomplete or empty')
        try:value=json.loads(''.join(texts))
        except ValueError:raise ModelError('Model did not return valid JSON') from None
        return {'value':value,'response_id':raw['id'],'model':raw['model'],'usage':raw.get('usage',{})}
