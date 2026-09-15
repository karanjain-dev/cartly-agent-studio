"""Mutation checks: each requested validation group must reject a broken fixture."""
import copy
import json
import unittest
from pathlib import Path
from validate_data import validate, TABLE_IDS
from fixture_data import load_eval_data

ROOT=Path(__file__).resolve().parents[1]

class ValidatorChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.clean=load_eval_data(ROOT/'data')

    def setUp(self): self.data=copy.deepcopy(self.clean)

    def rejected(self,check,record_id):
        errors=validate(self.data)['violations']
        self.assertTrue(any(e['check']==check and e['record_id']==record_id for e in errors),errors)

    def test_clean(self): self.assertEqual(validate(self.data)['violation_count'],0)

    def test_1_references(self):
        o=self.data['orders'][0];o['user_id']='MISSING';self.rejected(1,o['order_id'])
        i=self.data['order_items'][0];i['order_id']='MISSING';self.rejected(1,i['item_id'])
        r=self.data['refunds'][0];r['user_id']='U040';self.rejected(1,r['refund_id'])
        r['item_id']=self.data['order_items'][0]['item_id'];self.rejected(1,r['refund_id'])

    def test_2_future_dates(self):
        for table,field in [('orders','placed_date'),('orders','actual_delivery_date'),('refunds','date'),('returns','created_at'),('returns','completed_at')]:
            self.data=copy.deepcopy(self.clean)
            row=self.data[table][0]
            row[field]='2026-09-16T12:00:00+05:30' if field.endswith('_at') else '2026-09-16'
            self.rejected(2,row[TABLE_IDS[table]])

    def test_future_promises_allowed(self):
        o=next(o for o in self.data['orders'] if o['status']=='Packed' and not any(t.startswith('F1_') for t in o['edge_case']))
        o['promised_delivery_date']='2026-09-18'
        self.assertEqual(validate(self.data)['violation_count'],0)

    def test_promise_before_placement(self):
        o=self.data['orders'][0];o['promised_delivery_date']='2000-01-01';self.rejected(2,o['order_id'])

    def test_active_past_promise_requires_f1(self):
        for status in ['Placed','Packed','Shipped','Out for delivery']:
            self.data=copy.deepcopy(self.clean)
            o=next(o for o in self.data['orders'] if o['status']==status and not any(t.startswith('F1_') for t in o['edge_case']))
            o['promised_delivery_date']='2026-09-14';self.rejected(2,o['order_id'])

    def test_active_promise_today_allowed(self):
        o=next(o for o in self.data['orders'] if o['status']=='Packed' and not any(t.startswith('F1_') for t in o['edge_case']))
        o['promised_delivery_date']=self.data['config']['today']
        self.assertEqual(validate(self.data)['violation_count'],0)

    def test_f1_boundaries_delivered_and_undelivered(self):
        for tag in ['F1_exactly_5_days_late','F1_over_5_days_late','F1_undelivered_exactly_5_days_late','F1_undelivered_over_5_days_late']:
            self.data=copy.deepcopy(self.clean)
            o=next(o for o in self.data['orders'] if tag in o['edge_case'])
            # Promise on the relevant reference date makes lateness zero.
            o['promised_delivery_date']=o['actual_delivery_date'] or self.data['config']['today']
            self.rejected(8,o['order_id'])

    def test_3_refund_timing(self):
        r=self.data['refunds'][0];r['date']='2000-01-01';self.rejected(3,r['refund_id'])

    def test_4_delivery_status(self):
        o=self.data['orders'][0];o['actual_delivery_date']=None;self.rejected(4,o['order_id'])
        o['actual_delivery_date']='2026-09-08';o['status']='Packed';self.rejected(4,o['order_id'])

    def test_5_missing_cancellation_and_duplicate_refund(self):
        r=next(r for r in self.data['refunds'] if r['reason']=='cancellation')
        self.data['refunds'].remove(r);self.rejected(5,r['order_id'])
        r=copy.deepcopy(self.data['refunds'][0]);r['refund_id']='R_DUPLICATE'
        self.data['refunds'].append(r);self.rejected(5,r['refund_id'])

    def test_6_shipping_twice(self):
        r=copy.deepcopy(self.data['refunds'][0]);r['refund_id']='R_DOUBLE_SHIPPING'
        self.data['refunds'].append(r);self.rejected(6,r['refund_id'])

    def test_7_refund_math(self):
        r=self.data['refunds'][0];r['amount']+=1;self.rejected(7,r['refund_id'])

    def test_8_false_edge_tag(self):
        o=self.data['orders'][0];o['edge_case'].append('E1_electronics_day_10');self.rejected(8,o['order_id'])

    def test_8_unknown_edge_tag(self):
        o=self.data['orders'][0];o['edge_case'].append('E999_unknown');self.rejected(8,o['order_id'])

    def test_9_duplicates(self):
        for field in ['user_id','email','phone']:
            self.data=copy.deepcopy(self.clean)
            self.data['users'][1][field]=self.data['users'][0][field]
            self.rejected(9,self.data['users'][1]['user_id'])
        self.data=copy.deepcopy(self.clean)
        self.data['orders'][1]['order_id']=self.data['orders'][0]['order_id']
        self.rejected(9,self.data['orders'][0]['order_id'])

if __name__=='__main__':unittest.main()
