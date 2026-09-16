import copy
from pathlib import Path

import pytest

from service.policy import decide
from service.repository import load_seed, ROOT
from simulation.reference_calculator import calculate
from service.tests.conftest import approve, login

POLICY = (ROOT / "policy.md").read_text()


def fixture():
    w = load_seed()
    o = next(o for o in w["orders"] if o["order_id"] == "O0011")
    i = next(i for i in w["order_items"] if i["item_id"] == "I0011")
    f = {"intent": "return", "order_id": "O0011", "item_id": "I0011", "reason": "damaged"}
    return w, o, i, f


@pytest.mark.parametrize("category,days,reason,expected", [
    ("electronics", 7, "damaged", "return"), ("electronics", 8, "damaged", "escalate"),
    ("clothing", 10, "damaged", "return"), ("clothing", 11, "damaged", "escalate"),
    ("clothing", 11, "change_of_mind", "decline_no_change"),
])
def test_return_window(category, days, reason, expected):
    from datetime import date, timedelta
    w, o, i, f = fixture()
    i["category"] = category
    o["actual_delivery_date"] = (date.fromisoformat(w["config"]["today"]) - timedelta(days=days)).isoformat()
    f["reason"] = reason
    assert decide(w, POLICY, "U018", f, {"I0011": {"unused": True}})["outcome_type"] == expected


@pytest.mark.parametrize("price,photo,outcome", [(499, False, "immediate_refund"), (500, False, "return"),
                                               (2000, False, "return"), (2001, False, "clarify_then_resolve"),
                                               (2001, True, "return")])
def test_e5_e6_boundaries(price, photo, outcome):
    w, o, i, f = fixture()
    i.update(price=price, evidence_photo_uploaded=photo)
    assert decide(w, POLICY, "U018", f)["outcome_type"] == outcome


@pytest.mark.parametrize("hours,outcome", [(48, "return"), (49, "decline_no_change")])
def test_nonreturnable_exact_48_hours(hours, outcome):
    from datetime import datetime, timedelta
    w, o, i, f = fixture()
    i["category"] = "innerwear"
    at = datetime.fromisoformat(w["config"]["reference_datetime"]) - timedelta(hours=hours)
    o.update(actual_delivery_date=at.date().isoformat(), actual_delivery_at=at.isoformat())
    f["reason"] = "defective"
    assert decide(w, POLICY, "U018", f)["outcome_type"] == outcome


def test_cumulative_and_shipping_match_independent_calculator():
    w, o, i, f = fixture()
    i.update(price=3000, evidence_photo_uploaded=True)
    o["shipping_fee"] = 100
    w["refunds"].append({"order_id": "O0011", "item_id": "FIRST", "user_id": "U018", "amount": 3100,
                         "shipping_refunded": True, "reason": "damaged", "date": "2026-09-10", "status": "completed"})
    actual = decide(w, POLICY, "U018", f)
    oracle = calculate(w, "U018", f)
    assert actual["outcome_type"] == oracle["outcome_type"] == "escalate"
    assert actual["escalation_rule"] == oracle["escalation_rule"] == "H2"


@pytest.mark.parametrize("reason,amount", [("change_of_mind", 1400), ("damaged", 1548)])
def test_known_reference_amounts(reason, amount):
    w, o, i, f = fixture()
    f["reason"] = reason
    oracle = calculate(w, "U018", {**f, "is_unused": True})
    actual = decide(w, POLICY, "U018", f, {"I0011": {"unused": True}})
    assert actual["refund_amount"] == oracle["refund_amount"] == amount
    assert actual["refund_method"] == oracle["refund_method"] == "UPI"


def test_wrong_item_matches_requires_clarification():
    w, o, i, f = fixture()
    f["reason"] = "wrong_item"
    assert decide(w, POLICY, "U018", f)["missing"] == ["wrong_item_or_fit"]
    i["delivered_size"] = "XL"
    assert decide(w, POLICY, "U018", f)["refund_amount"] == 1548


def test_guarded_runtime_never_imports_oracle_or_truth():
    import ast
    for source in (ROOT / "service").glob("*.py"):
        tree = ast.parse(source.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith(("simulation", "evaluation", "scenario_truth")), source
            if isinstance(node, ast.Import):
                assert not any(a.name.startswith(("simulation", "evaluation", "scenario_truth")) for a in node.names), source


def test_all_actions_work_on_postgres_and_policy_rejects_shipped(repo, sandbox):
    wid, s = sandbox
    seed = load_seed()
    # Placed/Packed cancellations above the refund cap remain permitted.
    expensive = next(o for o in seed["orders"] if o["status"] in {"Placed", "Packed"}
                     and sum(i["price"] * i["quantity"] for i in seed["order_items"] if i["order_id"] == o["order_id"]) > 5000)
    t = login(s, wid, expensive["user_id"])
    p = approve(s, t, {"intent": "cancel", "order_id": expensive["order_id"]})
    assert s.execute(t, p, "cancel")["result"]["refund"]["amount"] > 5000
    placed = next(o for o in seed["orders"] if o["status"] == "Placed" and o["order_id"] != expensive["order_id"])
    t = login(s, wid, placed["user_id"])
    address = {**placed["delivery_address"], "line1": "Flat 12, Park View Apartments", "pincode": "560001"}
    request = {"intent": "address", "order_id": placed["order_id"], "address": address}
    assert s.execute(t, approve(s, t, request), "address")["ok"]
    request["address"]["pincode"] = "171001"
    assert s.decision(t, request)["result"]["rules"] == ["D2"]
    shipped = next(o for o in seed["orders"] if o["status"] == "Shipped")
    t = login(s, wid, shipped["user_id"])
    assert s.decision(t, {"intent": "cancel", "order_id": shipped["order_id"]})["result"]["outcome_type"] == "decline_no_change"


def test_coupon_lateness_and_history_from_database(repo, sandbox):
    from datetime import date
    wid, s = sandbox
    w = load_seed()
    today = date.fromisoformat(w["config"]["today"])
    late = next(o for o in w["orders"] if not o["actual_delivery_date"] and not o.get("coupon_issued")
                and (today - date.fromisoformat(o["promised_delivery_date"])).days > 5)
    t = login(s, wid, late["user_id"])
    req = {"intent": "coupon", "order_id": late["order_id"]}
    assert s.execute(t, approve(s, t, req), "coupon")["result"]["coupon"]["amount"] == 100
    assert s.decision(t, req)["result"]["outcome_type"] == "decline_no_change"
    five = next(o for o in w["orders"] if not o["actual_delivery_date"]
                and (today - date.fromisoformat(o["promised_delivery_date"])).days == 5)
    t = login(s, wid, five["user_id"])
    assert s.decision(t, {"intent": "coupon", "order_id": five["order_id"]})["result"]["outcome_type"] == "decline_no_change"


@pytest.mark.parametrize("count,reason,outcome", [(2, "damaged", "return"), (3, "damaged", "escalate"), (3, "cancellation", "return")])
def test_history_threshold(count, reason, outcome):
    w, o, i, f = fixture()
    w["refunds"] = [r for r in w["refunds"] if r["user_id"] != "U018"]
    for index in range(count):
        w["refunds"].append({"order_id": "OTHER", "item_id": None, "user_id": "U018", "amount": 100,
                             "shipping_refunded": False, "reason": reason, "date": "2026-09-10", "status": "completed"})
    assert decide(w, POLICY, "U018", f)["outcome_type"] == outcome
