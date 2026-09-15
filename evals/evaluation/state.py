"""Exact state differences; generated IDs remain available for auditing."""
import copy
KEYS={'users':'user_id','orders':'order_id','order_items':'item_id','refunds':'refund_id',
      'returns':'return_id','coupons':'coupon_id','escalations':'escalation_id'}

def changes(before,after):
    result=[]
    for table in sorted(set(before)|set(after)):
        a,b=before.get(table,[]),after.get(table,[])
        if a==b:continue
        if table not in KEYS:
            result.append({'table':table,'operation':'replace','key':{},'values':copy.deepcopy(b)});continue
        field=KEYS[table];old={r[field]:r for r in a};new={r[field]:r for r in b}
        for key in sorted(set(old)|set(new)):
            if key not in old:op='insert';values=new[key]
            elif key not in new:op='delete';values=old[key]
            else:
                values={k:copy.deepcopy(new[key].get(k)) for k in set(old[key])|set(new[key]) if old[key].get(k)!=new[key].get(k)}
                if not values:continue
                op='update'
            result.append({'table':table,'operation':op,'key':{field:key},'values':copy.deepcopy(values)})
    return result


def apply_changes(state,delta):
    out=copy.deepcopy(state)
    for c in delta:
        t=c['table'];op=c['operation']
        if op=='insert':out.setdefault(t,[]).append(copy.deepcopy(c['values']))
        elif op=='replace':out[t]=copy.deepcopy(c['values'])
        else:
            row=next(r for r in out[t] if all(r.get(k)==v for k,v in c['key'].items()))
            if op=='update':row.update(copy.deepcopy(c['values']))
            elif op=='delete':out[t].remove(row)
    return out
