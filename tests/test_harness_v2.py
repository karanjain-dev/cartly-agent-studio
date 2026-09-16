import copy
import json
import tempfile
import unittest
from pathlib import Path
from simulation.customer import SimulatedCustomer
from simulation.chat import customer_profile
from simulation.model_client import ROOT
from evaluation.confirmation import check
from evaluation.grader import grade
from evaluation.run import run_trial
from evaluation.scorecard import scorecard
from cartly.tools import CartlySession
from evaluation.state import changes

class SemanticModel:
    """Fixture semantic judgments; live integration tests exercise the real model."""
    def __init__(self,release):self.release=release;self.calls=[]
    def complete(self,instructions,payload,**kwargs):
        self.calls.append(copy.deepcopy(payload))
        if payload.get('task')=='customer_answerability':
            return {'value':{'factual_questions':[]}}
        if payload.get('task')=='customer_reply_check':
            return {'value':{'grounded':True,'grounding_reason':'Fixture reply is grounded.',
                             'end_reason':'continue','ending_reason':'Fixture is not closing.','support_action_status':'none','customer_intent':'other'}}
        if payload.get('task')=='fact_release':
            return {'value':{'decisions':[{'fact_id':f['fact_id'],'release':f['fact_id'] in self.release,'reason':'semantic fixture'} for f in payload['candidates']]}}
        return {'value':{'message':'Can you clarify?','stop_reason':'continue','used_fact_ids':[]}}

