"""The browser API exercises the same persistent agent and guarded actions."""
import json
from uuid import uuid4
import pytest

from fastapi.testclient import TestClient

from service.api import create_app
from service.prompt import PROMPT_PATH
from service.tests.test_agent import response

KEY = "test-server-key-" + "x" * 32


def client(repo, wid, transport=None):
    return TestClient(create_app(repo, KEY, wid, transport)), {"X-Cartly-Service-Key": KEY}


def session(c, headers, demo="return"):
    r = c.post("/web/session", headers=headers, json={"demo": demo})
    assert r.status_code == 200, r.text
    return {**headers, "Authorization": "Bearer " + r.json()["token"]}, r.json()["snapshot"]


def call(c, headers, name, args):
    return c.post("/v1/tools/" + name, headers=headers, json={"arguments": args}).json()


def verify(c, h):
    assert call(c, h, "verify_user", {"user_id": "U018", "email": "customer018@example.com"})["ok"]


def test_browser_auth_isolation_prompt_and_reset(repo, sandbox):
    wid, _ = sandbox
    c, headers = client(repo, wid)
    assert c.post("/web/session", json={}).status_code == 401
    h, initial = session(c, headers)
    assert initial["orders"] == [] and initial["verifiedUser"] is None
    verify(c, h)
    assert call(c, h, "get_order", {"order_id": "O0011"})["ok"]
    state = c.get("/web/session", headers=h).json()
    assert [o["order_id"] for o in state["orders"]] == ["O0011"]
    assert state["date"] == "2026-09-15"
    info = c.get("/web/policy", headers=h).json()
    assert info["prompt"].startswith(PROMPT_PATH.read_text())
    assert info["policy"] in info["prompt"]
    h2, fresh = session(c, headers)
    assert h2 != h and not fresh["orders"] and not fresh["messages"]
    assert call(c, h2, "get_order", {"order_id": "O0011"})["ok"] is False
    assert c.get("/web/session", headers={**headers, "Authorization": "Bearer fake"}).status_code == 401


def test_stream_proposal_confirmation_and_database_changes(repo, sandbox):
    wid, _ = sandbox
    replies = iter([
        response(name="get_order", args={"order_id": "O0011"}, call_id="read"),
        response(name="decide_policy", args={"intent": "return", "order_id": "O0011", "reason": "change_of_mind"}, call_id="decide"),
        response(text="Please record whether the kurta is unused."),
        response(name="propose_action", args={"intent": "return", "order_id": "O0011", "reason": "change_of_mind"}, call_id="propose"),
    ])
    payloads = []
    def transport(body):
        payloads.append(body)
        raw = next(replies)
        raw["output"].insert(0, {"type": "reasoning", "encrypted_content": "PRIVATE-REASONING"})
        return raw
    c, headers = client(repo, wid, transport)
    h, _ = session(c, headers)
    verify(c, h)
    first = c.post("/web/chat", headers={**h, "Idempotency-Key": "turn1"}, json={"message": "Return my kurta"})
    assert first.status_code == 200, first.text
    assert "PRIVATE-REASONING" not in first.text
    frames = [json.loads(line) for line in first.text.splitlines()]
    state = [f["data"] for f in frames if f["type"] == "snapshot"][-1]
    assert state["condition"] and state["proposal"] is None
    assert state["cost"] == pytest.approx(0.00024)
    assert any(e["type"] == "guardrail" for e in state["events"])
    assert len([f for f in frames if f["type"] == "snapshot"]) >= 4
    condition = {**state["condition"], "unused": True}
    assert c.post("/web/condition", headers={**h, "Idempotency-Key": "condition"}, json=condition).status_code == 200
    assert c.post("/web/chat", headers={**h, "Idempotency-Key": "turn2"}, json={"message": "Continue"}).status_code == 200
    state = c.get("/web/session", headers=h).json()
    p = state["proposal"]
    assert p["decision"]["amount"] == 1400 and p["decision"]["method"] == "UPI"
    assert not state["changes"]
    body = {"proposalId": p["id"], "termsHash": p["termsHash"], "accept": True}
    h2, _ = session(c, headers)
    assert c.patch("/web/proposal", headers={**h2, "Idempotency-Key": "foreign"}, json=body).status_code == 409
    accepted = c.patch("/web/proposal", headers={**h, "Idempotency-Key": "approval"}, json=body)
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["proposal"]["status"] == "executed"
    assert [d["table"] for d in accepted.json()["changes"]] == ["returns"]
    replay = c.patch("/web/proposal", headers={**h, "Idempotency-Key": "approval"}, json=body)
    assert replay.status_code == 200
    assert len(replay.json()["changes"]) == 1
    assert all(PROMPT_PATH.read_text() in b["instructions"] for b in payloads)
    # A new isolated browser sandbox must not inherit the return or messages.
    _, fresh = session(c, headers)
    assert fresh["changes"] == [] and fresh["messages"] == []


def test_browser_disabled_model_and_invalid_inputs(repo, sandbox):
    c, headers = client(repo, sandbox[0])
    h, _ = session(c, headers)
    r = c.post("/web/chat", headers={**h, "Idempotency-Key": "disabled"}, json={"message": "hello"})
    assert r.status_code == 503
    assert c.post("/web/session", headers=headers, json={"demo": "someone_else"}).status_code == 400
    assert c.patch("/web/proposal", headers={**h, "Idempotency-Key": "invalid"}, json={"proposalId": "x", "termsHash": "x", "accept": "true"}).status_code == 422


def test_browser_mutations_blocked_during_agent_turn(repo, sandbox):
    from service.repository import digest
    c, headers = client(repo, sandbox[0])
    h, _ = session(c, headers)
    verify(c, h)
    with repo.connect() as conn:
        s = conn.execute("SELECT session_id FROM sessions WHERE token_hash=%s", (digest(h["Authorization"].removeprefix("Bearer ")),)).fetchone()
        lock = "agent:" + s["session_id"]
        conn.execute("SELECT pg_advisory_lock(hashtext(%s))", (lock,))
        try:
            assert c.get("/web/session", headers=h).json()["busy"] is True
            r = c.post("/web/condition", headers={**h, "Idempotency-Key": "busy"}, json={"order_id": "O0011", "item_id": "I0011", "unused": True})
            assert r.status_code == 409 and r.json()["error"]["code"] == "conversation_busy"
        finally:
            conn.execute("SELECT pg_advisory_unlock(hashtext(%s))", (lock,))
