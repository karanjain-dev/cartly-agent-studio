"""Require profile evidence before answering factual customer questions."""
import json
from simulation.model_client import ModelError

INSTRUCTIONS='''Identify each factual question addressed to the customer in the representative's latest message. Use only the customer profile and current-date environment. Do not answer the question yourself. For each question quote the shortest exact profile/environment text that explicitly gives the answer, or use an empty source_quote if the answer is unknown. No inference from absence: a profile that says nothing about SMS does not establish that no SMS arrived. Do not infer delivery pincodes from user IDs, cities, or email. For 'Did you get a confirmation SMS?' with no SMS fact, include the question with source_quote="". For 'What is your delivery pincode?' with no pincode fact, include it with source_quote="". Quotes must be literal substrings of the supplied JSON values. Questions asking for consent, a preference, or a desired next action do not request a pre-existing factual detail; omit those. A pure action-completion statement contains no factual question. Return JSON with factual_questions, an array of {question, source_quote}. Include every factual question even when its answer is absent.'''
SCHEMA={'type':'object','additionalProperties':False,'required':['factual_questions'],'properties':{
    'factual_questions':{'type':'array','items':{'type':'object','additionalProperties':False,'required':['question','source_quote'],
                                             'properties':{'question':{'type':'string'},'source_quote':{'type':'string'}}}}}}

def check(client,profile,environment,agent_message):
    source={'profile':profile,'environment':environment}
    result=client.complete(INSTRUCTIONS,{'task':'customer_answerability',**source,'latest_agent_message':agent_message},
                           max_tokens=1100,response_schema=SCHEMA)
    value=result['value']
    if not isinstance(value,dict) or set(value)!={'factual_questions'} or not isinstance(value['factual_questions'],list):
        raise ModelError('Invalid customer answerability judgment')
    blob=json.dumps(source,ensure_ascii=False)
    unknown=[]
    for row in value['factual_questions']:
        if set(row)!={'question','source_quote'} or not all(isinstance(v,str) for v in row.values()):
            raise ModelError('Invalid factual question evidence')
        if not row['source_quote'].strip() or row['source_quote'] not in blob:
            unknown.append(row['question'])
    return {'factual_questions':value['factual_questions'],'unknown_questions':unknown}
