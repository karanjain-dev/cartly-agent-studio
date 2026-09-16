"""Persisted, shared API allowance. Uncertain calls keep their reservation."""
import json
from decimal import Decimal
from uuid import uuid4

from psycopg.types.json import Jsonb

from service.agent import MODEL
from service.errors import ServiceError

D = Decimal


def usage_cost(usage):
    details = usage.get("input_tokens_details", {})
    inputs, outputs = usage["input_tokens"], usage["output_tokens"]
    cached = details.get("cached_tokens", 0)
    written = details.get("cache_creation_tokens", details.get("cache_write_tokens", 0))
    if any(not isinstance(v, int) or v < 0 for v in (inputs, outputs, cached, written)) or cached + written > inputs:
        raise ValueError("Invalid model usage")
    return (D(inputs-cached-written)*10 + D(cached) + D(written)*D("12.5") + D(outputs)*50)/1_000_000


class BudgetedTransport:
    def __init__(self, repo, transport, limit="3", initial_spent="0", budget_id="public-demo"):
        self.repo, self.transport, self.id = repo, transport, budget_id
        limit, spent = D(limit), D(initial_spent)
        if not limit.is_finite() or not spent.is_finite() or limit < 0 or spent < 0:
            raise ValueError("Budget values must be finite and non-negative")
        with repo.connect() as conn:
            conn.execute("INSERT INTO api_budgets VALUES (%s,%s,%s) ON CONFLICT DO NOTHING", (budget_id, limit, spent))
            row = conn.execute("SELECT * FROM api_budgets WHERE budget_id=%s", (budget_id,)).fetchone()
            if row["limit_usd"] != limit:
                raise ValueError("Stored budget differs from configuration; reconcile explicitly rather than resetting spending")

    def __call__(self, body):
        # Conservative UTF-8 byte upper bound plus protocol allowance; reserve
        # the maximum output too. This can stop early, never silently renews.
        input_bound = len(json.dumps(body, ensure_ascii=False).encode()) + 4096
        output_bound = body.get("max_output_tokens")
        if body.get("model") != MODEL or input_bound > 272000 or not isinstance(output_bound, int) or not 0 < output_bound <= 8192:
            raise ServiceError("budget_request_limit", "Request exceeds the demo's configured model limits", 409)
        reserve = (D(input_bound)*D("12.5") + D(output_bound)*50)/1_000_000
        rid = str(uuid4())
        with self.repo.connect() as conn:
            budget = conn.execute("SELECT * FROM api_budgets WHERE budget_id=%s FOR UPDATE", (self.id,)).fetchone()
            pending = conn.execute("SELECT COALESCE(sum(reserved_usd),0) AS total FROM api_reservations WHERE budget_id=%s AND status='pending'", (self.id,)).fetchone()["total"]
            if budget["spent_usd"] + pending + reserve > budget["limit_usd"]:
                raise ServiceError("budget_exhausted", "The shared demo API allowance cannot cover another reply. Saved conversations remain available.", 503)
            conn.execute("INSERT INTO api_reservations(reservation_id,budget_id,reserved_usd,status) VALUES (%s,%s,%s,'pending')", (rid, self.id, reserve))
        raw = self.transport(body)  # Network/process failure deliberately retains reservation.
        try:
            actual = usage_cost(raw["usage"])
        except (KeyError, ValueError, TypeError):
            raise ServiceError("usage_unavailable", "Model usage could not be reconciled; its allowance remains reserved", 502) from None
        with self.repo.connect() as conn:
            conn.execute("SELECT * FROM api_budgets WHERE budget_id=%s FOR UPDATE", (self.id,))
            conn.execute("UPDATE api_budgets SET spent_usd=spent_usd+%s WHERE budget_id=%s", (actual, self.id))
            conn.execute("UPDATE api_reservations SET status='completed',actual_usd=%s,usage=%s WHERE reservation_id=%s", (actual, Jsonb(raw["usage"]), rid))
        return raw
