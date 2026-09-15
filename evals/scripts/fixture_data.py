"""Evaluation-only loader. Runtime tools must never import this module.

Rejoins scenario labels for fixture validation/tests only. Tools load data/ alone.
"""
import json
from pathlib import Path

TABLE_IDS={'users':'user_id','orders':'order_id','order_items':'item_id','refunds':'refund_id','returns':'return_id'}
HIDDEN_FIELDS={'is_unused','claim_reason','claim_reported_at','user_request','requesting_user_id','requested_delivery_address','edge_case'}

def load_eval_data(data_dir,truth_dir=None):
    data_dir=Path(data_dir)
    truth_dir=Path(truth_dir) if truth_dir else data_dir.parent/'scenario_truth'
    data={name:json.loads((data_dir/(name+'.json')).read_text()) for name in ['config',*TABLE_IDS,'serviceable_pincodes']}
    for table,key in TABLE_IDS.items():
        hidden=json.loads((truth_dir/(table+'.json')).read_text())
        mapping={row[key]:row for row in hidden}
        if len(mapping)!=len(hidden):raise ValueError(f'{table}: duplicate scenario IDs')
        if set(mapping)!={row[key] for row in data[table]}:raise ValueError(f'{table}: scenario IDs do not match world IDs')
        for row in data[table]:
            if HIDDEN_FIELDS & row.keys():raise ValueError(f'{table} {row[key]}: scenario fields leaked into world')
            truth=mapping[row[key]]
            if set(truth)-HIDDEN_FIELDS-{key}:raise ValueError(f'{table} {row[key]}: world fields duplicated into scenario truth')
            row.update(truth)
    return data
