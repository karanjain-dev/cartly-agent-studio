"""Browser presentation adapter. All decisions/actions use CartlyService.

Only session-scoped, public audit fields leave this adapter. Raw model responses
(including encrypted reasoning), bearer tokens and credentials never do.
"""
import json
from contextlib import contextmanager
from queue import Queue
from threading import Thread
from uuid import uuid4

from fastapi import Depends, Header
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from service.agent import MODEL, PersistentAgent
from service.errors import ServiceError
from service.prompt import prompt_info
from service.repository import digest, load_seed

DEMOS = {"return": "U018", "cancel": "U014", "delay": "U031"}


def require_ok(response):
    if not response["ok"]:
        error = response["error"]
        raise ServiceError(error.get("code", "rejected"), error["message"], 409, error.get("rules"))
    return response["result"]


def session_row(conn, token):
    row = conn.execute("SELECT * FROM sessions WHERE token_hash=%s AND NOT revoked", (digest(token),)).fetchone()
    if not row:
        raise ServiceError("unauthorized", "Valid session authentication required", 401)
    return row


@contextmanager
def idle_conversation(service, token):
    """Approval/condition writes cannot interleave with an active model turn."""
    with service.repo.connect() as conn:
        s = session_row(conn, token)
        lock = "agent:" + s["session_id"]
        if not conn.execute("SELECT pg_try_advisory_lock(hashtext(%s)) AS acquired", (lock,)).fetchone()["acquired"]:
            raise ServiceError("conversation_busy", "Wait for the current reply before changing this conversation", 409)
        try:
            yield
        finally:
            conn.rollback()
            conn.execute("SELECT pg_advisory_unlock(hashtext(%s))", (lock,))


def public_event(row):
    name, result = row["event_type"], row["result"]
    if name in {"session.view", "agent.message", "customer.message"}:
        return None
    kind = "tool" if name.startswith("tool.") else "state"
    data = {"arguments": row["arguments"], "result": result}
    if name == "model.response":
        kind = "model"
        raw = result.get("result", {})
        data = {"model": raw.get("model", MODEL), "usage": raw.get("usage", {}),
                "toolsRequested": [o.get("name") for o in raw.get("output", []) if o.get("type") == "function_call"]}
    elif name.startswith("policy.") or name == "proposal.create":
        kind = "guardrail"
        decision = result.get("result", {}).get("decision", result.get("result", {}))
        data = {"request": row["arguments"], "decision": decision,
                "passed": bool(result.get("ok") and decision.get("action")),
                "rule": ", ".join(decision.get("rules", result.get("error", {}).get("rules", [])))}
    elif name.startswith("proposal.") or name in {"customer.acceptance", "action.execute"}:
        kind = "approval"
    elif name.startswith("session."):
        kind = "session"
    elif name == "model.error":
        kind = "error"
    return {"id": str(row["event_id"]), "type": kind, "title": name,
            "status": "complete" if result.get("ok") else "error", "data": data}


def snapshot(service, token, ready=False):
    repo = service.repo
    with repo.connect() as conn:
        s = session_row(conn, token)
        world, policy = repo.world(conn, s["world_id"])
        sid = s["session_id"]
        messages = conn.execute("SELECT role,content FROM messages WHERE session_id=%s ORDER BY sequence", (sid,)).fetchall()
        rows = conn.execute("SELECT * FROM audit_events WHERE session_id=%s ORDER BY event_id", (sid,)).fetchall()
        p = conn.execute("SELECT * FROM proposals WHERE session_id=%s ORDER BY proposal_sequence DESC LIMIT 1", (sid,)).fetchone()
        memory = conn.execute("SELECT turns FROM agent_context WHERE session_id=%s", (sid,)).fetchone()
        unlocked = conn.execute("SELECT pg_try_advisory_lock(hashtext(%s)) AS acquired", ("agent:" + sid,)).fetchone()["acquired"]
        if unlocked:
            conn.execute("SELECT pg_advisory_unlock(hashtext(%s))", ("agent:" + sid,))
    events = [e for r in rows if (e := public_event(r)) is not None]
    seen = {r["arguments"].get("arguments", {}).get("order_id") for r in rows
            if r["event_type"] == "tool.get_order" and r["result"].get("ok")}
    orders = [o for o in world["orders"] if o["user_id"] == s["verified_user_id"] and o["order_id"] in seen]
    proposal = None
    if p:
        d = p["decision"]
        proposal = {"id": p["proposal_id"], "termsHash": p["terms_hash"], "terms": p["terms"], "status": p["status"],
                    "decision": {**d, "amount": d.get("refund_amount"), "method": d.get("refund_method")}, "result": p["result"]}
    condition = None
    for row in reversed(rows):
        if row["event_type"] in {"policy.decide", "proposal.create"}:
            d = row["result"].get("result", {})
            d = d.get("decision", d)
            if "customer_unused_assertion" in d.get("missing", []) and d.get("item_id") not in s["facts"]:
                condition = {"order_id": d["order_id"], "item_id": d["item_id"]}
            break
    cost = 0
    for row in rows:
        if row["event_type"] == "model.response":
            u = row["result"].get("result", {}).get("usage", {})
            details = u.get("input_tokens_details", {})
            cached = details.get("cached_tokens", 0)
            written = details.get("cache_creation_tokens", details.get("cache_write_tokens", 0))
            cost += ((u.get("input_tokens", 0) - cached - written) * 10 + cached + written * 12.5 + u.get("output_tokens", 0) * 50) / 1_000_000
    info = prompt_info(world, policy)
    return {"demo": next((k for k, v in DEMOS.items() if v == s["principal_id"]), "return"),
            "messages": [{"role": "user" if m["role"] == "customer" else "assistant", "content": m["content"]} for m in messages],
            "events": events, "turns": memory["turns"] if memory else 0, "cost": cost,
            "verifiedUser": s["verified_user_id"], "orders": orders,
            "items": [i for i in world["order_items"] if i["order_id"] in {o["order_id"] for o in orders}],
            "changes": [c for r in rows for c in r["changes"]], "toolCalls": sum(r["event_type"].startswith("tool.") or r["event_type"] in {"policy.decide", "proposal.create"} for r in rows),
            "model": MODEL, "ended": bool(memory and memory["turns"] >= 20), "busy": not unlocked,
            "ready": ready, "date": world["config"]["today"], "proposal": proposal, "condition": condition,
            "promptSource": info["promptSource"], "promptHash": info["promptHash"], "policyTitle": info["policyTitle"],
            "notice": "Isolated PostgreSQL sandbox. API costs are estimates using the recorded baseline rates."}


