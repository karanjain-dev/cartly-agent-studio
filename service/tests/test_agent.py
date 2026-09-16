import json

import pytest

from service.agent import PersistentAgent, schemas, service_state
from service.approval_flow import CartlyService
from service.errors import ServiceError
from service.tests.conftest import login
from service.demo import run_demo
from service.replay import replay


def response(text=None, name=None, args=None, call_id="call-test"):
    output = [{"type": "function_call", "call_id": call_id, "name": name, "arguments": json.dumps(args)}] if name else [
        {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": text}]}]
    return {"status": "completed", "model": "recorded-test-response", "usage": {"input_tokens": 10, "output_tokens": 5}, "output": output}


def test_agent_proposes_but_cannot_approve_or_execute(repo, sandbox):
    wid, s = sandbox
    t = login(s, wid, "U104")
    calls = []
    def transport(body):
        calls.append(body)
        return response(name="propose_action", args={"intent": "return", "order_id": "O1005", "item_id": "I1006", "reason": "wrong_item"})
    result = PersistentAgent(s, transport).reply(t, "The vest is the wrong size; refund me", "turn-1")
    assert result["ok"], result
    assert "448.00" in result["result"]["message"]
    assert "Cartly Wallet" in result["result"]["message"]
    assert not [r for r in repo.snapshot(wid)["refunds"] if r["order_id"] == "O1005"]
    exposed = {t["name"] for t in calls[0]["tools"]}
    assert not exposed.intersection({"accept", "execute", "issue_refund", "create_return", "system.complete_pickup", "assert_unused"})
    # Saved turn reuse after reconstructing the agent must not call the model again.
    assert PersistentAgent(CartlyService(repo), transport).reply(t, "The vest is the wrong size; refund me", "turn-1") == result
    assert len(calls) == 1
    p = result["result"]["proposal"]
    assert s.accept(t, p["proposal_id"], p["terms_hash"], True, "customer-yes")["ok"]
    assert s.execute(t, p["proposal_id"], "action")["ok"]
    assert replay(repo, wid)["pass"]


def test_agent_context_survives_reconstruction(repo, sandbox):
    wid, s = sandbox
    t = login(s, wid)
    seen = []
    def transport(body):
        seen.append(body)
        return response(text="Which order is this about?")
    assert PersistentAgent(s, transport).reply(t, "I want to return an item", "turn-1")["ok"]
    assert PersistentAgent(CartlyService(repo), transport).reply(t, "O0011", "turn-2")["ok"]
    contents = json.dumps(seen[1]["input"])
    assert "I want to return an item" in contents and "Which order is this about?" in contents and "O0011" in contents
    assert "Today's date is 2026-09-15 (IST)." in seen[0]["instructions"]
    assert "Before asking a customer to use the condition control, call decide_policy" in seen[0]["instructions"]
    exposed = {tool["name"]: tool for tool in seen[0]["tools"]}
    assert "makes that control visible" in exposed["decide_policy"]["description"]
    assert "exact server proposal and approval control" in exposed["propose_action"]["description"]


def test_model_error_saved_and_not_automatically_retried(sandbox):
    wid, s = sandbox
    t = login(s, wid)
    calls = []
    def broken(body):
        calls.append(body)
        raise ServiceError("model_api_error", "test API unavailable", 502)
    a = PersistentAgent(s, broken)
    result = a.reply(t, "hello", "turn-1")
    assert not result["ok"]
    assert a.reply(t, "hello", "turn-1") == result
    assert len(calls) == 1


def test_agent_forged_refund_still_rejected(repo, sandbox):
    wid, s = sandbox
    t = login(s, wid, "U104")
    replies = iter([response(name="issue_refund", args={"order_id": "O1005", "item_id": "I1006", "reason": "wrong_item", "confirmed": True}),
                    response(text="Please review the proposal before agreeing.")])
    result = PersistentAgent(s, lambda body: next(replies)).reply(t, "Refund me", "turn-1")
    assert result["ok"]
    assert not [r for r in repo.snapshot(wid)["refunds"] if r["order_id"] == "O1005"]


def test_full_demo_and_state_replay(repo):
    result = run_demo(repo, "x" * 40)
    assert result["model_calls"] == 0
    assert result["replay"]["pass"]
    assert result["replay"]["database_changes"] == 4  # Return, completed pickup, refund, Returned order.


def state_from(body):
    return json.loads(body["input"][0]["content"].split("\n", 1)[1])


def test_cancel_accept_execute_then_chat_receives_saved_result(repo, sandbox):
    wid, s = sandbox
    token = login(s, wid, "U014")
    seen = []
    def transport(body):
        seen.append(body)
        if len(seen) == 1:
            return response(name="propose_action", args={"intent": "cancel", "order_id": "O0143"})
        state = state_from(body)
        assert state["orders"][0]["status"] == "Cancelled"
        assert state["proposals"][0]["status"] == "executed"
        refund = state["proposals"][0]["result"]["refund"]
        assert (refund["amount"], refund["method"], refund["status"]) == (2548, "Card", "completed")
        assert state["refunds"] == [refund]
        return response(text="Your cancellation and ₹2,548 Card refund are recorded as completed.")
    p = PersistentAgent(s, transport).reply(token, "Cancel O0143", "one")["result"]["proposal"]
    assert s.accept(token, p["proposal_id"], p["terms_hash"], True, "accept")["ok"]
    assert s.execute(token, p["proposal_id"], "execute")["ok"]
    result = PersistentAgent(CartlyService(repo), transport).reply(token, "hey", "two")
    assert result["ok"]
    assert s.tool(token, "get_order", {"order_id": "O0143"})["result"]["order"]["status"] == "Cancelled"
    assert s.execute(token, p["proposal_id"], "retry")["replayed"]
    assert len([r for r in repo.snapshot(wid)["refunds"] if r["order_id"] == "O0143"]) == 1
    assert not state_from(seen[0])["proposals"]
    assert len([m for m in seen[1]["input"] if m.get("role") == "developer"]) == 1


def test_next_turn_refreshes_return_and_automatic_refund_state(repo, sandbox):
    wid, s = sandbox
    token = login(s, wid)
    assert s.assert_unused(token, "O0011", "I0011", True, "condition")["ok"]
    request = {"intent": "return", "order_id": "O0011", "item_id": "I0011", "reason": "change_of_mind"}
    p = s.propose(token, request, "quote")["result"]["proposal"]
    assert s.accept(token, p["proposal_id"], p["terms_hash"], True, "accept")["ok"]
    result = s.execute(token, p["proposal_id"], "execute")["result"]
    seen = []
    def transport(body):
        seen.append(state_from(body))
        return response(text="Here is the saved status.")
    assert PersistentAgent(s, transport).reply(token, "Status?", "one")["ok"]
    assert seen[0]["returns"][0]["pickup_status"] == "scheduled"
    assert seen[0]["refunds"] == []
    assert s.pickup(token, result["return"]["return_id"], "pickup")["ok"]
    assert PersistentAgent(CartlyService(repo), transport).reply(token, "Status now?", "two")["ok"]
    assert seen[1]["returns"][0]["pickup_status"] == "completed"
    assert seen[1]["refunds"][0]["amount"] == 1400
    assert seen[1]["orders"][0]["status"] == "Returned"


def test_service_context_excludes_unverified_and_other_customer_records(repo, sandbox):
    wid, s = sandbox
    token = login(s, wid, "U014")
    assert s.propose(token, {"intent": "cancel", "order_id": "O0143"}, "quote")["ok"]
    p = s.view(token)["result"]["proposals"][0]
    world = repo.snapshot(wid)
    for uid in [None, "U018"]:
        state = service_state({"verified_user_id": uid, "proposals": [p]}, world)
        assert all(state[key] == [] for key in ["orders", "refunds", "returns", "proposals"])
