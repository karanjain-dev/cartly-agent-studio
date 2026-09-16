from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Event
from uuid import uuid4

import pytest

from service.agent import MODEL
from service.budget import BudgetedTransport
from service.errors import ServiceError
from service.production import application

BODY = {"model": MODEL, "max_output_tokens": 8192, "input": "hello"}
RAW = {"usage": {"input_tokens": 100, "output_tokens": 10}}


def test_budget_survives_reconstruction_and_charges_usage(repo):
    key = str(uuid4())
    t = BudgetedTransport(repo, lambda _: RAW, initial_spent="1", budget_id=key)
    assert t(BODY) == RAW
    BudgetedTransport(repo, lambda _: RAW, initial_spent="0", budget_id=key)
    with repo.connect() as c:
        row = c.execute("SELECT * FROM api_budgets WHERE budget_id=%s", (key,)).fetchone()
    assert row["spent_usd"] == Decimal("1.0015")
    BudgetedTransport(repo, lambda _: RAW, initial_spent="1.2", budget_id=key)
    with repo.connect() as c:
        row = c.execute("SELECT * FROM api_budgets WHERE budget_id=%s", (key,)).fetchone()
    assert row["spent_usd"] == Decimal("1.2015")


def test_unknown_failure_retains_reservation(repo):
    key = str(uuid4())
    def broken(_):
        raise ServiceError("network", "Unavailable", 502)
    t = BudgetedTransport(repo, broken, limit="0.5", budget_id=key)
    with pytest.raises(ServiceError, match="Unavailable"):
        t(BODY)
    with pytest.raises(ServiceError, match="allowance"):
        t(BODY)


def test_concurrent_calls_cannot_oversubscribe(repo):
    started, release = Event(), Event()
    def slow(_):
        started.set()
        assert release.wait(10)
        return RAW
    t = BudgetedTransport(repo, slow, limit="0.5", budget_id=str(uuid4()))
    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(t, BODY)
        assert started.wait(5)
        try:
            with pytest.raises(ServiceError, match="allowance"):
                t(BODY)
        finally:
            release.set()
        assert first.result() == RAW


def test_production_has_no_local_secret_or_database_fallback(monkeypatch):
    for name in ("CARTLY_DATABASE_URL", "CARTLY_SERVICE_KEY", "OPENAI_API_KEY", "CARTLY_INITIAL_SPENT_USD"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(RuntimeError, match="Missing production configuration"):
        application()
