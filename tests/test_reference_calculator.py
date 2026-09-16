import copy
import json
import unittest
from datetime import datetime, timedelta
from simulation.reference_calculator import calculate, calculate_scenario
from simulation.reference_check import matches
from simulation.structured_check import ROOT, FIELDS

class ReferenceTests(unittest.TestCase):
    def setUp(self):
        self.w = {n:json.loads((ROOT/'data'/f'{n}.json').read_text()) for n in
                  ['config','users','orders','order_items','refunds','returns','serviceable_pincodes']}
        self.o = next(o for o in self.w['orders'] if o['order_id']=='O0011')
        self.i = next(i for i in self.w['order_items'] if i['order_id']=='O0011')
        self.f = dict(order_id='O0011', item_id=self.i['item_id'], intent='return', reason='change_of_mind', is_unused=True)
    def run_case(self): return calculate(self.w,self.o['user_id'],self.f)
    def test_hand_verified_change_of_mind(self):
        d=self.run_case();self.assertEqual((d['outcome_type'],d['refund_amount'],d['refund_method']),('return',1400,'UPI'))
    def test_hand_verified_damage(self):
        self.f['reason']='damaged';d=self.run_case();self.assertEqual(d['refund_amount'],1548);self.assertTrue(d['shipping_refunded'])
    def test_hand_verified_cumulative_6100(self):
        self.i['price']=3000;self.o['shipping_fee']=100;self.f['reason']='damaged';self.i['evidence_photo_uploaded']=True
        other={**self.i,'item_id':'FIRST'};self.w['order_items'].append(other)
        self.w['refunds'].append(dict(order_id='O0011',item_id='FIRST',user_id=self.o['user_id'],amount=3100,shipping_refunded=True,reason='damaged',date='2026-09-10',status='completed'))
        d=self.run_case();self.assertEqual((d['outcome_type'],d['escalation_rule']),('escalate','H2'))
    def test_packed_large_cancel_exempt_even_with_history(self):
        self.o['status']='Packed';self.i['price']=6000;self.f['intent']='cancel'
        for n in range(3):self.w['refunds'].append(dict(order_id='OTHER',item_id=str(n),user_id=self.o['user_id'],amount=100,shipping_refunded=False,reason='damaged',date='2026-09-10',status='completed'))
        d=self.run_case();self.assertEqual((d['outcome_type'],d['refund_amount']),('cancel',6049))
    def test_inclusive_window_and_h1(self):
        self.assertEqual(self.run_case()['outcome_type'],'return')
        self.o['actual_delivery_date']='2026-09-04'
        self.assertEqual(self.run_case()['outcome_type'],'decline_no_change')
        self.f['reason']='defective';self.assertEqual(self.run_case()['escalation_rule'],'H1')
    def test_e2_exact_48_hours(self):
        self.i['category']='innerwear';self.f['reason']='damaged'
        self.o.update(actual_delivery_date='2026-09-13',actual_delivery_at='2026-09-13T12:00:00+05:30')
        self.assertEqual(self.run_case()['outcome_type'],'return')
        self.f['claim_reported_at']='2026-09-15T12:00:01+05:30'
        self.assertEqual(self.run_case()['outcome_type'],'decline_no_change')
    def test_photo_threshold_and_immediate_threshold(self):
        self.f.update(reason='damaged',photo_unavailable=True);self.i['evidence_photo_uploaded']=False
        for value,outcome in [(499,'immediate_refund'),(500,'return'),(2000,'return'),(2001,'decline_no_change')]:
            self.i['price']=value;self.assertEqual(self.run_case()['outcome_type'],outcome)
    def test_shipping_once_and_cod(self):
        self.f['reason']='damaged';self.o['payment_method']='COD'
        self.w['refunds'].append(dict(order_id='O0011',item_id='OTHER',user_id=self.o['user_id'],amount=49,shipping_refunded=True,reason='damaged',date='2026-09-10',status='completed'))
        d=self.run_case();self.assertEqual(d['refund_amount'],1499);self.assertFalse(d['shipping_refunded']);self.assertEqual(d['refund_method'],'Cartly Wallet')
    def test_wrong_item_matches_is_preference(self):
        self.f['reason']='wrong_item';self.assertEqual(self.run_case()['refund_amount'],1400)
        self.i['delivered_size']='XL';self.assertEqual(self.run_case()['refund_amount'],1548)
    def test_late_exact_five_and_six_and_once(self):
        self.f['intent']='coupon';self.o.update(actual_delivery_date=None,status='Shipped',promised_delivery_date='2026-09-10')
        self.assertEqual(self.run_case()['outcome_type'],'decline_no_change')
        self.o['promised_delivery_date']='2026-09-09';self.assertEqual(self.run_case()['outcome_type'],'coupon')
        self.o['coupon_issued']=True;self.assertEqual(self.run_case()['outcome_type'],'decline_no_change')
    def test_address_state_and_serviceability(self):
        self.f.update(intent='address',address={'pincode':'560001'});self.o['status']='Placed'
        self.assertEqual(self.run_case()['outcome_type'],'address_update')
        self.f['address']['pincode']='171001';self.assertEqual(self.run_case()['outcome_type'],'decline_no_change')
        self.f['address']['pincode']='560001';self.o['status']='Packed';self.assertEqual(self.run_case()['outcome_type'],'decline_no_change')
    def test_history_excludes_cancellations(self):
        for n in range(3):self.w['refunds'].append(dict(order_id='OTHER',item_id=None,user_id=self.o['user_id'],amount=100,shipping_refunded=False,reason='cancellation',date='2026-09-10',status='completed'))
        self.assertEqual(self.run_case()['outcome_type'],'return')
        for r in self.w['refunds'][-3:]:r['reason']='damaged'
        self.assertEqual(self.run_case()['escalation_rule'],'E10')
    def test_uncovered_and_foreign(self):
        self.f['intent']='uncovered';self.assertEqual(self.run_case()['escalation_rule'],'A3')
        self.o['user_id']='OTHER';self.assertEqual(calculate(self.w,'OWNER',self.f)['outcome_type'],'decline_no_change')
    def test_all_decisions_eight_fields_without_labels(self):
        for s in json.loads((ROOT/'scenarios/scenarios.json').read_text()):
            d=calculate_scenario(self.w,s['user_id'],s['hidden_facts']);self.assertEqual(set(d),set(FIELDS))
    def test_decline_item_normalization_only(self):
        a={**self.run_case(),'outcome_type':'decline_no_change'};b={**a,'item_id':None}
        self.assertTrue(matches(a,b));b['reason']='damaged';self.assertFalse(matches(a,b))

if __name__=='__main__':unittest.main()
