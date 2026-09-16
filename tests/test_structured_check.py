import copy
import json
import unittest
from io import BytesIO
from unittest.mock import patch
from simulation.structured_check import SCHEMA,FIELDS,select_fields,projected_expected,coverage,ROOT
from simulation.classify_structured import classify,verify_decision
from simulation.model_client import ModelClient

class StructuredCheckTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scenarios=json.loads((ROOT/'scenarios/scenarios.json').read_text())
        cls.world={n:json.loads((ROOT/'data'/(n+'.json')).read_text()) for n in ['config','users','orders','order_items','refunds','returns','serviceable_pincodes']}
    def expected(self,sid='S001'):
        return projected_expected(next(s for s in self.scenarios if s['scenario_id']==sid),self.world)
    def test_exact_eight_schema_fields(self):
        self.assertEqual(set(SCHEMA['properties']),set(FIELDS));self.assertEqual(set(SCHEMA['required']),set(FIELDS));self.assertFalse(SCHEMA['additionalProperties'])
    def test_api_uses_strict_json_schema(self):
        answer={'id':'offline','status':'completed','model':'gpt-4.1-mini','output':[{'content':[{'type':'output_text','text':json.dumps(self.expected()[0])}]}]}
        bodies=[]
        def open_request(request,**kwargs):bodies.append(json.loads(request.data));return BytesIO(json.dumps(answer).encode())
        with patch('simulation.model_client.api_key',return_value='placeholder'),patch('simulation.model_client.urlopen',side_effect=open_request):
            ModelClient().complete('Return JSON',{},response_schema=SCHEMA)
        self.assertEqual(bodies[0]['text']['format']['schema'],SCHEMA);self.assertTrue(bodies[0]['text']['format']['strict'])
    def test_ignores_all_unlisted_fields(self):
        d=self.expected()[0];other={**d,'wording':'Different prose','irrelevant':42}
        self.assertEqual(select_fields(d),select_fields(other))
    def test_any_acceptable_state_matches(self):
        expected=self.expected('S009')
        self.assertEqual(classify(expected,[expected[0],expected[1]],[[],[]]),'MATCH')
    def test_consensus_nonmatch_is_suspect(self):
        expected=self.expected();d={**expected[0],'refund_amount':5}
        self.assertEqual(classify(expected,[d,d],[[{'evidence':'bad math'}],[{'evidence':'bad math'}]]),'SCENARIO_SUSPECT')
    def test_disagreement_verified_error(self):
        expected=self.expected();d={**expected[0],'refund_amount':5}
        self.assertEqual(classify(expected,[expected[0],d],[[],[{'evidence':'bad math'}]]),'MODEL_ERROR')
    def test_unexplained_primary_disagreement(self):
        expected=self.expected();d={**expected[0],'outcome_type':'clarify_then_resolve','refund_amount':None}
        self.assertEqual(classify(expected,[expected[0],d],[[],[]]),'POLICY_AMBIGUOUS')
    def test_secondary_output_field_mistake_is_model_error(self):
        expected=self.expected();d={**expected[0],'item_id':None}
        self.assertEqual(classify(expected,[expected[0],d],[[],[]]),'MODEL_ERROR')
    def test_database_audit_does_not_use_scenario_label(self):
        s=copy.deepcopy(self.scenarios[0]);d=self.expected()[0];d['refund_amount']=2000
        s['acceptable_end_states']=[];s['rules_tested']=[]
        evidence=verify_decision(s,d,self.world)
        self.assertTrue(any(e['field']=='refund_amount' and '1400' in e['evidence'] for e in evidence))
    def test_expected_projection_all_cases(self):
        for s in self.scenarios:
            for state in projected_expected(s,self.world):self.assertEqual(set(state),set(FIELDS))
    def test_coverage(self):
        c=coverage(self.scenarios);self.assertEqual(c['distinct_users'],23);self.assertEqual(c['distinct_orders'],37);self.assertEqual(c['orders_used_more_than_twice'],[])

if __name__=='__main__':unittest.main()
