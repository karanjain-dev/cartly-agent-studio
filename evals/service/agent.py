"""Persistent single-agent adapter. The original baseline agent stays frozen.

The model can read, ask, and propose. It cannot invoke customer acceptance or
pickup completion. Mutations require customer approval through the service API.
"""
import inspect
import json
import os
from pathlib import Path
from uuid import uuid4

import httpx
from psycopg.types.json import Jsonb

from cartly.tools import CartlySession, TOOLS, WRITES
from service.errors import ServiceError
from service.repository import digest, ROOT

MODEL = "gpt-6-astra"
MAX_API_CALLS = 40  # Per session, persisted across service restarts.


def schemas():
    result = []
    for name in TOOLS:
        if name in WRITES:
            continue
        fields = {}
        for key, param in inspect.signature(getattr(CartlySession, "_" + name)).parameters.items():
            if key == "self":
                continue
            fields[key] = {"type": ["string", "null"] if param.default is None else "string"}
        result.append({"type": "function", "name": name, "description": name.replace("_", " "), "strict": True,
                       "parameters": {"type": "object", "properties": fields, "required": list(fields), "additionalProperties": False}})
    address = {k: {"type": "string"} for k in ["line1", "line2", "city", "state", "pincode", "country"]}
    fields = {"intent": {"type": "string", "enum": ["return", "cancel", "address", "coupon", "safety", "legal", "human", "uncovered"]},
              "order_id": {"type": ["string", "null"]}, "item_id": {"type": ["string", "null"]},
              "reason": {"type": ["string", "null"], "enum": ["change_of_mind", "damaged", "defective", "wrong_item", None]},
              "address": {"type": ["object", "null"], "properties": address, "required": list(address), "additionalProperties": False}}
    for name in ["decide_policy", "propose_action"]:
        result.append({"type": "function", "name": name,
                       "description": "Read policy decision from the database" if name == "decide_policy" else "Present an exact proposal to the customer for approval; does not execute it",
                       "strict": True, "parameters": {"type": "object", "properties": fields, "required": list(fields), "additionalProperties": False}})
    return result


def load_api_key():
    key = os.environ.get("OPENAI_API_KEY")
    if not key and (ROOT / ".env").exists():
        for line in (ROOT / ".env").read_text().splitlines():
            if line.startswith("OPENAI_API_KEY="):
                key = line.split("=", 1)[1].strip().strip("\"'")
                break
    if not key:
        raise ServiceError("model_unconfigured", "Set OPENAI_API_KEY to enable live agent replies", 503)
    return key


class OpenAITransport:
    def __init__(self, api_key):
        self.api_key = api_key

    def __call__(self, body):
        try:
            with httpx.Client(timeout=180) as client:
                response = client.post("https://api.openai.com/v1/responses", json=body,
                                       headers={"Authorization": "Bearer " + self.api_key})
                if response.status_code != 200:
                    raise ServiceError("model_api_error", f"Model request failed (HTTP {response.status_code}); no automatic retry", 502)
                return response.json()
        except httpx.HTTPError:
            raise ServiceError("model_connection_error", "Model request interrupted; no automatic retry", 502) from None