class WebBody(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Demo(WebBody):
    demo: str = "return"


class Chat(WebBody):
    message: str = Field(min_length=1, max_length=3000)


class Approval(WebBody):
    proposalId: str
    termsHash: str
    accept: StrictBool


class Condition(WebBody):
    order_id: str
    item_id: str
    unused: StrictBool


def install(app, service, operator, customer, transport):
    # Every browser bridge request authenticates the website server. The
    # browser receives only an opaque HttpOnly session cookie from that server.
    private = [Depends(operator)]
    ready = transport is not None

    @app.post("/web/session", dependencies=private)
    def new_session(body: Demo):
        if body.demo not in DEMOS:
            raise ServiceError("invalid_demo", "Choose a valid demo customer")
        wid = "web-" + uuid4().hex
        service.repo.seed(wid)
        u = next(u for u in load_seed()["users"] if u["user_id"] == DEMOS[body.demo])
        auth = require_ok(service.login(wid, u["user_id"], email=u["email"]))["token"]
        return {"token": auth, "snapshot": snapshot(service, auth, ready)}

    @app.get("/web/session", dependencies=private)
    def get_session(auth=Depends(customer)):
        return snapshot(service, auth, ready)

    @app.get("/web/policy", dependencies=private)
    def policy(auth=Depends(customer)):
        with service.repo.connect() as conn:
            s = session_row(conn, auth)
            w, p = service.repo.world(conn, s["world_id"])
        return prompt_info(w, p)

    @app.post("/web/chat", dependencies=private)
    def chat(body: Chat, auth=Depends(customer), idempotency_key: str = Header(min_length=1, max_length=128)):
        if not ready:
            raise ServiceError("model_disabled", "Live model calls are disabled. Start with --enable-model to opt in", 503)
        with service.repo.connect() as conn:
            session_row(conn, auth)
        queue = Queue()
        def progress():
            queue.put({"type": "snapshot", "data": {**snapshot(service, auth, ready), "busy": True}})
        def run():
            try:
                result = PersistentAgent(service, transport).reply(auth, body.message, idempotency_key, progress)
                if not result["ok"]:
                    queue.put({"type": "error", "message": result["error"]["message"]})
            except ServiceError as exc:
                queue.put({"type": "error", "message": exc.message})
            except Exception:
                queue.put({"type": "error", "message": "The reply was interrupted. Reload to see saved activity."})
            finally:
                try:
                    queue.put({"type": "snapshot", "data": snapshot(service, auth, ready)})
                finally:
                    queue.put(None)
        Thread(target=run, daemon=True).start()
        def stream():
            while (event := queue.get()) is not None:
                yield json.dumps(event) + "\n"
            yield json.dumps({"type": "done"}) + "\n"
        return StreamingResponse(stream(), media_type="application/x-ndjson")

    @app.patch("/web/proposal", dependencies=private)
    def approve(body: Approval, auth=Depends(customer), idempotency_key: str = Header(min_length=1, max_length=100)):
        with idle_conversation(service, auth):
            require_ok(service.accept(auth, body.proposalId, body.termsHash, body.accept, "accept:" + idempotency_key))
            if body.accept:
                require_ok(service.execute(auth, body.proposalId, "execute:" + idempotency_key))
        return snapshot(service, auth, ready)

    @app.post("/web/condition", dependencies=private)
    def condition(body: Condition, auth=Depends(customer), idempotency_key: str = Header(min_length=1, max_length=128)):
        with idle_conversation(service, auth):
            require_ok(service.assert_unused(auth, **body.model_dump(), key=idempotency_key))
        return snapshot(service, auth, ready)
