"""Operational policy decisions. Independent of the evaluation answer key.

Only world data and authenticated customer assertions are accepted. Never import
simulation/, evaluation/, scenarios/, or scenario_truth/ into the runtime.
"""
from datetime import date, datetime, timedelta
from decimal import Decimal

from cartly.tools import ACCESS_ERROR, REASONS
from service.engine import GuardedEngine
from service.errors import ServiceError

ACTIONS = {"return": "create_return", "immediate_refund": "issue_refund", "cancel": "cancel_order",
           "coupon": "issue_coupon", "address_update": "update_address"}


def decide(world, policy, user_id, request, assertions=None):
    assertions = assertions or {}
    oid, iid, intent = request.get("order_id"), request.get("item_id"), request.get("intent")

    def result(outcome, rules, **values):
        return {"outcome_type": outcome, "order_id": oid, "item_id": iid, "reason": None,
                "refund_amount": None, "refund_method": None, "shipping_refunded": False,
                "escalation_rule": rules[0] if outcome == "escalate" else None,
                "rules": rules, "action": ACTIONS.get(outcome), **values}

    if intent in {"safety", "legal", "human", "uncovered"}:
        if oid:
            GuardedEngine(world, policy, user_id)._order(oid)
        if intent == "human" and assertions.get("human_requests", 0) < 2:
            return result("clarify_then_resolve", ["G2", "G4"], missing=["second_human_request"],
                          explanation="A single request for a person does not establish the twice-requested trigger")
        return result("escalate", ["G6" if intent == "safety" else "A3" if intent == "uncovered" else "G2"])
    order = next((o for o in world["orders"] if o["order_id"] == oid and o["user_id"] == user_id), None)
    if not order:
        raise ServiceError("not_available", ACCESS_ERROR, 404, ["A2"])
    engine = GuardedEngine(world, policy, user_id)
    today = date.fromisoformat(world["config"]["today"])
    prior = engine._refunds(order)
    method = engine._method(order)
    item = None
    reason = request.get("reason")
    if intent == "cancel":
        if order["status"] not in {"Placed", "Packed"}:
            return result("decline_no_change", ["C2"], item_id=None) if order["status"] in {"Shipped", "Out for delivery"} else result("escalate", ["A3"], item_id=None)
        amount, shipping = engine._amount(order, None, "cancellation")
        decision = result("cancel", ["C1", "E7", "E9"], item_id=None, reason="cancellation",
                          refund_amount=amount, refund_method=method, shipping_refunded=shipping)
    elif intent == "address":
        if order["status"] != "Placed":
            return result("decline_no_change", ["D1"])
        address = request.get("address") or {}
        required = ["line1", "city", "state", "pincode", "country"]
        if any(not isinstance(address.get(k), str) or not address[k].strip() for k in required):
            return result("clarify_then_resolve", ["D3"], missing=["full_address"])
        if str(address["pincode"]) not in world["serviceable_pincodes"]["serviceable_pincodes"]:
            return result("decline_no_change", ["D2"])
        decision = result("address_update", ["D1", "D2", "D3"], address=address)
    elif intent == "coupon":
        end = date.fromisoformat(order["actual_delivery_date"]) if order["actual_delivery_date"] else today
        late = (end - date.fromisoformat(order["promised_delivery_date"])).days
        if late <= 5 or order.get("coupon_issued") or any(c["order_id"] == oid for c in world["coupons"]):
            return result("decline_no_change", ["F1"], lateness_days=late)
        decision = result("coupon", ["F1", "F2"], coupon_amount=100)
    elif intent == "return":
        history = [r for r in world["refunds"] if r["user_id"] == user_id and r["status"] == "completed"
                   and r["reason"] in REASONS and today - timedelta(days=90) <= date.fromisoformat(r["date"]) <= today]
        if len(history) >= 3:
            return result("escalate", ["E10"])
        items = [i for i in world["order_items"] if i["order_id"] == oid and (not iid or i["item_id"] == iid)]
        if iid and not items:
            raise ServiceError("not_available", ACCESS_ERROR, 404, ["A2"])
        if len(items) != 1:
            return result("clarify_then_resolve", ["E8"], missing=["item_id"])
        item = items[0]
        iid = item["item_id"]
        if any(r["item_id"] == iid for r in prior):
            return result("decline_no_change", ["E8"], explanation="Item already refunded")
        if any(r["item_id"] == iid for r in world["returns"]):
            return result("decline_no_change", ["G5"], explanation="Return already exists; refund follows completed pickup")
        if order["status"] != "Delivered" or not order["actual_delivery_date"]:
            return result("escalate", ["A3"])
        if reason not in REASONS:
            return result("clarify_then_resolve", ["E11"], missing=["reason"])
        if reason == "wrong_item":
            pairs = ["product_name", "size", "color", "quantity"]
            if not any(item.get("ordered_" + a) != item.get("delivered_" + a) for a in pairs):
                return result("clarify_then_resolve", ["E11"], missing=["wrong_item_or_fit"],
                              explanation="Ordered and delivered attributes match; clarify fit or preference")
        days = (today - date.fromisoformat(order["actual_delivery_date"])).days
        if days < 0:
            raise ServiceError("invalid_data", "Delivery date is after the configured reference date")
        if days > (7 if item["category"] == "electronics" else 10):
            return result("escalate" if reason in {"damaged", "defective"} else "decline_no_change", ["H1", "E1"])
        if item["category"] in {"innerwear", "perishables", "personalized"}:
            if reason == "change_of_mind":
                return result("decline_no_change", ["E2"])
            if not order.get("actual_delivery_at"):
                return result("clarify_then_resolve", ["E2"], missing=["delivery_time"])
            age = datetime.fromisoformat(world["config"]["reference_datetime"]) - datetime.fromisoformat(order["actual_delivery_at"])
            if age < timedelta(0) or age > timedelta(hours=48):
                return result("decline_no_change", ["E2"])
        if reason == "change_of_mind":
            unused = assertions.get(iid, {}).get("unused")
            if unused is None:
                return result("clarify_then_resolve", ["E4"], missing=["customer_unused_assertion"])
            if unused is not True:
                return result("decline_no_change", ["E4"])
        value = engine._value(item)
        if reason == "change_of_mind" and value < 99:
            return result("escalate", ["A3", "E4"], explanation="Negative refund requires human review")
        if reason != "change_of_mind" and value > 2000 and not item["evidence_photo_uploaded"]:
            return result("clarify_then_resolve", ["E6"], missing=["photo_uploaded_to_order"])
        amount, shipping = engine._amount(order, item, reason)
        if sum(Decimal(str(r["amount"])) for r in prior) + Decimal(str(amount)) > 5000:
            return result("escalate", ["H2", "E9"])
        kind = "immediate_refund" if reason != "change_of_mind" and value < 500 else "return"
        decision = result(kind, ["E3" if reason != "change_of_mind" else "E4", "E5", "E7", "E12"],
                          reason=reason, refund_amount=amount, refund_method=method, shipping_refunded=shipping)
    else:
        return result("escalate", ["A3"])
    # A read-only dry run checks the existing guarded implementation too.
    trial = engine.call(decision["action"], **action_arguments(decision, request))
    if not trial["ok"]:
        return result("decline_no_change", decision["rules"], explanation=trial["error"]["message"])
    return decision


def action_arguments(decision, request):
    args = {"order_id": decision["order_id"], "confirmed": True}
    if decision["action"] in {"issue_refund", "create_return"}:
        args.update(item_id=decision["item_id"], reason=decision["reason"])
    if decision["action"] == "update_address":
        args["address"] = request["address"]
    return args


def proposal_text(decision):
    oid = decision["order_id"]
    amount = format(Decimal(str(decision.get("refund_amount") or 0)), ".2f")
    method = decision.get("refund_method")
    if decision["action"] == "create_return":
        return f"Create a return for item {decision['item_id']} on order {oid}. Refund ₹{amount} to {method} automatically after pickup completes. Do you agree?"
    if decision["action"] == "issue_refund":
        return f"Issue an immediate refund of ₹{amount} to {method} for item {decision['item_id']} on order {oid}. No return is needed. Do you agree?"
    if decision["action"] == "cancel_order":
        return f"Cancel order {oid} and refund ₹{amount} to {method}. Do you agree?"
    if decision["action"] == "issue_coupon":
        return f"Issue one ₹100 coupon for order {oid}. Do you agree?"
    address = ", ".join(str(v) for v in decision["address"].values() if v)
    return f"Update the delivery address for order {oid} to: {address}. Do you agree?"
