"""Service boundary: identity, decisions, customer approval, atomic execution."""
import copy
import secrets
from uuid import uuid4

import psycopg
from psycopg.types.json import Jsonb

from cartly.tools import ACCESS_ERROR, TOOLS, WRITES, ToolError
from service.engine import GuardedEngine
from service.errors import ServiceError
from service.policy import decide, action_arguments, proposal_text
from service.repository import digest


class CartlyService:
    def __init__(self, repository):
        self.repo = repository

    def login(self, world_id, user_id, email=None, phone=None):
        """Demo identity exchange, protected by an operator key at the HTTP layer.

        Registered email/phone matching is the seeded A1 rule, not a real OTP or
        production identity provider. The resulting token is bound to one user.
        """
        with self.repo.connect() as conn:
            world, policy = self.repo.world(conn, world_id, lock=True)
            engine = GuardedEngine(world, policy)
            response = engine.verify_user(user_id=user_id, email=email, phone=phone)
            args = {"user_id": user_id}  # Do not audit passwords/tokens or contact credentials.
            if not response["ok"]:
                self.repo.audit(conn, world_id, None, engine.timestamp, "session.login_failed", args, response, [])
                return response
            sid, token = str(uuid4()), secrets.token_urlsafe(32)
            conn.execute("INSERT INTO sessions(session_id,world_id,principal_id,token_hash,created_at) VALUES(%s,%s,%s,%s,%s)",
                         (sid, world_id, user_id, digest(token), engine.timestamp))
            self.repo.audit(conn, world_id, sid, engine.timestamp, "session.created", args, {"ok": True}, [])
        return {"ok": True, "result": {"session_id": sid, "token": token, "user_id": user_id, "world_id": world_id}}

    def _message(self, conn, session, world, role, content):
        session["revision"] += 1
        sequence = session["revision"]
        conn.execute("INSERT INTO messages(session_id,sequence,role,content,timestamp) VALUES(%s,%s,%s,%s,%s)",
                     (session["session_id"], sequence, role, content, world["config"]["reference_datetime"]))
        conn.execute("UPDATE sessions SET revision=%s WHERE session_id=%s", (sequence, session["session_id"]))
        return sequence

    def _invalidate(self, conn, sid):
        conn.execute("UPDATE proposals SET status='superseded' WHERE session_id=%s AND status IN ('proposed','accepted')", (sid,))

    def _operation(self, token, name, args, callback, key=None):
        if key is not None and (not isinstance(key, str) or not 1 <= len(key) <= 128):
            raise ServiceError("invalid_idempotency_key", "Use a nonempty key up to 128 characters")
        with self.repo.connect() as conn:
            # Lock order is always world -> session. Two conversations share business state.
            session = conn.execute("SELECT * FROM sessions WHERE token_hash=%s AND NOT revoked", (digest(token),)).fetchone()
            if not session:
                raise ServiceError("unauthorized", "Valid session authentication required", 401)
            world, policy = self.repo.world(conn, session["world_id"], lock=True)
            session = conn.execute("SELECT * FROM sessions WHERE session_id=%s FOR UPDATE", (session["session_id"],)).fetchone()
            if session["revoked"]:
                raise ServiceError("unauthorized", "Valid session authentication required", 401)
            sid, wid, timestamp = session["session_id"], session["world_id"], world["config"]["reference_datetime"]
            request_hash = digest({"operation": name, "arguments": args})
            cached = conn.execute("SELECT * FROM idempotency WHERE session_id=%s AND request_key=%s", (sid, key)).fetchone() if key else None
            if cached:
                response = cached["response"] if cached["request_hash"] == request_hash else ServiceError(
                    "idempotency_conflict", "This key was already used for a different request", 409).response()
                self.repo.audit(conn, wid, sid, timestamp, "idempotency.replay", {"operation": name, "key": key}, response, [])
                return response
            before = copy.deepcopy(world)
            try:
                # This savepoint makes audit failures and SQL constraints fail closed.
                with conn.transaction():
                    response = callback(conn, session, world, policy)
                    delta = self.repo.persist(conn, wid, before, world)
            except ServiceError as exc:
                response, delta = exc.response(), []
            except ToolError as exc:
                response, delta = ServiceError("policy_rejected", str(exc)).response(), []
            except psycopg.IntegrityError:
                response, delta = ServiceError("state_conflict", "State changed or database constraint rejected the action", 409).response(), []
            self.repo.audit(conn, wid, sid, timestamp, name, args, response, delta)
            if key:
                conn.execute("INSERT INTO idempotency VALUES(%s,%s,%s,%s)", (sid, key, request_hash, Jsonb(response)))
            return response

    @staticmethod
    def _verified(session):
        if not session["verified_user_id"]:
            raise ServiceError("verification_required", "verification required", 403, ["A1"])
        return session["verified_user_id"]

    def tool(self, token, tool_name, arguments, key=None):
        def call(conn, session, world, policy):
            if tool_name not in TOOLS:
                raise ServiceError("unknown_tool", "Unknown tool")
            if tool_name in WRITES:
                raise ServiceError("confirmation_required", "Use a stored proposal and customer acceptance; confirmed=true alone is not authorization", 409, ["G1", "H5"])
            uid = session["verified_user_id"]
            if tool_name not in {"verify_user", "search_policy", "check_serviceability"}:
                self._verified(session)
            engine = GuardedEngine(world, policy, uid)
            if tool_name == "verify_user" and arguments.get("user_id") != session["principal_id"]:
                conn.execute("UPDATE sessions SET verified_user_id=NULL WHERE session_id=%s", (session["session_id"],))
                return {"ok": False, "error": {"code": "verification_failed", "message": "verification failed", "rules": ["A1"]}}
            response = engine.call(tool_name, **arguments)
            if tool_name == "verify_user":
                conn.execute("UPDATE sessions SET verified_user_id=%s WHERE session_id=%s", (engine.verified_user_id, session["session_id"]))
                self._invalidate(conn, session["session_id"])
            if response["ok"]:
                world.update(engine.state)
            else:
                response["error"].setdefault("code", "tool_rejected")
                response["error"].setdefault("rules", [])
            if tool_name == "escalate_to_human" and response["ok"]:
                response["result"]["status"] = "queued_in_database"
            return response
        safe_args = {k: v for k, v in arguments.items() if k not in {"email", "phone"}}
        if tool_name == "verify_user":
            # Credential values stay out of the audit, but cannot share an
            # idempotency fingerprint with a different verification attempt.
            safe_args["credential_fingerprint"] = digest({k: arguments.get(k) for k in ("email", "phone")})
        return self._operation(token, "tool." + tool_name, {"tool": tool_name, "arguments": safe_args}, call, key)

    def message(self, token, content, key):
        if not isinstance(content, str) or not content.strip() or len(content) > 10000:
            raise ServiceError("invalid_message", "A message of 1–10,000 characters is required")
        def save(conn, session, world, policy):
            self._invalidate(conn, session["session_id"])
            seq = self._message(conn, session, world, "customer", content)
            return {"ok": True, "result": {"sequence": seq, "content": content}}
        return self._operation(token, "customer.message", {"content": content}, save, key)

    def assert_unused(self, token, order_id, item_id, unused, key):
        if type(unused) is not bool:
            raise ServiceError("invalid_assertion", "unused must be a boolean")
        def save(conn, session, world, policy):
            GuardedEngine(world, policy, self._verified(session))._item(order_id, item_id)
            self._invalidate(conn, session["session_id"])
            seq = self._message(conn, session, world, "customer", f"For item {item_id}, I confirm it {'has not' if unused else 'has'} been used.")
            session["facts"][item_id] = {"unused": unused, "message_sequence": seq, "source": "customer"}
            conn.execute("UPDATE sessions SET facts=%s WHERE session_id=%s", (Jsonb(session["facts"]), session["session_id"]))
            return {"ok": True, "result": {"item_id": item_id, "condition_recorded": True}}
        return self._operation(token, "customer.condition", {"order_id": order_id, "item_id": item_id, "unused": unused}, save, key)

    def decision(self, token, request):
        return self._operation(token, "policy.decide", request, lambda conn, session, world, policy:
                               {"ok": True, "result": decide(world, policy, self._verified(session), request, session["facts"])})

    def propose(self, token, request, key):
        def create(conn, session, world, policy):
            decision = decide(world, policy, self._verified(session), request, session["facts"])
            if not decision["action"]:
                return {"ok": True, "result": {"decision": decision, "proposal": None}}
            self._invalidate(conn, session["session_id"])
            terms = proposal_text(decision)
            sequence = self._message(conn, session, world, "support", terms)
            proposal_id = str(uuid4())
            conn.execute("INSERT INTO proposals(proposal_id,session_id,request,decision,terms,terms_hash,proposal_sequence,status,created_at) VALUES(%s,%s,%s,%s,%s,%s,%s,'proposed',%s)",
                         (proposal_id, session["session_id"], Jsonb(request), Jsonb(decision), terms, digest(terms), sequence, world["config"]["reference_datetime"]))
            return {"ok": True, "result": {"decision": decision, "proposal": {"proposal_id": proposal_id,
                    "status": "proposed", "terms": terms, "terms_hash": digest(terms)}}}
        return self._operation(token, "proposal.create", request, create, key)

    def _proposal(self, conn, session, proposal_id):
        proposal = conn.execute("SELECT * FROM proposals WHERE proposal_id=%s AND session_id=%s FOR UPDATE", (proposal_id, session["session_id"])).fetchone()
        if not proposal:
            raise ServiceError("not_available", "Proposal unavailable for this session", 404)
        return proposal

    def accept(self, token, proposal_id, terms_hash, accept, key):
        """Customer-only structured control. Never exposed as an agent tool.

        A plain chat message (including 'yes') grants no permission. The customer
        explicitly accepts the displayed terms, or changes the request in chat.
        """
        if type(accept) is not bool:
            raise ServiceError("invalid_acceptance", "accept must be a boolean")
        def record(conn, session, world, policy):
            self._verified(session)
            p = self._proposal(conn, session, proposal_id)
            if p["status"] != "proposed" or p["proposal_sequence"] != session["revision"]:
                raise ServiceError("stale_confirmation", "Please review a new proposal before agreeing", 409, ["H5"])
            if not secrets.compare_digest(terms_hash, p["terms_hash"]):
                raise ServiceError("terms_changed", "The accepted terms do not match the displayed proposal", 409)
            reply = ("Yes, I agree to this exact proposal: " if accept else "No, I decline: ") + p["terms"]
            sequence = self._message(conn, session, world, "customer", reply)
            status = "accepted" if accept else "rejected"
            conn.execute("UPDATE proposals SET status=%s,acceptance_sequence=%s WHERE proposal_id=%s", (status, sequence, proposal_id))
            return {"ok": True, "result": {"proposal_id": proposal_id, "status": status}}
        return self._operation(token, "customer.acceptance", {"proposal_id": proposal_id, "terms_hash": terms_hash, "accept": accept}, record, key)

    def execute(self, token, proposal_id, key):
        def execute(conn, session, world, policy):
            uid = self._verified(session)
            p = self._proposal(conn, session, proposal_id)
            if p["status"] == "executed":
                return {"ok": True, "result": p["result"], "replayed": True}
            if p["status"] != "accepted" or p["acceptance_sequence"] != session["revision"]:
                raise ServiceError("confirmation_required", "Customer must accept the current proposal first", 409, ["G1", "H5"])
            current = decide(world, policy, uid, p["request"], session["facts"])
            if current != p["decision"]:
                conn.execute("UPDATE proposals SET status='stale' WHERE proposal_id=%s", (proposal_id,))
                return ServiceError("proposal_changed", "Eligibility or refund terms changed. Review a new proposal", 409, current["rules"]).response()
            engine = GuardedEngine(world, policy, uid)
            response = engine.call(current["action"], **action_arguments(current, p["request"]))
            if not response["ok"]:
                return response
            world.update(engine.state)
            conn.execute("UPDATE proposals SET status='executed',result=%s WHERE proposal_id=%s", (Jsonb(response["result"]), proposal_id))
            self._message(conn, session, world, "support", "Completed: " + p["terms"].removesuffix(" Do you agree?"))
            return response
        return self._operation(token, "action.execute", {"proposal_id": proposal_id}, execute, key)

    def pickup(self, token, return_id, key):
        """Operator/system event only; absent from the agent's tool registry."""
        def complete(conn, session, world, policy):
            engine = GuardedEngine(world, policy, self._verified(session))
            result = engine.complete_pickup(return_id)
            if result["ok"]:
                world.update(engine.state)
            return result
        return self._operation(token, "system.pickup", {"return_id": return_id}, complete, key)

    def view(self, token):
        def view(conn, session, world, policy):
            rows = conn.execute("SELECT sequence,role,content,timestamp FROM messages WHERE session_id=%s ORDER BY sequence", (session["session_id"],)).fetchall()
            proposals = conn.execute("SELECT proposal_id,status,terms,terms_hash,decision,result FROM proposals WHERE session_id=%s ORDER BY proposal_sequence", (session["session_id"],)).fetchall()
            return {"ok": True, "result": {"session_id": session["session_id"], "verified_user_id": session["verified_user_id"],
                    "reference_date": world["config"]["today"], "messages": rows, "proposals": proposals}}
        return self._operation(token, "session.view", {}, view)
