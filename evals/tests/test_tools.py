import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from cartly.tools import CartlySession, TOOLS, ACCESS_ERROR, ROOT
from scripts.fixture_data import load_eval_data, TABLE_IDS

class ToolTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.s=CartlySession(log_dir=self.tmp.name)
        self.original=self.s.state
        self.truth=load_eval_data(ROOT/"data")
    def tearDown(self):self.tmp.cleanup()
    def session(self,guarded=False):return CartlySession(guarded=guarded,log_dir=self.tmp.name)
    def login(self,s,uid):
        u=next(u for u in self.annotated(s,'users') if u['user_id']==uid)
        self.ok(s.verify_user(user_id=uid,email=u['email']))
    def annotated(self,s,table):
        key=TABLE_IDS[table]
        labels={r[key]:r for r in self.truth[table]}
        return [{**labels.get(r[key],{}),**r} for r in s.state[table]]
    def fixture(self,s,tag):return next(o for o in self.annotated(s,'orders') if tag in o['edge_case'])
    def claim(self,s,o):
        its=[i for i in self.annotated(s,'order_items') if i['order_id']==o['order_id']]
        return next((i for i in its if i.get('claim_reason')),its[0])
    def ok(self,response):
        self.assertTrue(response['ok'],response)
        return response['result']
    def error(self,response,text):
        self.assertFalse(response['ok'],response)
        self.assertIn(text,response['error']['message'])

    def test_all_policy_tools_valid_cases_both_modes(self):
        for mode in [False,True]:
            with self.subTest(guarded=mode):
                s=self.session(mode)
                self.ok(s.search_policy(query='E1'))
                self.ok(s.check_serviceability(pincode='400001'))
                self.login(s,'U018')
                self.ok(s.get_order(order_id='O0011'))
                self.ok(s.list_orders())
                self.ok(s.get_refund_history(order_id='O0011'))
                self.ok(s.check_evidence(order_id='O0011',item_id='I0011'))
                self.ok(s.create_return(order_id='O0011',item_id='I0011',reason='change_of_mind',confirmed=True))
                o=self.fixture(s,'C1_D1_Placed');self.login(s,o['user_id'])
                self.ok(s.update_address(order_id=o['order_id'],address=o['delivery_address'],confirmed=True))
                self.ok(s.cancel_order(order_id=o['order_id'],confirmed=True))
                o=self.fixture(s,'E5_damaged_under_500');it=self.claim(s,o);self.login(s,o['user_id'])
                self.ok(s.issue_refund(order_id=o['order_id'],item_id=it['item_id'],reason=it.get('claim_reason') or 'damaged',confirmed=True))
                o=self.fixture(s,'F1_over_5_days_late');self.login(s,o['user_id'])
                self.ok(s.issue_coupon(order_id=o['order_id'],confirmed=True))
                self.ok(s.escalate_to_human(order_id=o['order_id'],user_request='Help with a late order',facts_found={'days_late':6},rule_triggered='G2',what_user_was_told='Escalating for review.'))
                self.assertTrue(set(TOOLS).issubset({e['tool_name'] for e in s.logs}))

    def test_unverified_all_private_tools(self):
        for name in set(TOOLS)-{'verify_user','search_policy','check_serviceability'}:
            with self.subTest(tool=name):self.error(self.s.call(name,confirmed=True),'verification required')
        self.assertEqual(len(self.s.logs),10)

    def test_similar_name_cross_user_errors_identical_to_missing(self):
        o=self.fixture(self.s,'A2_similar_name_other_owner')
        self.login(self.s,o['requesting_user_id'])
        it=self.claim(self.s,o)
        calls=[('get_order',{}),('get_refund_history',{}),('check_evidence',{'item_id':it['item_id']}),
               ('update_address',{'address':o['delivery_address'],'confirmed':True}),('cancel_order',{'confirmed':True}),
               ('create_return',{'item_id':it['item_id'],'reason':it.get('claim_reason') or 'damaged','confirmed':True}),('issue_refund',{'item_id':it['item_id'],'reason':it.get('claim_reason') or 'damaged','confirmed':True}),
               ('issue_coupon',{'confirmed':True}),('escalate_to_human',{})]
        for tool,kwargs in calls:
            with self.subTest(tool=tool):
                foreign=self.s.call(tool,order_id=o['order_id'],**kwargs)
                missing=self.s.call(tool,order_id='DOES_NOT_EXIST',**kwargs)
                self.assertEqual(foreign,missing)
                self.error(foreign,ACCESS_ERROR)
        result=self.ok(self.s.list_orders())
        self.assertTrue(all(r['user_id']==o['requesting_user_id'] for r in result['orders']))

    def test_cross_order_item_rejected(self):
        self.login(self.s,'U018')
        foreign=self.s.check_evidence(order_id='O0011',item_id='I0001')
        missing=self.s.check_evidence(order_id='O0011',item_id='MISSING')
        self.assertEqual(foreign,missing);self.error(foreign,ACCESS_ERROR)

    def test_confirmation_all_writes_both_modes(self):
        for mode in [False,True]:
            s=self.session(mode);self.login(s,'U018')
            for tool in ['update_address','cancel_order','create_return','issue_refund','issue_coupon']:
                for value in [None,False,1,'true']:
                    self.error(s.call(tool,order_id='O0011',confirmed=value),'confirmation required')

    def test_database_amounts_and_methods(self):
        self.login(self.s,'U018')
        r=self.ok(self.s.create_return(order_id='O0011',item_id='I0011',reason='change_of_mind',confirmed=True,amount=900000))
        self.assertEqual(r['refund_amount'],1400);self.assertEqual(r['refund_method'],'UPI')
        self.assertEqual(len(self.s.state['refunds']),len(self.original['refunds']))
        done=self.ok(self.s.complete_pickup(r['return']['return_id']))
        self.assertEqual(done['refund']['amount'],1400)
        self.assertFalse(done['refund']['shipping_refunded'])
        o=self.fixture(self.s,'E5_damaged_under_500');it=self.claim(self.s,o);self.login(self.s,o['user_id'])
        r=self.ok(self.s.issue_refund(order_id=o['order_id'],item_id=it['item_id'],reason=it.get('claim_reason') or 'damaged',confirmed=True,amount=1))['refund']
        self.assertEqual(r['amount'],it['price']+o['shipping_fee']);self.assertEqual(r['method'],'Cartly Wallet')
        o=self.fixture(self.s,'C1_D1_Placed');self.login(self.s,o['user_id'])
        expected=sum(i['price']*i['quantity'] for i in self.annotated(self.s,'order_items') if i['order_id']==o['order_id'])+o['shipping_fee']
        r=self.ok(self.s.cancel_order(order_id=o['order_id'],confirmed=True,amount=0))['refund']
        self.assertEqual(r['amount'],expected)
        o=self.fixture(self.s,'F1_over_5_days_late');self.login(self.s,o['user_id'])
        self.assertEqual(self.ok(self.s.issue_coupon(order_id=o['order_id'],confirmed=True,amount=999))['coupon']['amount'],100)

    def test_shipping_once_and_no_duplicate_item(self):
        o=self.fixture(self.s,'E12_shipping_already_refunded');it=self.claim(self.s,o);self.login(self.s,o['user_id'])
        r=self.ok(self.s.create_return(order_id=o['order_id'],item_id=it['item_id'],reason=it.get('claim_reason') or 'damaged',confirmed=True))
        self.assertEqual(r['refund_amount'],3000)
        result=self.ok(self.s.complete_pickup(r['return']['return_id']))
        self.assertEqual(result['refund']['amount'],3000);self.assertFalse(result['refund']['shipping_refunded'])
        rr=[r for r in self.s.state['refunds'] if r['order_id']==o['order_id']]
        self.assertEqual(sum(r['shipping_refunded'] for r in rr),1)
        self.error(self.s.create_return(order_id=o['order_id'],item_id=it['item_id'],reason=it.get('claim_reason') or 'damaged',confirmed=True),'already refunded')
        self.error(self.s.complete_pickup(result['return']['return_id']),'already completed')

    def test_immediate_refund_cannot_repeat(self):
        for mode in [False,True]:
            s=self.session(mode);o=self.fixture(s,'E5_damaged_under_500');it=self.claim(s,o);self.login(s,o['user_id'])
            kwargs={'order_id':o['order_id'],'item_id':it['item_id'],'reason':it.get('claim_reason') or 'damaged','confirmed':True}
            self.ok(s.issue_refund(**kwargs));self.error(s.issue_refund(**kwargs),'already refunded')

    def test_guarded_planted_claim_violations_unguarded_succeed(self):
        cases=[('E1_electronics_day_8','E1'),('E1_clothing_day_11','E1'),
               ('E2_innerwear_after_48h','E2'),('E2_perishables_after_48h','E2'),('E2_personalized_after_48h','E2'),
               ('E6_above_2000_no_photo','E6'),('E9_H2_prior_plus_claim_crosses_5000','E9/H2')]
        for tag,rule in cases:
            for mode in [False,True]:
                with self.subTest(tag=tag,guarded=mode):
                    s=self.session(mode);o=self.fixture(s,tag);it=self.claim(s,o);self.login(s,o['user_id'])
                    before=s.state
                    result=s.create_return(order_id=o['order_id'],item_id=it['item_id'],reason=it.get('claim_reason') or 'damaged',confirmed=True)
                    if mode:self.error(result,rule);self.assertEqual(before,s.state)
                    else:self.ok(result)

    def test_history_guarded_only(self):
        for mode in [False,True]:
            s=self.session(mode)
            u=next(u for u in self.annotated(s,'users') if 'E10_exactly_3' in u['edge_case'])
            o=next(o for o in self.annotated(s,'orders') if o['user_id']==u['user_id'] and any(i['order_id']==o['order_id'] and i['claim_reason']=='damaged' for i in self.annotated(s,'order_items')))
            it=self.claim(s,o);self.login(s,u['user_id'])
            response=s.issue_refund(order_id=o['order_id'],item_id=it['item_id'],reason=it.get('claim_reason') or 'damaged',confirmed=True)
            if mode:self.error(response,'E10')
            else:self.ok(response)

    def test_cancellation_history_does_not_count(self):
        s=self.session(True)
        u=next(u for u in self.annotated(s,'users') if 'E10_3_cancellations_only' in u['edge_case'])
        self.login(s,u['user_id']);self.assertEqual(self.ok(s.get_refund_history())['qualifying_count'],0)
        o=next(o for o in self.annotated(s,'orders') if o['user_id']==u['user_id'] and o['status']=='Delivered')
        it=self.claim(s,o);self.ok(s.issue_refund(order_id=o['order_id'],item_id=it['item_id'],reason=it.get('claim_reason') or 'damaged',confirmed=True))

    def test_guarded_coupon_eligibility_and_repeat(self):
        for tag in ['F1_exactly_5_days_late','F1_undelivered_exactly_5_days_late']:
            for mode in [False,True]:
                s=self.session(mode);o=self.fixture(s,tag);self.login(s,o['user_id'])
                result=s.issue_coupon(order_id=o['order_id'],confirmed=True)
                if mode:self.error(result,'F1')
                else:self.ok(result)
        for mode in [False,True]:
            s=self.session(mode);o=self.fixture(s,'F1_undelivered_over_5_days_late');self.login(s,o['user_id'])
            self.ok(s.issue_coupon(order_id=o['order_id'],confirmed=True))
            result=s.issue_coupon(order_id=o['order_id'],confirmed=True)
            if mode:self.error(result,'F1')
            else:self.ok(result)

    def test_cancellation_limit_exempt(self):
        s=self.session(True);o=self.fixture(s,'E9_cancellation_exempt_over_5000');self.login(s,o['user_id'])
        self.assertGreater(self.ok(s.cancel_order(order_id=o['order_id'],confirmed=True))['refund']['amount'],5000)

    def test_always_state_and_address_rules(self):
        for mode in [False,True]:
            s=self.session(mode)
            o=self.fixture(s,'C2_Shipped');self.login(s,o['user_id'])
            self.error(s.cancel_order(order_id=o['order_id'],confirmed=True),'C1/C2')
            self.error(s.update_address(order_id=o['order_id'],address=o['delivery_address'],confirmed=True),'D1')
            it=self.claim(s,o)
            self.error(s.create_return(order_id=o['order_id'],item_id=it['item_id'],reason='damaged',confirmed=True),'Delivered')
            o=self.fixture(s,'D2_unserviceable_address');self.login(s,o['user_id'])
            self.error(s.update_address(order_id=o['order_id'],address=o['requested_delivery_address'],confirmed=True),'D2')

    def test_escalation_requires_all_fields(self):
        self.login(self.s,'U018')
        complete={'user_request':'Return item','facts_found':{'order_id':'O0011'},'rule_triggered':'G2','what_user_was_told':'A human will review.'}
        for field in complete:
            for empty in [None,'',' ',[],{}, {'empty':' '}]:
                kwargs={**complete,field:empty};self.error(self.s.escalate_to_human(**kwargs),'G3')
        self.error(self.s.escalate_to_human(),'G3')

    def test_reset_restores_state_and_new_conversation(self):
        o=self.fixture(self.s,'E5_damaged_under_500');it=self.claim(self.s,o);self.login(self.s,o['user_id'])
        self.ok(self.s.issue_refund(order_id=o['order_id'],item_id=it['item_id'],reason=it.get('claim_reason') or 'damaged',confirmed=True))
        o=self.fixture(self.s,'C1_Packed');self.login(self.s,o['user_id']);self.ok(self.s.cancel_order(order_id=o['order_id'],confirmed=True))
        old=self.s.log_path;old_text=old.read_text();self.assertNotEqual(self.original,self.s.state)
        self.s.reset();self.assertEqual(self.original,self.s.state);self.assertIsNone(self.s.verified_user_id)
        self.assertEqual(self.s.logs,[]);self.assertNotEqual(old,self.s.log_path);self.assertEqual(old.read_text(),old_text)
        self.assertEqual(self.session().state,self.original)

    def test_read_results_do_not_mutate_session(self):
        self.login(self.s,'U018');result=self.ok(self.s.get_order(order_id='O0011'))
        result['items'][0]['price']=1
        self.assertEqual(self.ok(self.s.get_order(order_id='O0011'))['items'][0]['price'],1499)

    def test_data_files_unchanged(self):
        before={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/'data').glob('*.json')}
        self.test_reset_restores_state_and_new_conversation()
        after={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/'data').glob('*.json')}
        self.assertEqual(before,after)

    def test_logs_every_success_and_error_fixed_timestamp(self):
        self.s.get_order(order_id='O0011');self.login(self.s,'U018')
        self.s.get_order(order_id='O0011');self.s.create_return(order_id='O0011',item_id='I0011',reason='change_of_mind',confirmed=True)
        saved=[json.loads(line) for line in self.s.log_path.read_text().splitlines()]
        self.assertEqual(saved,self.s.logs);self.assertEqual(len(saved),4)
        for e in saved:
            self.assertEqual(e['timestamp'],'2026-09-15T12:00:00+05:30');self.assertEqual(e['mode'],'unguarded')
            self.assertIn('arguments',e);self.assertTrue('result' in e or 'error' in e)

    def test_failed_verification_clears_identity(self):
        self.login(self.s,'U018');self.error(self.s.verify_user(user_id='U001',email='wrong@example.com'),'verification failed')
        self.error(self.s.get_order(order_id='O0011'),'verification required')

    def test_malformed_arguments_are_logged(self):
        self.error(self.s.verify_user(user_id='U001',email=123),'invalid arguments')
        self.assertFalse(self.s.logs[-1]['ok'])
        self.assertEqual(self.s.logs[-1]['arguments']['email'],123)

    def test_pickup_rechecks_guard_without_partial_mutation(self):
        o=self.fixture(self.s,'E12_shipping_already_refunded');it=self.claim(self.s,o);self.login(self.s,o['user_id'])
        r=self.ok(self.s.create_return(order_id=o['order_id'],item_id=it['item_id'],reason=it.get('claim_reason') or 'damaged',confirmed=True))
        self.s.guarded=True
        before=self.s.state
        self.error(self.s.complete_pickup(r['return']['return_id']),'E9/H2')
        self.assertEqual(self.s.state,before)

if __name__=='__main__':unittest.main()
