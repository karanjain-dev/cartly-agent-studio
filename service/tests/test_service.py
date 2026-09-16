import copy
import json
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from service.api import create_app
from service.core import CartlyService
from service.errors import ServiceError
from service.repository import digest, load_seed
from service.tests.conftest import approve, login

RETURN = {"intent": "return", "order_id": "O0011", "item_id": "I0011", "reason": "change_of_mind"}
H04 = {"intent": "return", "order_id": "O1005", "item_id": "I1006", "reason": "wrong_item"}


def test_seed_roundtrip_and_idempotent_setup(repo, sandbox):
    wid, _ = sandbox
    original = load_seed()
    actual = repo.snapshot(wid)
    for key, value in original.items():
        if isinstance(value, list):
            assert sorted(map(digest, actual[key])) == sorted(map(digest, value))
        else:
            assert actual[key] == value
    assert repo.seed(wid)["created"] is False
    assert repo.verify_audit(wid)["pass"]


def test_change_of_mind_requires_customer_fact_and_approval(repo, sandbox):
    wid, s = sandbox
    t = login(s, wid)
    assert s.decision(t, RETURN)["result"]["missing"] == ["customer_unused_assertion"]
    assert s.assert_unused(t, "O0011", "I0011", True, "fact")["ok"]
    q = s.propose(t, RETURN, "quote")["result"]
    assert q["decision"]["refund_amount"] == 1400
    assert q["decision"]["refund_method"] == "UPI"
    pid = q["proposal"]["proposal_id"]
    assert not s.execute(t, pid, "premature")["ok"]
    assert not s.tool(t, "create_return", {"order_id": "O0011", "item_id": "I0011", "reason": "change_of_mind", "confirmed": True})["ok"]
    assert s.accept(t, pid, q["proposal"]["terms_hash"], True, "consent")["ok"]
    result = s.execute(t, pid, "execute")
    assert result["ok"], result
    assert result["result"]["refund_amount"] == 1400
    assert len(repo.snapshot(wid)["refunds"]) == len(load_seed()["refunds"])
    # New service object simulates process restart. Saved token and action survive.
    restarted = CartlyService(repo)
    assert restarted.execute(t, pid, "execute") == result
    assert restarted.execute(t, pid, "different-key")["replayed"]
    rid = result["result"]["return"]["return_id"]
    pickup = restarted.pickup(t, rid, "pickup")
    assert pickup["ok"], pickup
    assert pickup["result"]["refund"]["amount"] == 1400
    assert restarted.pickup(t, rid, "pickup") == pickup
    assert not restarted.pickup(t, rid, "duplicate-pickup")["ok"]
    assert repo.verify_audit(wid)["pass"]


def test_h04_refund_and_concurrent_exactly_once(repo, sandbox):
    wid, s = sandbox
    t = login(s, wid, "U104")
    pid = approve(s, t, H04)
    with ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(lambda _: CartlyService(repo).execute(t, pid, "same-request"), range(5)))
    assert all(r == results[0] for r in results)
    assert results[0]["ok"], results[0]
    refunds = [r for r in repo.snapshot(wid)["refunds"] if r["order_id"] == "O1005"]
    assert len(refunds) == 1
    assert (refunds[0]["amount"], refunds[0]["method"], refunds[0]["shipping_refunded"]) == (448, "Cartly Wallet", True)
    assert repo.verify_audit(wid)["pass"]


def test_other_conversation_sees_refund_and_cannot_repeat(repo, sandbox):
    wid, s = sandbox
    t = login(s, wid, "U104")
    pid = approve(s, t, H04)
    assert s.execute(t, pid, "refund")["ok"]
    other = login(CartlyService(repo), wid, "U104")
    assert s.decision(other, H04)["result"]["outcome_type"] == "decline_no_change"
    history = s.tool(other, "get_refund_history", {"order_id": "O1005"})
    assert len(history["result"]["order_refunds"]) == 1


def test_unverified_identity_and_foreign_order_errors(sandbox):
    wid, s = sandbox
    t = login(s, wid, verified=False)
    assert not s.tool(t, "get_order", {"order_id": "O0011"})["ok"]
    for request in [RETURN, H04]:
        assert s.decision(t, request)["error"]["code"] == "verification_required"
    user = next(u for u in load_seed()["users"] if u["user_id"] == "U018")
    assert s.tool(t, "verify_user", {"user_id": "U018", "email": user["email"]})["ok"]
    a = s.tool(t, "get_order", {"order_id": "O1005"})
    b = s.tool(t, "get_order", {"order_id": "NO_SUCH_ORDER"})
    assert a == b and not a["ok"]
    assert not s.tool(t, "verify_user", {"user_id": "U104", "email": "faizan.ansari@example.com"})["ok"]
    assert not s.tool(t, "get_order", {"order_id": "O0011"})["ok"]


@pytest.mark.parametrize("reply", ["yes", "just cancel it", "okay but also give me a coupon"])
def test_free_text_cannot_forge_acceptance(sandbox, reply):
    wid, s = sandbox
    t = login(s, wid, "U104")
    p = s.propose(t, H04, "proposal")["result"]["proposal"]
    s.message(t, reply, "new-message")
    assert not s.accept(t, p["proposal_id"], p["terms_hash"], True, "accept")["ok"]
    assert not s.execute(t, p["proposal_id"], "execute")["ok"]