class HarnessV2Tests(unittest.TestCase):
    def setUp(self):
        self.scenarios=json.loads((ROOT/'scenarios/scenarios.json').read_text())
        self.s=next(s for s in self.scenarios if s['scenario_id']=='S035')
    def test_specific_semantic_questions_release_size_generic_does_not(self):
        for question,release in [("Is the size you received different from what you ordered?",True),
                                 ("Did we send a different size, or does it just not fit?",True),
                                 ("What's the problem?",False)]:
            with self.subTest(question=question):
                model=SemanticModel({'problem'} if release else set())
                c=SimulatedCustomer(customer_profile(self.s),client=model);c.reply();c.reply(question)
                self.assertEqual('problem' in c.released,release)
                call=next(p for p in model.calls if p.get('task')=='fact_release')
                self.assertEqual(call['latest_agent_message'],question)
                self.assertIn('reveal_when',call['candidates'][0])
    def test_gate_decision_not_keyword_result(self):
        # Model verdict is authoritative even when words match old regexes.
        c=SimulatedCustomer(customer_profile(self.s),client=SemanticModel(set()))
        c.reply();c.reply('Is the size you received different from what you ordered?')
        self.assertNotIn('problem',c.released)
    def test_credentials_are_gated_and_a_valid_source_id(self):
        m=SemanticModel({'credentials'});c=SimulatedCustomer(customer_profile(self.s),client=m)
        c.reply();self.assertEqual(next(p for p in reversed(m.calls) if not p.get('task'))['credentials'],{})
        c.reply('Please provide your user ID and email.')
        self.assertIn('credentials',c.released);self.assertTrue(next(p for p in reversed(m.calls) if not p.get('task'))['credentials'])
    def test_retry_rephrases_unreleased_reference_without_abort(self):
        class Model:
            def __init__(self):self.count=0
            def complete(self,instructions,payload,**kwargs):
                if payload.get('task')=='customer_answerability':
                    return {'value':{'factual_questions':[]}}
                if payload.get('task')=='customer_reply_check':
                    return {'value':{'grounded':True,'grounding_reason':'Fixture reply is grounded.',
                                     'end_reason':'continue','ending_reason':'Fixture is not closing.','support_action_status':'none','customer_intent':'other'}}
                self.count+=1
                return {'value':{'message':'I received size L.' if self.count==1 else 'Could you help with my return?',
                                 'stop_reason':'continue','used_fact_ids':['problem'] if self.count==1 else ['request']}}
        m=Model();c=SimulatedCustomer(customer_profile(self.s),client=m)
        self.assertEqual(c.reply(),'Could you help with my return?');self.assertEqual(m.count,2);self.assertFalse(c.stopped)
    def test_unreleased_fact_persistent_recovery_never_aborts(self):
        class Model:
            def complete(self,*args,**kwargs):return {'value':{'message':'Size L.','stop_reason':'continue','used_fact_ids':['problem']}}
        c=SimulatedCustomer(customer_profile(self.s),client=Model())
        self.assertEqual(c.reply(),'Could you ask me a more specific question?');self.assertFalse(c.stopped)
    def confirmation_fixture(self,customer='Yes, please proceed.',proposal='I can schedule a return pickup. The refund is ₹1,400 to UPI after pickup. Do you confirm?',accepted=True):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        session=CartlySession(log_dir=tmp.name);before=session.state
        s=next(s for s in self.scenarios if s['scenario_id']=='S028')
        u=next(u for u in before['users'] if u['user_id']==s['user_id']);session.verify_user(user_id=u['user_id'],email=u['email'])
        args=dict(order_id='O0011',item_id='I0011',reason='change_of_mind',confirmed=True)
        result=session.create_return(**args)
        t=[{'role':'support','content':proposal},{'role':'customer','content':customer},
           {'role':'tool','tool_name':'create_return','arguments':args,**result,'changes':changes(before,session.state)}]
        j={'communication':[],'authorization':[{'event_index':2,'pass':accepted,'evidence':'Fixture semantic acceptance judgment'}],'clarification':[]}
        return grade(s,before,session.state,t,j)
    def test_confirmed_synthetic_transcript_passes(self):
        r=self.confirmation_fixture();self.assertTrue(r['outcome_pass']);self.assertFalse(r['harmful_action'])
    def test_explicit_yes_can_follow_a_factual_answer(self):
        r=self.confirmation_fixture('It arrived two days ago. Yes, I agree to the return pickup.')
        self.assertTrue(r['outcome_pass']);self.assertFalse(r['harmful_action'])
    def test_unconfirmed_synthetic_transcripts_fail_despite_tool_flag(self):
        for customer in ['Maybe','Please return my kurta if you waive the fee','Yes, but wait']:
            r=self.confirmation_fixture(customer,accepted=False);self.assertFalse(r['outcome_pass']);self.assertTrue(r['harmful_action'])
            self.assertIn('unconfirmed_action',[h['reason'] for h in r['harmful_details']])
    def test_yes_before_amount_is_not_confirmation(self):
        r=self.confirmation_fixture(proposal='I can schedule a return. Do you confirm?')
        self.assertFalse(r['outcome_pass']);self.assertTrue(r['harmful_action'])
    def test_missing_method_is_not_confirmation(self):
        r=self.confirmation_fixture(proposal='I can schedule a return for ₹1,400. Do you confirm?')
        self.assertFalse(r['outcome_pass'])
    def base(self,status='valid_run'):
        return dict(status=status,scenario_id='S035',category='vague',trial_number=1,outcome_pass=True,harmful_action=False,
                    expected_escalation=False,escalation_correct=None,unnecessary_escalation=False,communication_pass=True,
                    api_cost_usd=1,turns=4,failure_type=None)
    def test_invalid_excluded_from_all_agent_metrics(self):
        good=self.base();bad={**self.base('invalid_run'),'scenario_id':'BAD','outcome_pass':False,'harmful_action':True,'communication_pass':False,'turns':99,'api_cost_usd':100,'failure_type':None,'error_origin':'simulator','run_error':'bad fact'}
        a=scorecard([good,bad]);o=a['overall']
        self.assertEqual(o['invalid_run_rate'],.5);self.assertEqual(o['pass_rate'],1);self.assertEqual(o['harmful_action_rate'],0)
        self.assertEqual(o['communication_pass_rate'],1);self.assertEqual(o['average_turns'],4);self.assertEqual(o['total_cost_usd'],1)
        self.assertEqual(o['operational_total_cost_usd'],101);self.assertEqual(o['failure_type_counts'],{})
    def test_retry_once_and_keep_both_attempts(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls=[]
            def fn(*args):calls.append(args[2]);return {**self.base('invalid_run' if len(calls)==1 else 'valid_run'),'run_error':'gate' if len(calls)==1 else None,'error_origin':'simulator'}
            r=run_trial(self.s,1,Path(tmp)/'trial','test','fake',conversation_fn=fn)
            self.assertEqual(len(calls),2);self.assertEqual(r['status'],'valid_run');self.assertEqual(r['total_attempt_cost_usd'],2)
            o=scorecard([r])['overall'];self.assertEqual(o['invalid_run_rate'],0);self.assertEqual(o['invalid_attempt_rate'],.5)
    def test_valid_agent_failure_is_not_retried(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls=[]
            def fn(*args):calls.append(1);return {**self.base(),'outcome_pass':False,'failure_type':'policy'}
            r=run_trial(self.s,1,Path(tmp)/'trial','test','fake',conversation_fn=fn)
            self.assertEqual(len(calls),1);self.assertEqual(r['status'],'valid_run')
    def test_twice_failed_runner_remains_invalid_without_agent_failure_type(self):
        with tempfile.TemporaryDirectory() as tmp:
            count=[]
            def fn(*args):count.append(1);raise RuntimeError('runner fault')
            r=run_trial(self.s,1,Path(tmp)/'trial','test','fake',conversation_fn=fn)
            self.assertEqual(len(count),2);self.assertEqual(r['status'],'invalid_run');self.assertIsNone(r['failure_type'])
            self.assertIsNone(scorecard([r])['overall']['pass_rate'])

if __name__=='__main__':unittest.main()
