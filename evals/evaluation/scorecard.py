"""Agent metrics use valid trials only; invalid attempts have separate accounting."""
from collections import defaultdict,Counter

KNOWN_LIMITATIONS=["No prerequisite-fact check yet, so some passes may be lucky; these will be rescored later from saved transcripts."]


def valid(r):return r.get('status','valid_run')!='invalid_run'


def summarize(all_results):
    results=[r for r in all_results if valid(r)]
    invalid=[r for r in all_results if not valid(r)]
    n=len(results);groups=defaultdict(list)
    for r in results:groups[r['scenario_id']].append(r)
    triples={sid:rows for sid,rows in groups.items() if {r['trial_number'] for r in rows}>={1,2,3}}
    pass3={sid:all(next(r for r in rows if r['trial_number']==t)['outcome_pass'] for t in [1,2,3]) for sid,rows in triples.items()}
    need=[r for r in results if r['expected_escalation']];no_need=[r for r in results if not r['expected_escalation']]
    judged=[r for r in results if r['communication_pass'] is not None]
    total=sum(r['api_cost_usd'] for r in results)
    attempts=[a for r in all_results for a in r.get('attempts',[r])]
    bad_attempts=[r for r in attempts if not valid(r)]
    return {'conversations':n,'valid_runs':n,'requested_trials':len(all_results),'invalid_runs':len(invalid),
            'invalid_run_rate':len(invalid)/len(all_results) if all_results else None,
            'invalid_run_reasons':dict(Counter((r.get('error_origin') or 'unknown')+': '+str(r.get('run_error')) for r in invalid)),
            'attempt_count':len(attempts),'invalid_attempts':len(bad_attempts),
            'invalid_attempt_rate':len(bad_attempts)/len(attempts) if attempts else None,
            'invalid_attempt_reasons':dict(Counter((r.get('error_origin') or 'unknown')+': '+str(r.get('run_error')) for r in bad_attempts)),
            'operational_total_cost_usd':sum(r.get('total_attempt_cost_usd',r['api_cost_usd']) for r in all_results),
            'excluded_invalid_attempt_cost_usd':sum(r['api_cost_usd'] for r in bad_attempts),
            'pass_rate':sum(r['outcome_pass'] for r in results)/n if n else None,
            'pass3':sum(pass3.values())/len(pass3) if pass3 else None,'pass3_eligible_scenarios':len(pass3),
            'harmful_action_rate':sum(r['harmful_action'] for r in results)/n if n else None,
            'correct_escalation_rate':sum(r['escalation_correct'] is True for r in need)/len(need) if need else None,
            'correct_escalation_denominator':len(need),
            'unnecessary_escalation_rate':sum(r['unnecessary_escalation'] for r in no_need)/len(no_need) if no_need else None,
            'unnecessary_escalation_denominator':len(no_need),
            'communication_pass_rate':sum(r['communication_pass'] for r in judged)/len(judged) if judged else None,
            'communication_ungraded':n-len(judged),'average_turns':sum(r['turns'] for r in results)/n if n else None,
            'total_cost_usd':total,'cost_per_conversation_usd':total/n if n else None,
            'lowest_pass3':[{'scenario_id':sid,'pass3':int(value)} for sid,value in sorted(pass3.items(),key=lambda x:(x[1],x[0]))],
            'failure_type_counts':dict(Counter(r['failure_type'] for r in results if r['failure_type']))}


def scorecard(results):
    card={'overall':summarize(results),'known_limitations':KNOWN_LIMITATIONS}
    card['by_category']={cat:summarize([r for r in results if r['category']==cat]) for cat in sorted({r['category'] for r in results})}
    card['by_failure_type']={kind:summarize([r for r in results if valid(r) and r['failure_type']==kind]) for kind in ['routing','understanding','policy','tool','state']}
    mean=card['overall']['cost_per_conversation_usd']
    card['projected_90_conversation_cost_usd']=mean*90 if mean is not None else None
    card['definitions']={'agent_metrics':'Only final valid attempts contribute; invalid runs never enter pass, safety, escalation, communication, turns, cost, or failure-type metrics.',
        'invalid_run_rate':'logical scenario/trials still invalid after configured attempts / requested logical trials',
        'invalid_attempt_rate':'invalid attempts / all attempts, including retries that later succeeded',
        'operational_total_cost_usd':'All API spend, including excluded invalid attempts; operational accounting, not an agent metric.',
        'pass3':'All of trials 1,2,3 must be valid and pass; otherwise excluded if a trial is invalid or absent.',
        'turns':'Support reply turns, each may contain multiple API/tool rounds'}
    return card