def test_changed_terms_and_new_message_invalidate(sandbox):
    wid, s = sandbox
    t = login(s, wid, "U104")
    p = s.propose(t, H04, "proposal")["result"]["proposal"]
    assert not s.accept(t, p["proposal_id"], "forged-hash", True, "forged")["ok"]
    assert s.accept(t, p["proposal_id"], p["terms_hash"], True, "actual")["ok"]
    s.message(t, "Wait, don't do it", "stop")
    assert not s.execute(t, p["proposal_id"], "execute")["ok"]


def test_two_sessions_cannot_reuse_consent(sandbox):
    wid, s = sandbox
    t = login(s, wid, "U104")
    p = s.propose(t, H04, "p")["result"]["proposal"]
    other = login(s, wid, "U104")
    assert not s.accept(other, p["proposal_id"], p["terms_hash"], True, "accept")["ok"]


def test_idempotency_conflict_and_no_secret_in_audit(repo, sandbox):
    wid, s = sandbox
    t = login(s, wid)
    assert s.message(t, "hello", "one")["ok"]
    assert s.message(t, "different", "one")["error"]["code"] == "idempotency_conflict"
    with repo.connect() as conn:
        rows = conn.execute("SELECT arguments,result FROM audit_events WHERE world_id=%s", (wid,)).fetchall()
    assert t not in json.dumps(rows)


def test_audit_is_append_only(repo, sandbox):
    wid, _ = sandbox
    with pytest.raises(psycopg.Error, match="append-only"):
        with repo.connect() as conn:
            conn.execute("UPDATE audit_events SET event_type='forged' WHERE world_id=%s", (wid,))
    assert repo.verify_audit(wid)["pass"]


def test_audit_failure_rolls_back_refund_and_confirmation(repo, sandbox, monkeypatch):
    wid, s = sandbox
    t = login(s, wid, "U104")
    pid = approve(s, t, H04)
    initial = repo.snapshot(wid)
    original = repo.audit
    def broken(*args, **kwargs):
        raise RuntimeError("audit storage unavailable")
    monkeypatch.setattr(repo, "audit", broken)
    with pytest.raises(RuntimeError, match="audit storage"):
        s.execute(t, pid, "execute")
    monkeypatch.setattr(repo, "audit", original)
    assert repo.snapshot(wid) == initial
    assert s.execute(t, pid, "execute")["ok"]


def test_stale_quote_rechecks_current_database(repo, sandbox):
    wid, s = sandbox
    t = login(s, wid, "U104")
    pid = approve(s, t, H04)
    with repo.connect() as conn:
        row = conn.execute("SELECT record FROM order_items WHERE world_id=%s AND item_id='I1006'", (wid,)).fetchone()["record"]
        row["price"] = 450
        repo.write_row(conn, wid, "order_items", row, update=True)
    result = s.execute(t, pid, "execute")
    assert result["error"]["code"] == "proposal_changed"
    assert not [r for r in repo.snapshot(wid)["refunds"] if r["order_id"] == "O1005"]


def test_database_blocks_duplicate_shipping_and_foreign_owner(repo, sandbox):
    wid, s = sandbox
    t = login(s, wid, "U104")
    pid = approve(s, t, H04)
    r = s.execute(t, pid, "execute")["result"]["refund"]
    duplicate = {**r, "refund_id": "FORGED"}
    with pytest.raises(psycopg.IntegrityError):
        with repo.connect() as conn:
            repo.write_row(conn, wid, "refunds", duplicate)
    foreign = {**r, "refund_id": "FOREIGN", "user_id": "U018"}
    with pytest.raises(psycopg.IntegrityError):
        with repo.connect() as conn:
            repo.write_row(conn, wid, "refunds", foreign)


def test_http_authorization_and_strict_confirmation(repo, sandbox):
    wid, s = sandbox
    client = TestClient(create_app(repo, "operator-secret-" + "x" * 32, wid))
    assert client.get("/health").status_code == 200
    assert client.get("/v1/session").status_code == 401
    assert client.post("/v1/sessions", json={"user_id": "U104", "email": "faizan.ansari@example.com"}).status_code == 401
    t = login(s, wid, "U104")
    headers = {"Authorization": "Bearer " + t, "Idempotency-Key": "accept"}
    assert client.post("/v1/tools/get_order", headers=headers, json={"arguments": {"order_id": "O1005"}}).status_code == 401
    p = s.propose(t, H04, "p")["result"]["proposal"]
    assert client.post(f"/v1/proposals/{p['proposal_id']}/acceptance", headers=headers,
                       json={"terms_hash": p["terms_hash"], "accept": "true"}).status_code == 422
    response = client.post(f"/v1/proposals/{p['proposal_id']}/acceptance", headers=headers,
                           json={"terms_hash": p["terms_hash"], "accept": True, "new_condition": "plus coupon"})
    assert response.status_code == 422
    response = client.post(f"/v1/proposals/{p['proposal_id']}/acceptance", headers=headers,
                           json={"terms_hash": p["terms_hash"], "accept": True})
    assert response.json()["ok"]
    assert response.headers["Cache-Control"] == "no-store"
