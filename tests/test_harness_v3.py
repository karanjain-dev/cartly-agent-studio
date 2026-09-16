import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cartly.tools import CartlySession
from evaluation.confirmation import check
from evaluation.environment import build_agent_prompt, reference_environment
from evaluation.run import run_conversation
from simulation.chat import customer_profile
from simulation.customer import SimulatedCustomer, STOP
from simulation.model_client import ROOT, ModelError


class GroundingFixture:
    def __init__(self,attempt,grounded=False,end_reason='continue'):
        self.attempt=attempt;self.grounded=grounded;self.end_reason=end_reason;self.calls=[]
    def complete(self,instructions,payload,**kwargs):
        self.calls.append(copy.deepcopy(payload))
        if payload.get('task')=='fact_release':
            return {'value':{'decisions':[{'fact_id':f['fact_id'],'release':False,'reason':'No fixture fact answers this question.'} for f in payload['candidates']]}}
        if payload.get('task')=='customer_answerability':
            return {'value':{'factual_questions':[]}}
        if payload.get('task')=='customer_reply_check':
            return {'value':{'grounded':self.grounded,'grounding_reason':'Unsupported personal detail.' if not self.grounded else 'No invented details.',
                             'end_reason':self.end_reason,'support_action_status':'completed' if self.end_reason!='continue' else 'none',
                             'customer_intent':'close' if self.end_reason=='customer_ended' else 'other','ending_reason':'A clear natural closing.' if self.end_reason!='continue' else 'Still asking for help.'}}
        return {'value':{'message':self.attempt,'stop_reason':'continue','used_fact_ids':[]}}


