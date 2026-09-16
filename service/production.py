"""Host entrypoint: external PostgreSQL and explicit secrets; no laptop fallback."""
import os

from service.agent import OpenAITransport
from service.api import create_app
from service.budget import BudgetedTransport
from service.repository import Repository


def application():
    required = ("CARTLY_DATABASE_URL", "CARTLY_SERVICE_KEY", "OPENAI_API_KEY", "CARTLY_INITIAL_SPENT_USD")
    missing = [key for key in required if not os.environ.get(key)]
    if missing:
        raise RuntimeError("Missing production configuration: " + ", ".join(missing))
    if len(os.environ["CARTLY_SERVICE_KEY"]) < 32:
        raise RuntimeError("CARTLY_SERVICE_KEY must have at least 32 characters")
    repo = Repository(os.environ["CARTLY_DATABASE_URL"])
    repo.migrate()
    world = os.environ.get("CARTLY_WORLD", "production-demo")
    repo.seed(world)
    transport = BudgetedTransport(repo, OpenAITransport(os.environ["OPENAI_API_KEY"]),
        limit=os.environ.get("CARTLY_API_BUDGET_USD", "3"), initial_spent=os.environ["CARTLY_INITIAL_SPENT_USD"])
    return create_app(repo, os.environ["CARTLY_SERVICE_KEY"], world, transport)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(application(), host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
