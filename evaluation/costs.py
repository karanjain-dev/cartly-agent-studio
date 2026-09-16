"""USD estimates from API usage and published standard text-token prices."""
RATES = {'gpt-5.6-luna':{'input':0.2,'cached':0.02,'cache_write':0.25,'output':1.2},
         'gpt-5.6-terra':{'input':2,'cached':0.2,'cache_write':2.5,'output':12},
         'gpt-6-astra':{'input':10,'cached':1,'cache_write':12.5,'output':50},
         'gpt-4.1-mini':{'input':0.4,'cached':0.1,'cache_write':0.4,'output':1.6}}
SOURCES = ['https://developers.openai.com/api/docs/models/gpt-5.6-luna',
           'https://developers.openai.com/api/docs/models/gpt-5.6-terra',
           'https://developers.openai.com/api/docs/models/gpt-6-astra',
           'https://developers.openai.com/api/docs/models/gpt-4.1-mini']

def cost(model,usage):
    family=next((m for m in RATES if model==m or model.startswith(m+'-')),None)
    if family is None:raise ValueError('No verified pricing for '+model)
    r=RATES[family];details=usage.get('input_tokens_details',{})
    cached=details.get('cached_tokens',0)
    written=details.get('cache_creation_tokens',details.get('cache_write_tokens',0))
    inputs=usage.get('input_tokens',0);outputs=usage.get('output_tokens',0)
    if inputs>272000 and family in {'gpt-6-astra','gpt-5.6-luna','gpt-5.6-terra'}:raise ValueError('Long-context pricing not configured for this baseline')
    return ((inputs-cached-written)*r['input']+cached*r['cached']+written*r['cache_write']+outputs*r['output'])/1_000_000
