import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from evaluation.stress import OUT, SUITE, Budget, BudgetStop, check_suite, preservation, world

class StressTests(unittest.TestCase):
    def setUp(self):self.s=json.loads(SUITE.read_text());self.w=world()
    def test_original_records_and_frozen_components_preserved(self):self.assertTrue(preservation()['pass'])
    def test_exact_case_set_separate_from_original_cases(self):
        self.assertEqual({s['scenario_id'] for s in self.s},{'H01','H02','H03','H04','H05','H06','H07','H08','H08b','H09','H10','H11','H12'})
        self.assertTrue(all(s['split']=='stress' for s in self.s))
    def test_policy_conflicts_are_skipped_not_repaired(self):
        rows=check_suite(self.s,self.w)
        self.assertEqual({r['scenario_id'] for r in rows if r['status']=='SKIP'},{'H05','H06'})
    def test_multi_order_amounts_are_independent(self):
        rows=check_suite(self.s,self.w);ds=rows[0]['reference_decisions']
        self.assertEqual([d['refund_amount'] for d in ds],[1400,2548])
        self.assertNotEqual(ds[0]['order_id'],ds[1]['order_id'])
    def test_cod_wrong_size_20_hours(self):
        r=next(r for r in check_suite(self.s,self.w) if r['scenario_id']=='H04')['reference_decisions'][0]
        self.assertEqual((r['outcome_type'],r['refund_amount'],r['refund_method']),('immediate_refund',448,'Cartly Wallet'))
    def test_budget_blocks_before_network(self):
        b=Budget();b.spent=2.99
        with patch('evaluation.stress.urlopen') as net:
            with self.assertRaises(BudgetStop):b.call('agent',{'model':'gpt-6-astra','max_output_tokens':8192},Path('/unused'))
            net.assert_not_called()
    def test_observation_cases_have_no_scored_answers(self):
        for s in self.s:
            if s['grading']=='observe_only':self.assertFalse(s['acceptable_end_states'])
    def test_wrong_amount_is_a_precheck_failure(self):
        s=copy.deepcopy(self.s[0]);s['acceptable_end_states'][0]['refunds'][0]['amount']=2000
        self.assertEqual(check_suite([s],self.w)[0]['status'],'SKIP')

if __name__=='__main__':unittest.main()
