# Cartly policy tools

Python standard library only. No agent, payment integration, or network calls.
The 12 policy table rows expose 13 callable names: `get_order` and `list_orders`
share a table row.

```python
from cartly import CartlySession

session = CartlySession()  # guarded=False by default; a new clean conversation
session.verify_user(user_id="U018", email="customer018@example.com")
session.get_order(order_id="O0011")
result = session.create_return(order_id="O0011", item_id="I0011", reason="change_of_mind", confirmed=True)
session.reset()  # clears identity/state, starts a new log, keeps the old log
```

Each tool returns `{ "ok": true, "result": ... }` or
`{ "ok": false, "error": { "message": ... } }`. Failed calls do not mutate
business state. Failed verification clears the current identity. Read results,
`state`, and `logs` are defensive copies.

## Interface

| Name | Arguments |
|---|---|
| verify_user | user_id, email=None, phone=None |
| get_order | order_id |
| list_orders | none; always limited to the verified user |
| search_policy | query (rule number or text) |
| check_serviceability | pincode |
| get_refund_history | order_id=None (adds all-time refunds on that owned order) |
| check_evidence | order_id, item_id |
| update_address | order_id, address, confirmed=False |
| cancel_order | order_id, confirmed=False, amount=None |
| create_return | order_id, item_id, reason, confirmed=False, amount=None |
| issue_refund | order_id, item_id, reason, confirmed=False, amount=None |
| issue_coupon | order_id, confirmed=False, amount=None |
| escalate_to_human | user_request, facts_found, rule_triggered, what_user_was_told, order_id=None, item_id=None |

The caller must explicitly supply reason: change_of_mind, damaged, defective,
or wrong_item. No reason is inferred from a fixture label. Unguarded mode accepts
the supplied reason without testing its truth; guarded mode checks wrong_item
against the ordered/delivered attributes (E11). A full address includes line1, city, state, pincode and country.
Every monetary `amount` argument is ignored; amounts come from database values.
Only literal boolean `confirmed=True` grants confirmation. The caller is
responsible for obtaining the user's explicit yes to the exact action, amount
and method before supplying it.

## Modes and invariants

Every mode enforces verification, ownership, confirmation, valid order states,
D2 serviceability, E7 method, E12 shipping once, duplicate-item-refund prevention, F2 fixed
₹100 coupons, and G3 complete escalation fields.

`CartlySession(guarded=True)` also checks E1/H1 windows, E2 category exceptions,
E5 immediate-refund eligibility, E6 photos, E9/H2 cumulative actual refunds,
E10 qualifying history, E11 wrong-item classification, and F1 late
eligibility / one coupon per order. Guard failures name the rule. Unguarded mode
intentionally permits these listed eligibility violations for evaluation; all
other invariants still apply. Cancellations are exempt from E9/H2 and E10.

`create_return` schedules a pickup and reports a quote; it does not refund.
For the synthetic system only, `session.complete_pickup(return_id)` atomically
completes pickup and refunds from current database values. It is **not** in the
agent tool registry. It checks ownership, duplicate refund prevention and, in
guarded mode, current cumulative/history limits again, so other intervening
refunds cannot bypass a limit. If rejected, neither pickup nor refund changes.
Shipping in a quote can change if another item's pickup refunds it first.
Legacy seeded returns without an operational reason require an explicit reason
argument to complete_pickup; there is no hidden-label fallback.

`issue_refund` enforces the under-₹500 damaged/defective/wrong-item restriction
only in guarded mode (E5). Unguarded mode can issue a direct refund for any valid
supplied reason, including an item with a scheduled return, while still enforcing
identity, ownership, state, confirmation and no duplicate refunds. Orders become
Returned only when all their items have completed pickups; partial returns
leave the order Delivered.

## State and logging

`data/` is read-only to this implementation. Each session loads JSON into memory,
and reset deep-copies its initial snapshot. The configured date and timestamp
are the only clock; no system-clock APIs are used. Logs are JSONL at
`logs/conversation_NNNN/calls.jsonl`; each call records its arguments, result or
error, fixed timestamp and mode. Conversation numbers distinguish logs without
reading a clock. A custom log directory inside data/ is rejected. Logs contain
synthetic identity/contact details as required by the complete-call log format.
Escalations are stored in memory; no message is sent to a real human.

## Checks

```sh
python3 -B -m unittest discover -s tests -v
python3 -B scripts/test_validate_data.py
python3 -B scripts/validate_data.py
```

## World data and scenario truth

`data/` contains world facts only. `scenario_truth/` contains per-record labels,
customer requests and edge tags, keyed by the original record IDs. Runtime tools
never import the evaluation loader or read that directory, including via symlink.
The evaluation-only `scripts/fixture_data.py` rejoins the layers for validator
and test assertions. Historical refunds retain their operational `reason` field.

All tool results recursively exclude scenario field keys, including handoff
results. G3 still accepts the caller's user_request and logs it as a call argument;
that request is not read from hidden scenario data or echoed in results.

The tool cannot observe whether an item is unused (E4); that fact must be
established in the conversation. The tool never consults hidden is_unused.
For E2, the current tool call is the report, timed using the fixed config
reference timestamp rather than hidden claim_reported_at.
