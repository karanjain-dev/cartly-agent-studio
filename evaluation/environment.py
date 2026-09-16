"""Versioned agent environment; no reads of the system clock."""
import json
import re
from simulation.model_client import ROOT

CHANGELOG='environment: added current date; no behavioral instructions changed.'

def reference_environment(config=None):
    config=config or json.loads((ROOT/'data/config.json').read_text())
    return {'current_date':config['today'],'timezone':config['timezone']}

def policy_version(policy):
    match=re.search(r'^# Cartly Customer Support Policy (v\d+\.\d+)$',policy,re.M)
    if not match:raise ValueError('Policy version missing from title')
    return match.group(1)

def build_agent_prompt(config,policy):
    return ('You are Cartly customer support. Follow the policy exactly.\n\n'
            +"Today's date is "+reference_environment(config)['current_date']+' (IST).\n\n'
            +policy.rstrip()+'\n\n'+CHANGELOG+'\n')
