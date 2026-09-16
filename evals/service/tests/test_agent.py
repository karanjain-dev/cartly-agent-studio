import json

import pytest

from service.agent import PersistentAgent, schemas
from service.core import CartlyService
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
