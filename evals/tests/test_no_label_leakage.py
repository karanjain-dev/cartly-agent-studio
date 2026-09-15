"""Runtime isolation tests; scenario truth is available only to the test harness."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from cartly.tools import CartlySession, ROOT, HIDDEN_FIELDS, ACCESS_ERROR
from scripts.fixture_data import load_eval_data, TABLE_IDS

class LeakageTests(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory()
    def tearDown(self):self.tmp.cleanup()
    def session(self,guarded=False):return CartlySession(guarded=guarded,log_dir=self.tmp.name)
    def login(self,s,uid='U018'):
        user=next(u for u in s.state['users'] if u['user_id']==uid)
        result=s.verify_user(user_id=uid,email=user['email'])
        self.assertTrue(result['ok']);self.clean(result)
    def clean(self,value):
        if isinstance(value,dict):
            self.assertFalse(set(value)&HIDDEN_FIELDS,f'Leaked keys: {set(value)&HIDDEN_FIELDS}')
            for child in value.values():self.clean(child)
        elif isinstance(value,list):
            for child in value:self.clean(child)
    def digest(self,value):return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()

    def test_split_preserves_every_original_value_and_policy(self):
        manifest=json.loads((ROOT/'scenario_truth/migration_manifest.json').read_text())
        combined=load_eval_data(ROOT/'data')
        for table in TABLE_IDS:
            self.assertEqual(self.digest(combined[table]),manifest['original_combined_sha256'][table])
            world=json.loads((ROOT/'data'/(table+'.json')).read_text())
            self.clean(world)
            self.assertEqual(self.digest(world),manifest['world_sha256'][table])
        # The migration froze v0.5; v0.6 is an explicitly authorized policy update.
        original_policy=(ROOT/'prompts/agent_v1.md').read_text().split('\n\n',1)[1]
        self.assertEqual(hashlib.sha256(original_policy.encode()).hexdigest(),manifest['policy_sha256'])

    def test_every_read_tool_on_every_order_both_modes_without_truth_access(self):
        original_read=Path.read_text
        def read_world_only(path,*args,**kwargs):
            self.assertNotIn('scenario_truth',path.parts,'Runtime attempted to read hidden truth')
            return original_read(path,*args,**kwargs)
        with patch.object(Path,'read_text',read_world_only):
            for mode in [False,True]:
                s=self.session(mode)
                world=s.state
                self.clean(world)
                for order in world['orders']:
                    uid=order['user_id'];self.login(s,uid)
                    responses=[s.get_order(order_id=order['order_id']),s.list_orders(),
                               s.get_refund_history(order_id=order['order_id']),s.search_policy(query='E1'),
                               s.check_serviceability(pincode=order['delivery_address']['pincode'])]
                    for it in world['order_items']:
                        if it['order_id']==order['order_id']:
                            responses.append(s.check_evidence(order_id=order['order_id'],item_id=it['item_id']))
                    for response in responses:
                        self.assertTrue(response['ok'],response);self.clean(response)

    def test_reason_required_and_validated(self):
        for mode in [False,True]:
            s=self.session(mode);self.login(s)
            for name in ['create_return','issue_refund']:
                response=s.call(name,order_id='O0011',item_id='I0011',confirmed=True)
                self.assertFalse(response['ok']);self.assertIn("missing a required argument: 'reason'",response['error']['message'])
                response=s.call(name,order_id='O0011',item_id='I0011',reason='invented',confirmed=True)
                self.assertFalse(response['ok']);self.clean(response)

    def test_both_supplied_reasons_quote_database_amounts(self):
        for reason,expected in [('change_of_mind',1400),('damaged',1548)]:
            s=self.session();self.login(s)
            result=s.create_return(order_id='O0011',item_id='I0011',reason=reason,confirmed=True,amount=123456)
            self.assertTrue(result['ok'],result);self.assertEqual(result['result']['refund_amount'],expected)
            self.clean(result)

    def test_wrong_item_checks_only_guarded(self):
        for name in ['create_return','issue_refund']:
            for mode in [False,True]:
                s=self.session(mode);self.login(s)
                response=s.call(name,order_id='O0011',item_id='I0011',reason='wrong_item',confirmed=True)
                if mode:
                    self.assertFalse(response['ok']);self.assertEqual(response['error']['message'],'E11: clarification required; database does not establish a wrong item')
                else:self.assertTrue(response['ok'],response)
                self.clean(response)

    def test_e5_agent_refund_only_guarded(self):
        for reason,expected in [('change_of_mind',1400),('damaged',1548),('defective',1548)]:
            for mode in [False,True]:
                s=self.session(mode);self.login(s)
                response=s.issue_refund(order_id='O0011',item_id='I0011',reason=reason,confirmed=True,amount=1)
                if mode:self.assertFalse(response['ok']);self.assertIn('E5:',response['error']['message'])
                else:self.assertTrue(response['ok'],response);self.assertEqual(response['result']['refund']['amount'],expected)
                self.clean(response)

    def test_e5_small_item_return_only_guarded(self):
        # Selection is done in the evaluation harness, never in CartlySession.
        fixture=load_eval_data(ROOT/'data')
        o=next(o for o in fixture['orders'] if 'E5_damaged_under_500' in o['edge_case'])
        it=next(i for i in fixture['order_items'] if i['order_id']==o['order_id'])
        for mode in [False,True]:
            s=self.session(mode);self.login(s,o['user_id'])
            response=s.create_return(order_id=o['order_id'],item_id=it['item_id'],reason='damaged',confirmed=True)
            if mode:self.assertFalse(response['ok']);self.assertIn('E5:',response['error']['message'])
            else:self.assertTrue(response['ok'],response)

    def test_direct_unguarded_refund_after_scheduled_return_no_double_payment(self):
        s=self.session();self.login(s)
        returned=s.create_return(order_id='O0011',item_id='I0011',reason='change_of_mind',confirmed=True)
        paid=s.issue_refund(order_id='O0011',item_id='I0011',reason='damaged',confirmed=True)
        self.assertTrue(paid['ok'],paid)
        result=s.complete_pickup(returned['result']['return']['return_id'])
        self.assertFalse(result['ok']);self.assertIn('already refunded',result['error']['message'])
        self.clean(paid);self.clean(result)

    def test_write_outputs_never_echo_scenario_field_keys(self):
        s=self.session();self.login(s)
        result=s.escalate_to_human(user_request='Review this claim',facts_found={'nested':{'edge_case':'trap','price':1499}},rule_triggered='G2',what_user_was_told='Escalating')
        self.assertTrue(result['ok'],result);self.clean(result)
        # The supplied request is retained in the internal handoff/log, not echoed.
        self.assertEqual(s.logs[-1]['arguments']['user_request'],'Review this claim')

    def test_cross_user_error_exact(self):
        s=self.session();self.login(s)
        foreign=s.get_order(order_id='O0001');missing=s.get_order(order_id='NO_SUCH_ORDER')
        self.assertEqual(foreign,missing)
        self.assertEqual(foreign,{'ok':False,'error':{'message':ACCESS_ERROR}})

    def test_runtime_rejects_truth_paths_even_when_explicitly_supplied(self):
        with self.assertRaisesRegex(ValueError,'runtime cannot read scenario truth'):
            CartlySession(data_dir=ROOT/'scenario_truth',log_dir=self.tmp.name)
        with self.assertRaisesRegex(ValueError,'runtime cannot read scenario truth'):
            CartlySession(policy_path=ROOT/'scenario_truth/orders.json',log_dir=self.tmp.name)

if __name__=='__main__':unittest.main()