class PersistentAgent:
    def __init__(self, service, transport):
        self.service, self.transport = service, transport

    def reply(self, token, text, request_id):
        if not request_id or len(request_id) > 128:
            raise ServiceError("invalid_request", "A request ID is required")
        repo = self.service.repo
        with repo.connect() as conn:
            s = conn.execute("SELECT * FROM sessions WHERE token_hash=%s AND NOT revoked", (digest(token),)).fetchone()
            if not s:
                raise ServiceError("unauthorized", "Valid session authentication required", 401)
            sid = s["session_id"]
            locked = conn.execute("SELECT pg_try_advisory_lock(hashtext(%s)) AS locked", ("agent:" + sid,)).fetchone()["locked"]
            if not locked:
                raise ServiceError("conversation_busy", "A reply is already being prepared", 409)
            try:
                return self._reply(conn, s, token, text, request_id)
            finally:
                # Advisory locks also release automatically if the process dies.
                conn.rollback()
                conn.execute("SELECT pg_advisory_unlock(hashtext(%s))", ("agent:" + sid,))

    def _reply(self, conn, session, token, text, request_id):
        service, sid = self.service, session["session_id"]
        old = conn.execute("SELECT * FROM agent_turns WHERE session_id=%s AND request_id=%s", (sid, request_id)).fetchone()
        if old:
            if old["request_hash"] != digest(text):
                raise ServiceError("idempotency_conflict", "Request ID already belongs to a different message", 409)
            return old["result"]
        conn.execute("INSERT INTO agent_context(session_id) VALUES(%s) ON CONFLICT DO NOTHING", (sid,))
        memory = conn.execute("SELECT * FROM agent_context WHERE session_id=%s", (sid,)).fetchone()
        if memory["turns"] >= 20 or memory["api_calls"] >= MAX_API_CALLS:
            raise ServiceError("conversation_limit", "This conversation has reached its configured limit", 409)
        memory["turns"] += 1
        conn.commit()
        service.message(token, text, "chat:" + request_id)
        view = service.view(token)["result"]
        for m in view["messages"]:
            if m["sequence"] > memory["message_sequence"]:
                memory["input"].append({"role": "assistant" if m["role"] == "support" else "user", "content": m["content"]})
        with service.repo.connect() as snapshot:
            world, policy = service.repo.world(snapshot, session["world_id"])
        prompt = (Path(__file__).parent / "prompts/agent_v0.1.md").read_text()
        prompt += f"\nToday's date is {world['config']['today']} (IST).\n\n" + policy
        result = None
        try:
            for step in range(12):
                if memory["api_calls"] >= MAX_API_CALLS:
                    raise ServiceError("conversation_limit", "Configured model-call limit reached", 409)
                body = {"model": MODEL, "instructions": prompt, "input": memory["input"], "tools": schemas(),
                        "parallel_tool_calls": False, "reasoning": {"effort": "high"}, "max_output_tokens": 8192,
                        "store": False, "include": ["reasoning.encrypted_content"]}
                memory["api_calls"] += 1
                self._save(conn, memory, sid)
                raw = self.transport(body)
                service._operation(token, "model.response", {"model": MODEL, "turn": memory["turns"], "step": step},
                                   lambda c, s, w, p: {"ok": True, "result": raw})
                if raw.get("status") != "completed":
                    raise ServiceError("model_incomplete", "The agent response was incomplete", 502)
                memory["input"].extend(raw.get("output", []))
                calls = [i for i in raw.get("output", []) if i.get("type") == "function_call"]
                messages = [c["text"] for i in raw.get("output", []) if i.get("type") == "message"
                            for c in i.get("content", []) if c.get("type") == "output_text"]
                pending = None
                for call in calls:
                    try:
                        args = json.loads(call["arguments"])
                        if not isinstance(args, dict):
                            raise ValueError("object required")
                        if call["name"] in {"propose_action", "decide_policy"}:
                            args = {k: v for k, v in args.items() if v is not None}
                            response = service.propose(token, args, call["call_id"]) if call["name"] == "propose_action" else service.decision(token, args)
                            if call["name"] == "propose_action" and response["ok"]:
                                pending = response["result"].get("proposal")
                        else:
                            response = service.tool(token, call["name"], args, call["call_id"])
                    except (ValueError, TypeError):
                        response = ServiceError("invalid_arguments", "Tool arguments must be a JSON object").response()
                    memory["input"].append({"type": "function_call_output", "call_id": call["call_id"], "output": json.dumps(response)})
                if pending:
                    # The canonical server quote is the final agent proposal. A
                    # model cannot paraphrase away its amount/method before approval.
                    memory["input"].append({"role": "assistant", "content": pending["terms"]})
                    result = {"ok": True, "result": {"message": pending["terms"], "proposal": pending}}
                    break
                if not calls:
                    if not messages:
                        raise ServiceError("model_empty", "The agent returned no message", 502)
                    message = "\n".join(messages)
                    def save_message(c, s, w, p):
                        service._message(c, s, w, "support", message)
                        return {"ok": True, "result": {"message": message, "proposal": None}}
                    result = service._operation(token, "agent.message", {"message": message}, save_message)
                    break
            if result is None:
                raise ServiceError("tool_limit", "Agent exceeded the tool-round limit", 502)
        except ServiceError as exc:
            result = exc.response()
            service._operation(token, "model.error", {"code": exc.code}, lambda c, s, w, p: result)
        memory["message_sequence"] = service.view(token)["result"]["messages"][-1]["sequence"]
        self._save(conn, memory, sid)
        conn.execute("INSERT INTO agent_turns VALUES(%s,%s,%s,%s)", (sid, request_id, digest(text), Jsonb(result)))
        conn.commit()
        return result

    def _save(self, conn, memory, sid):
        conn.execute("UPDATE agent_context SET input=%s,message_sequence=%s,turns=%s,api_calls=%s WHERE session_id=%s",
                     (Jsonb(memory["input"]), memory["message_sequence"], memory["turns"], memory["api_calls"], sid))
        conn.commit()
