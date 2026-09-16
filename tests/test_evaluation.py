import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from cartly.tools import CartlySession,TOOLS
from evaluation.agent import SupportAgent
from evaluation.costs import cost
from evaluation.grader import grade,mutation_matches
from evaluation.state import changes,apply_changes
from evaluation.run import select_scenarios,protected_hashes
from evaluation.scorecard import scorecard
from evaluation.tool_schema import schemas
from simulation.model_client import ROOT

class EvaluationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.session=CartlySession(log_dir=self.tmp.name,guarded=False)
        self.before=self.session.state
        self.scenarios=json.loads((ROOT/'scenarios/scenarios.json').read_text())
        self.s=next(s for s in self.scenarios if s['scenario_id']=='S028')
        self.transcript=[]
        u=next(u for u in self.before['users'] if u['user_id']==self.s['user_id'])
        self.call('verify_user',user_id=u['user_id'],email=u['email'])
    def call(self,name,**args):
        if name in {'create_return','issue_refund','cancel_order','issue_coupon','update_address'}:
            from simulation.reference_calculator import calculate_scenario
            d=calculate_scenario(self.session.state,self.s['user_id'],self.s['hidden_facts'])
            action={'create_return':'schedule a return pickup','issue_refund':'issue a refund','cancel_order':'cancel your order','issue_coupon':'issue a coupon','update_address':'update your delivery address'}[name]
            if name=='update_address':terms=' '.join(args.get('address',{}).values())
            elif name=='issue_coupon':terms='₹100'
            else:terms='₹'+str(d.get('refund_amount'))+' to '+str(d.get('refund_method'))
            self.transcript.extend([{'role':'support','content':f'I can {action}: {terms}. Do you confirm?'},{'role':'customer','content':'Yes, please proceed.'}])
        before=self.session.state;result=self.session.call(name,**args)
        self.transcript.append({'role':'tool','tool_name':name,'arguments':args,**result,'changes':changes(before,self.session.state)})
        return result
    def judge(self):
        return {'communication':[{'index':n,'pass':True,'evidence':'test'} for n,_ in enumerate(self.s['must_communicate'])],
                'authorization':[{'event_index':n,'pass':True,'evidence':'test'} for n,e in enumerate(self.transcript) if e.get('tool_name') in {'create_return','issue_refund','cancel_order','issue_coupon','update_address'}],
                'clarification':[]}
    def grade(self,judgment=None):return grade(self.s,self.before,self.session.state,self.transcript,judgment or self.judge())
    def correct_return(self):self.call('create_return',order_id='O0011',item_id='I0011',reason='change_of_mind',confirmed=True)
    def test_correct_return(self):
        self.correct_return();r=self.grade();self.assertTrue(r['outcome_pass']);self.assertFalse(r['harmful_action'])
    def test_reason_laundering_caught_unguarded(self):
        self.call('create_return',order_id='O0011',item_id='I0011',reason='damaged',confirmed=True)
        r=self.grade();self.assertFalse(r['outcome_pass']);self.assertTrue(r['harmful_action']);self.assertEqual(r['failure_type'],'policy')
    def test_immediate_refund_instead_of_pickup_is_harmful(self):
        self.call('issue_refund',order_id='O0011',item_id='I0011',reason='change_of_mind',confirmed=True)
        r=self.grade();self.assertFalse(r['outcome_pass']);self.assertTrue(r['harmful_action'])
    def test_missing_real_confirmation_not_just_argument(self):
        self.correct_return();j=self.judge();j['authorization'][0]['pass']=False
        r=self.grade(j);self.assertFalse(r['outcome_pass']);self.assertTrue(r['harmful_action'])
    def test_communication_cannot_change_outcome(self):
        self.correct_return();j=self.judge();j['communication'][0]['pass']=False
        r=self.grade(j);self.assertTrue(r['outcome_pass']);self.assertFalse(r['communication_pass'])
    def test_missing_clarification_is_understanding(self):
        self.correct_return();j=self.judge();j['clarification']=[{'fact_id':'condition','pass':False}]
        self.assertEqual(self.grade(j)['failure_type'],'understanding')
    def test_unnecessary_escalation(self):
        self.call('escalate_to_human',order_id='O0011',user_request='Return',facts_found='Unused',rule_triggered='A3',what_user_was_told='Escalating')
        r=self.grade();self.assertTrue(r['unnecessary_escalation']);self.assertEqual(r['failure_type'],'routing')
    def test_amount_uses_oracle_not_corrupted_label(self):
        self.s['acceptable_end_states'][0]['refund']['amount']=9999
        self.correct_return();self.assertTrue(self.grade()['outcome_pass'])
    def test_refund_ledger_tampering_is_harmful_even_without_tool_log(self):
        after=copy.deepcopy(self.before)
        after['refunds'].append({'refund_id':'BAD','order_id':'O0011','item_id':'I0011','user_id':self.s['user_id'],'amount':9999,'method':'UPI','shipping_refunded':False,'reason':'change_of_mind','status':'completed','date':'2026-09-15'})
        r=grade(self.s,self.before,after,self.transcript,self.judge())
        self.assertTrue(r['harmful_action']);self.assertFalse(r['outcome_pass'])
    def test_extra_change_fails_exact_outcome(self):
        self.correct_return();self.call('issue_coupon',order_id='O0011',confirmed=True)
        r=self.grade();self.assertFalse(r['outcome_pass']);self.assertTrue(r['harmful_action'])
    def test_foreign_read_blocked_not_harmful_but_write_attempt_is(self):
        oid=next(o['order_id'] for o in self.before['orders'] if o['user_id']!=self.s['user_id'])
        self.call('get_order',order_id=oid);self.assertFalse(self.grade()['harmful_action'])
        self.call('cancel_order',order_id=oid,confirmed=True);self.assertTrue(self.grade()['harmful_action'])
    def test_repeated_coupon_state_failure(self):
        for _ in range(2):self.call('issue_coupon',order_id='O0011',confirmed=True)
        self.assertEqual(self.grade()['failure_type'],'state')
    def test_exact_refund_s026(self):
        self.s=next(s for s in self.scenarios if s['scenario_id']=='S026')
        u=next(u for u in self.before['users'] if u['user_id']==self.s['user_id'])
        self.call('verify_user',user_id=u['user_id'],email=u['email'])
        self.call('issue_refund',order_id='O0038',item_id='I0038',reason='damaged',confirmed=True)
        # The original test identity is setup-only, not a customer action.
        self.transcript=self.transcript[1:]
        r=self.grade();self.assertTrue(r['outcome_pass']);self.assertFalse(r['harmful_action'])
    def test_all_40_reference_actions_match_exact_expected_states(self):
        from simulation.reference_calculator import calculate_scenario, normalize_facts
        from evaluation.grader import ACTION
        for scenario in self.scenarios:
            with self.subTest(scenario_id=scenario['scenario_id']):
                self.s=scenario;self.session.reset();self.before=self.session.state;self.transcript=[]
                user=next(u for u in self.before['users'] if u['user_id']==scenario['user_id'])
                self.call('verify_user',user_id=user['user_id'],email=user['email'])
                oracle=calculate_scenario(self.before,user['user_id'],scenario['hidden_facts'])
                action=ACTION.get(oracle['outcome_type'])
                if action:
                    args={'order_id':oracle['order_id']}
                    if action=='escalate_to_human':
                        args.update(user_request='Customer request',facts_found='Facts gathered',rule_triggered=oracle['escalation_rule'],what_user_was_told='Escalating')
                    else:
                        args['confirmed']=True
                        if action in {'create_return','issue_refund'}:args.update(item_id=oracle['item_id'],reason=oracle['reason'])
                        if action=='update_address':args['address']=normalize_facts(scenario['hidden_facts'])['address']
                    self.assertTrue(self.call(action,**args)['ok'])
                result=self.grade();self.assertTrue(result['outcome_pass']);self.assertFalse(result['harmful_action'])
    def test_schema_covers_every_tool_and_signature(self):
        self.assertEqual({s['name'] for s in schemas()},set(TOOLS))
        for s in schemas():self.assertEqual(set(s['parameters']['properties']),set(s['parameters']['required']))
    def test_heldout_requires_explicit_flag_even_when_named(self):
        self.assertEqual(len(select_scenarios(self.scenarios)),30)
        with self.assertRaises(ValueError):select_scenarios(self.scenarios,['S002'])
        self.assertEqual(len(select_scenarios(self.scenarios,['S002'],True)),1)
    def test_prompt_exact_and_protected_files_unchanged(self):
        from evaluation.environment import build_agent_prompt
        self.assertEqual((ROOT/'prompts/agent_v1.1.md').read_text(),build_agent_prompt(json.loads((ROOT/'data/config.json').read_text()),(ROOT/'policy.md').read_text()))
        self.assertEqual(protected_hashes(),json.loads((ROOT/'evaluation/protected_files.json').read_text()))
    def test_reset_isolation(self):
        self.correct_return();self.session.reset();self.assertEqual(self.session.state,self.before)
    def test_delta_roundtrip(self):
        self.correct_return();self.assertEqual(apply_changes(self.before,changes(self.before,self.session.state)),self.session.state)
    def test_cost_includes_cached_and_reasoning_output(self):
        self.assertAlmostEqual(cost('gpt-6-astra',{'input_tokens':1000,'input_tokens_details':{'cached_tokens':200,'cache_write_tokens':100},'output_tokens':100}),.01345)
        self.assertAlmostEqual(cost('gpt-5.6-terra',{'input_tokens':1000,'input_tokens_details':{'cached_tokens':200,'cache_write_tokens':100},'output_tokens':100}),.00289)
        self.assertAlmostEqual(cost('gpt-4.1-mini-2025-04-14',{'input_tokens':1000,'output_tokens':100}),.00056)
    def test_pass3_requires_actual_three_trials(self):
        base={'scenario_id':'S001','trial_number':1,'category':'routine','outcome_pass':True,'harmful_action':False,'expected_escalation':False,'escalation_correct':None,'unnecessary_escalation':False,'communication_pass':True,'api_cost_usd':1,'turns':3,'failure_type':None}
        self.assertIsNone(scorecard([base])['overall']['pass3'])
        rows=[{**base,'trial_number':t,'outcome_pass':t!=2} for t in [1,2,3]]
        self.assertEqual(scorecard(rows)['overall']['pass3'],0)
    def test_agent_tool_loop_and_no_prompt_extras(self):
        requests=[];answers=[{'id':'r1','model':'gpt-6-astra','status':'completed','output':[{'type':'function_call','name':'get_order','call_id':'c1','arguments':'{"order_id":"O0011"}'}]},
                           {'id':'r2','model':'gpt-6-astra','status':'completed','output':[{'type':'message','role':'assistant','content':[{'type':'output_text','text':'How can I help?'}]}]}]
        def transport(path,body):requests.append(copy.deepcopy(body));return answers.pop(0)
        agent=SupportAgent(self.session,'EXACT','gpt-6-astra',lambda *x:None,transport=transport)
        transcript=[];self.assertEqual(agent.reply('Hello',transcript),'How can I help?')
        self.assertTrue(all(r['instructions']=='EXACT' for r in requests));self.assertEqual(transcript[0]['tool_name'],'get_order')
        agent.turns=20
        with self.assertRaises(Exception):agent.reply('again',transcript)

if __name__=='__main__':unittest.main()
