import copy
import json
import re
import unittest
from unittest.mock import patch
from io import BytesIO
from collections import Counter
from pathlib import Path
from simulation.customer import SimulatedCustomer, STOP
from simulation.chat import customer_profile
from simulation.self_check import payload_for, canonical
from simulation.model_client import ROOT, ModelError
from simulation.model_client import ModelClient

class FakeModel:
    def __init__(self,answer=None):self.calls=[];self.answer=answer
    def complete(self,instructions,payload,**kwargs):
        self.calls.append({'instructions':instructions,'payload':copy.deepcopy(payload)})
        if payload.get('task')=='customer_answerability':
            return {'value':{'factual_questions':[]}}
        if payload.get('task')=='customer_reply_check':
            draft=payload['draft']
            status=draft['stop_reason']
            return {'value':{'grounded':True,'grounding_reason':'Fixture reply is grounded.',
                             'end_reason':'customer_ended' if draft['message']==STOP and status=='continue' else status,
                             'ending_reason':'Fixture ending judgment.','support_action_status':getattr(self,'action_status',{'refused':'final_refusal','handoff':'escalation_completed'}.get(status,'completed')),
                             'customer_intent':'close' if status!='continue' or draft['message']==STOP else 'other'}}
        if payload.get('task')=='fact_release':
            q=payload['latest_agent_message']
            release=set()
            if q=='Has the item been used?':release={'condition','secret'}
            if 'confirm' in q.lower() or 'do you agree' in q.lower():release.add('consent')
            return {'value':{'decisions':[{'fact_id':f['fact_id'],'release':f['fact_id'] in release,'reason':'mock semantic verdict'} for f in payload['candidates']]}}
        return {'value':self.answer or {'message':'Could you help me with my order?','stop_reason':'continue','used_fact_ids':[]},'response_id':'offline','model':'fake'}

class SimulationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scenarios=json.loads((ROOT/'scenarios/scenarios.json').read_text())
        cls.world={n:json.loads((ROOT/'data'/(n+'.json')).read_text()) for n in ['config','users','orders','order_items','refunds','returns','serviceable_pincodes']}
    def scenario(self,sid='S001'):return next(s for s in self.scenarios if s['scenario_id']==sid)

    def test_distribution_and_required_fields(self):
        self.assertEqual(len(self.scenarios),40)
        self.assertEqual(len({s['scenario_id'] for s in self.scenarios}),40)
        self.assertEqual(Counter(s['category'] for s in self.scenarios),{'routine':11,'policy_boundary':10,'rule_interactions':6,'adversarial':7,'vague':3,'uncovered':3})
        self.assertEqual(Counter(s['split'] for s in self.scenarios),{'dev':30,'heldout':10})
        for category in {s['category'] for s in self.scenarios}:self.assertTrue(any(s['category']==category and s['split']=='heldout' for s in self.scenarios))
        required={'scenario_id','category','rules_tested','user_id','credentials','persona','goal','opening_style','hidden_facts','behavior_rules','acceptable_end_states','must_communicate','forbidden_actions','split'}
        for s in self.scenarios:
            self.assertEqual(set(s),required)
            self.assertTrue(s['acceptable_end_states']);self.assertTrue(s['must_communicate']);self.assertTrue(s['forbidden_actions'])
            self.assertFalse(re.search(r'\b[A-H]\d+\b',s['goal']))
            for fact in s['hidden_facts']:self.assertTrue(fact['fact']);self.assertTrue(fact['reveal_when']);self.assertTrue(fact['trigger'])
            uid=s['user_id'];u=next(u for u in self.world['users'] if u['user_id']==uid)
            self.assertEqual(s['credentials']['email'],u['email'])

    def test_world_wording_clean(self):
        for p in (ROOT/'data').glob('*.json'):self.assertIsNone(re.search(r'synthetic|sample|test|evaluation',p.read_text(),re.I),p.name)

    def test_customer_profile_allowlist(self):
        profile=customer_profile(self.scenario())
        self.assertEqual(set(profile),{'persona','goal','opening_style','hidden_facts','behavior_rules','credentials'})
        fake=FakeModel();c=SimulatedCustomer(profile,client=fake);c.reply()
        payload=json.dumps(fake.calls[0]['payload'])
        for forbidden in ['acceptable_end_states','rules_tested','must_communicate','forbidden_actions','policy.md','heldout','scenario_id']:
            self.assertNotIn(forbidden,payload)
        with self.assertRaises(ValueError):SimulatedCustomer(self.scenario(),client=fake)

    def test_hidden_fact_gate(self):
        profile=customer_profile(self.scenario());profile['hidden_facts'].append({'fact_id':'secret','fact':'The item has a distinctive amber mark.','trigger':'condition','reveal_when':'agent asks about use'})
        fake=FakeModel();c=SimulatedCustomer(profile,client=fake);c.reply()
        self.assertNotIn('amber',json.dumps(next(c['payload'] for c in reversed(fake.calls) if not c['payload'].get('task'))))
        c.reply('Hello, how can I help?')
        self.assertNotIn('amber',json.dumps(next(c['payload'] for c in reversed(fake.calls) if not c['payload'].get('task'))))
        c.reply('Used items can be difficult to return.')
        self.assertNotIn('amber',json.dumps(next(c['payload'] for c in reversed(fake.calls) if not c['payload'].get('task'))))
        c.reply('Has the item been used?')
        self.assertIn('amber',json.dumps(next(c['payload'] for c in reversed(fake.calls) if not c['payload'].get('task'))))

    def test_unreleased_fact_reference_rejected(self):
        fake=FakeModel({'message':'It is unused.','stop_reason':'continue','used_fact_ids':['condition']})
        c=SimulatedCustomer(customer_profile(self.scenario()),client=fake)
        self.assertEqual(c.reply(),'Could you ask me a more specific question?')
        self.assertFalse(c.stopped)
        self.assertTrue(any(t.get('blocked_ids')==['condition'] for t in c.trace))

    def test_pressure_then_refusal_stop(self):
        profile=customer_profile(self.scenario('S028'))
        fake=FakeModel();c=SimulatedCustomer(profile,client=fake);c.reply();c.reply('The refund amount is ₹1,400, do you agree?')
        self.assertIsNotNone(next(c['payload'] for c in reversed(fake.calls) if not c['payload'].get('task'))['active_behavior'])
        c.reply('The amount remains ₹1,400.')
        self.assertIsNone(next(c['payload'] for c in reversed(fake.calls) if not c['payload'].get('task'))['active_behavior'])
        fake.answer={'message':STOP,'stop_reason':'refused','used_fact_ids':[]}
        self.assertEqual(c.reply('I cannot offer a higher amount.'),STOP)

    def test_stop_handoff_and_goal(self):
        for status in ['handoff','goal_met']:
            fake=FakeModel();c=SimulatedCustomer(customer_profile(self.scenario()),client=fake);c.reply()
            fake.answer={'message':STOP,'stop_reason':status,'used_fact_ids':[]}
            self.assertEqual(c.reply('Your return is arranged.' if status=='goal_met' else 'I am handing you to a human.'),STOP)
            count=len(fake.calls);self.assertEqual(c.reply('Anything else?'),STOP);self.assertEqual(len(fake.calls),count)

    def test_hard_twenty_turn_limit(self):
        fake=FakeModel();c=SimulatedCustomer(customer_profile(self.scenario()),client=fake)
        c.reply()
        for _ in range(19):self.assertNotEqual(c.reply('Please continue.'),STOP)
        self.assertEqual(c.reply('Please continue.'),STOP);self.assertEqual(c.turns,20);self.assertEqual(sum(not c['payload'].get('task') for c in fake.calls),20)

    def test_stop_marker_does_not_override_pending_proposal(self):
        fake=FakeModel();c=SimulatedCustomer(customer_profile(self.scenario()),client=fake);c.reply()
        fake.answer={'message':STOP,'stop_reason':'continue','used_fact_ids':[]}
        fake.action_status='offered_or_pending'
        self.assertNotEqual(c.reply('May I create the return?'),STOP)
        self.assertFalse(c.stopped)

    def test_character_break_rejected(self):
        fake=FakeModel({'message':'I am a simulated user.','stop_reason':'continue','used_fact_ids':[]})
        with self.assertRaises(ModelError):SimulatedCustomer(customer_profile(self.scenario()),client=fake).reply()

    def test_self_check_payload_blind_and_user_scoped(self):
        for s in self.scenarios:
            p=payload_for(s,self.world,'POLICY')
            self.assertEqual(set(p),{'policy','world_data_for_user','full_hidden_facts'})
            self.assertNotIn('acceptable_end_states',json.dumps(p));self.assertNotIn('rules_tested',json.dumps(p))
            self.assertTrue(all(o['user_id']==s['user_id'] for o in p['world_data_for_user']['orders']))
            self.assertTrue(all(r['user_id']==s['user_id'] for r in p['world_data_for_user']['refunds']))

    def test_comparison_does_not_hide_amount_disagreements(self):
        state=copy.deepcopy(self.scenario()['acceptable_end_states'][0]);other=copy.deepcopy(state);other['refund']['amount']+=1
        self.assertNotEqual(canonical(state),canonical(other))

    def test_inactive_behavior_text_is_withheld(self):
        profile=customer_profile(self.scenario())
        profile['behavior_rules']=[{'trigger':'condition','instruction':'Admit there is an amber stain.','max_times':1}]
        fake=FakeModel();c=SimulatedCustomer(profile,client=fake);c.reply()
        self.assertNotIn('amber',json.dumps(next(c['payload'] for c in reversed(fake.calls) if not c['payload'].get('task'))))

    def test_api_json_mode_explicit_in_input(self):
        reply={'id':'response_offline','model':'gpt-4.1-mini','status':'completed','output':[{'content':[{'type':'output_text','text':'{"message":"Hello"}'}]}]}
        captured=[]
        def open_request(request,**kwargs):
            captured.append(json.loads(request.data));return BytesIO(json.dumps(reply).encode())
        with patch('simulation.model_client.api_key',return_value='offline-placeholder'),patch('simulation.model_client.urlopen',side_effect=open_request):
            result=ModelClient().complete('Reply naturally.',{'goal':'Help with my order'})
        self.assertIn('JSON',captured[0]['input']);self.assertFalse(captured[0]['store']);self.assertEqual(result['value']['message'],'Hello')

if __name__=='__main__':unittest.main()
