"""Responses API transport; all project timestamps use config, never wall time."""
import json
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from threading import Event
from simulation.model_client import api_key, ModelError, ROOT


def request(path, body=None):
    req = Request('https://api.openai.com/v1/'+path,
                  data=None if body is None else json.dumps(body).encode(),
                  headers={'Authorization':'Bearer '+api_key(), 'Content-Type':'application/json'})
    for attempt in range(6):
        try:
            with urlopen(req, timeout=180) as response:
                return json.load(response)
        except HTTPError as exc:
            detail = exc.read().decode()
            if exc.code == 429 and attempt < 5:
                Event().wait(15); continue
            raise ModelError(f'OpenAI API HTTP {exc.code}: {detail}') from None
        except URLError as exc:
            raise ModelError('OpenAI API connection failed: '+str(exc.reason)) from None


def list_models():
    models = sorted(m['id'] for m in request('models')['data'])
    out = ROOT/'evaluation/available_models.json'
    out.write_text(json.dumps({'reference_date':json.loads((ROOT/'data/config.json').read_text())['today'],
                               'models':models}, indent=2)+'\n')
    return models

if __name__ == '__main__':
    print('\n'.join(list_models()))