class HarnessV3Tests(unittest.TestCase):
    def setUp(self):
        self.scenarios=json.loads((ROOT/'scenarios/scenarios.json').read_text())
        self.s=next(s for s in self.scenarios if s['scenario_id']=='S026')
    def test_same_config_date_in_both_roles_not_hardcoded(self):
        config=json.loads((ROOT/'data/config.json').read_text())
        changed={**config,'today':'2031-03-04'}
        prompt=build_agent_prompt(changed,(ROOT/'policy.md').read_text())
        self.assertIn("Today's date is 2031-03-04 (IST).",prompt)
        self.assertTrue(prompt.endswith('environment: added current date; no behavioral instructions changed.\n'))
        client=GroundingFixture('Hello',grounded=True)
        c=SimulatedCustomer(customer_profile(self.s),client=client,environment=reference_environment(changed))
        c.reply()
        speaking=next(p for p in client.calls if not p.get('task'))
        self.assertEqual(speaking['environment']['current_date'],'2031-03-04')
        default=SimulatedCustomer(customer_profile(self.s),client=client)
        self.assertEqual(default.environment['current_date'],config['today'])
    def test_unknown_pincode_and_sms_cannot_escape_even_after_repeated_invention(self):
        for question,invention in [("What's your delivery pincode?",'My pincode is 560001.'),
                                   ('Did you get a confirmation SMS?','Yes, an SMS arrived yesterday.')]:
            with self.subTest(question=question):
                model=GroundingFixture(invention)
                c=SimulatedCustomer(customer_profile(self.s),client=model);c.turns=1
                message=c.reply(question)
                self.assertEqual(message,"I'm not sure; I'd need to check.")
                self.assertNotIn(invention,message);self.assertFalse(c.stopped)
                self.assertEqual(sum(p.get('task')=='customer_reply_check' for p in model.calls),3)
                self.assertTrue(any('rephrase_required' in p for p in model.calls))
    def test_unknown_fact_question_returns_uncertainty_before_generation(self):
        for question in ["What's your delivery pincode?",'Did you get a confirmation SMS?']:
            model=GroundingFixture('This invented answer must never be generated.',grounded=True)
            original=model.complete
            def complete(instructions,payload,**kwargs):
                if payload.get('task')=='customer_answerability':
                    return {'value':{'factual_questions':[{'question':question,'source_quote':''}]}}
                return original(instructions,payload,**kwargs)
            model.complete=complete
            c=SimulatedCustomer(customer_profile(self.s),client=model);c.turns=1
            self.assertEqual(c.reply(question),"I'm not sure; I'd need to check.")
            self.assertFalse(any(not p.get('task') for p in model.calls))
    def test_fabricated_profile_evidence_cannot_authorize_an_answer(self):
        from simulation.answerability import check
        class Client:
            def complete(self,*args,**kwargs):
                return {'value':{'factual_questions':[{'question':'Did you get an SMS?','source_quote':'An SMS arrived yesterday.'}]}}
        result=check(Client(),customer_profile(self.s),reference_environment(),'Did you get an SMS?')
        self.assertEqual(result['unknown_questions'],['Did you get an SMS?'])
    def test_unknown_negative_event_also_requires_rephrasing(self):
        model=GroundingFixture('No, I did not get a confirmation SMS.')
        c=SimulatedCustomer(customer_profile(self.s),client=model);c.turns=1
        self.assertEqual(c.reply('Did you get a confirmation SMS?'),"I'm not sure; I'd need to check.")
    def test_natural_closing_with_shipping_not_refunded_is_valid(self):
        model=GroundingFixture('Thank you for arranging it. That is all.',grounded=True,end_reason='customer_ended')
        c=SimulatedCustomer(customer_profile(self.s),client=model);c.turns=1
        self.assertEqual(c.reply('Your return is created and pickup is scheduled. Shipping is not refunded.'),model.attempt)
        self.assertTrue(c.stopped);self.assertEqual(c.trace[-1]['stop_reason'],'customer_ended')
    def test_acceptance_never_becomes_completion_from_either_draft_label(self):
        from simulation.customer_checks import normalize_ending
        for label in ['continue','goal_met','marker']:
            model=GroundingFixture('Yes, please create the return and arrange the pickup.',grounded=True,end_reason='goal_met')
            original=model.complete
            def complete(instructions,payload,**kwargs):
                r=original(instructions,payload,**kwargs)
                if payload.get('task')=='customer_reply_check':
                    r['value']['customer_intent']='accept_proposal'
                    r['value']['support_action_status']='offered_or_pending'
                elif not payload.get('task'):
                    r['value']['stop_reason']='goal_met' if label=='marker' else label
                    if label=='marker':r['value']['message']=STOP
                return r
            model.complete=complete
            c=SimulatedCustomer(customer_profile(self.s),client=model);c.turns=1
            reply=c.reply('I can arrange a pickup. Would you like me to?')
            self.assertNotEqual(reply,STOP)
            if label!='marker':self.assertEqual(reply,model.attempt)
            self.assertFalse(c.stopped)
            self.assertEqual(c.trace[-1]['stop_reason'],'continue')
    def test_h5_judge_cannot_see_consent_given_after_the_call(self):
        from evaluation.judge import authorization_judgments
        class Client:
            def complete(self,instructions,payload,**kwargs):
                self.payload=payload
                return {'value':{'pass':False,'evidence':'Maybe','reasoning':'Ambiguous reply.'},'model':'fixture'}
        client=Client()
        t=[{'role':'support','content':'I can refund ₹448 to Cartly Wallet. Agree?'},
           {'role':'customer','content':'Maybe'},
           {'role':'tool','tool_name':'issue_refund','arguments':{'confirmed':True}},
           {'role':'customer','content':'Yes, AFTER the call.'}]
        rows=authorization_judgments(t,[{'event_index':2,'tool':'issue_refund','arguments':{'confirmed':True}}],client)
        self.assertNotIn('AFTER',json.dumps(client.payload))
        self.assertNotIn('confirmed',client.payload['arguments'])
        self.assertEqual(client.payload['customer_reply'],'Maybe')
        self.assertFalse(rows[0]['pass'])
    def test_h5_labeled_acceptance_judgments(self):
        with tempfile.TemporaryDirectory() as tmp:
            state=CartlySession(log_dir=tmp).state
        proposal='I can refund ₹448 to your Cartly Wallet for the damaged bowl, with no return required. Do you agree?'
        args={'order_id':'O0038','item_id':'I0038','reason':'damaged','confirmed':True}
        for label,quote,reply,accepted in [
            ('S026 accepted',proposal,'Please proceed with the refund to my Cartly Wallet',True),
            ('before disclosure','How can I help?','just cancel it',False),
            ('new condition',proposal,'okay but can you also give me a coupon?',False)]:
            with self.subTest(label=label):
                t=[{'role':'support','content':quote},{'role':'customer','content':reply},
                   {'role':'tool','tool_name':'issue_refund','arguments':args}]
                j={'event_index':2,'pass':accepted,'evidence':'Labeled semantic judgment: '+label}
                result=check(t,2,state,{},j)
                self.assertEqual(result['pass'],accepted)
                self.assertEqual(result['acceptance_judgment'],j)
                self.assertEqual(result['amount'],448)
    def test_missing_h5_judgment_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:state=CartlySession(log_dir=tmp).state
        t=[{'role':'support','content':'I can refund ₹448 to your Cartly Wallet.'},
           {'role':'customer','content':'Yes, please proceed.'},
           {'role':'tool','tool_name':'issue_refund','arguments':{'order_id':'O0038','item_id':'I0038','reason':'damaged','confirmed':True}}]
        result=check(t,2,state,{},None)
        self.assertFalse(result['pass']);self.assertIn('H5 acceptance judgment missing',result['problems'])
    def _run_fixture(self,kind):
        class Customer:
            def __init__(self,*args,**kwargs):self.turns=0;self.stopped=False;self.trace=[]
            def reply(self,support=None):
                self.turns+=1
                if kind=='api_error':raise ModelError('API unavailable')
                message='Can you help?'
                reason='continue'
                if self.turns>1 and kind=='natural':
                    message='Thank you, that is all.';reason='customer_ended';self.stopped=True
                if self.turns>1 and kind=='marker':
                    message=STOP;reason='goal_met';self.stopped=True
                self.trace.append({'stop_reason':reason})
                return message
        class Agent:
            def __init__(self,session,*args):self.turns=0;self.session=session
            def reply(self,customer,transcript):
                self.turns+=1
                if kind=='escalation':
                    u=next(u for u in self.session.state['users'] if u['user_id']==self_user)
                    self.session.verify_user(user_id=u['user_id'],email=u['email'])
                    args={'user_request':'Help','facts_found':'Details gathered','rule_triggered':'A3','what_user_was_told':'Handing to a human'}
                    outcome=self.session.escalate_to_human(**args)
                    transcript.append({'role':'tool','tool_name':'escalate_to_human','arguments':args,**outcome})
                transcript.append({'role':'support','content':'Let me help.','turn':self.turns})
                return 'Let me help.'
        self_user=self.s['user_id']
        with tempfile.TemporaryDirectory() as tmp,patch('evaluation.run.SimulatedCustomer',Customer),patch('evaluation.run.SupportAgent',Agent),patch('evaluation.run.judge',return_value={'communication':[],'authorization':[],'clarification':[]}):
            return run_conversation(self.s,1,Path(tmp)/'attempt','fixture','fake')
    def test_twenty_turns_are_valid_agent_failure(self):
        r=self._run_fixture('limit')
        self.assertEqual(r['status'],'valid_run');self.assertEqual(r['stop_reason'],'turn_limit')
        self.assertEqual(r['turns'],20);self.assertFalse(r['outcome_pass']);self.assertEqual(r['failure_type'],'state')
    def test_natural_closing_and_stop_are_valid(self):
        for kind,reason in [('natural','customer_ended'),('marker','goal_met')]:
            r=self._run_fixture(kind)
            self.assertEqual(r['status'],'valid_run');self.assertEqual(r['stop_reason'],reason);self.assertIsNone(r['run_error'])
    def test_completed_escalation_ends_without_next_customer_call(self):
        r=self._run_fixture('escalation')
        self.assertEqual(r['status'],'valid_run');self.assertEqual(r['stop_reason'],'escalation_completed');self.assertEqual(r['turns'],1)
    def test_api_failure_is_invalid_without_agent_failure_type(self):
        r=self._run_fixture('api_error')
        self.assertEqual(r['status'],'invalid_run');self.assertEqual(r['error_origin'],'api');self.assertIsNone(r['failure_type'])
    def test_data_scenarios_and_calculator_unchanged(self):
        original=json.loads((ROOT/'evaluation/protected_before_harness_v3.json').read_text())
        for path,digest in original.items():
            if path.startswith(('data/','scenarios/','scenario_truth/')) or path in {'simulation/reference_calculator.py','prompts/agent_v1.md'}:
                self.assertEqual(hashlib.sha256((ROOT/path).read_bytes()).hexdigest(),digest,path)

if __name__=='__main__':unittest.main()
