import os
from uuid import uuid4

import pytest

from service.core import CartlyService
from service.repository import Repository, load_seed


@pytest.fixture(scope="session")
def repo(tmp_path_factory):
    dsn = os.environ.get("CARTLY_TEST_DATABASE_URL")
    handle = None
    if not dsn:
        import pgserver
        handle = pgserver.get_server(tmp_path_factory.mktemp("postgres"), cleanup_mode="stop")
        dsn = handle.get_uri()
    repository = Repository(dsn, "cartly_test_" + uuid4().hex)
    repository.migrate()
    yield repository
    if handle:
        handle.cleanup()


@pytest.fixture
def sandbox(repo):
    world_id = "test-" + uuid4().hex
    repo.seed(world_id)
    return world_id, CartlyService(repo)


def login(service, wid, uid="U018", verified=True):
    user = next(u for u in load_seed()["users"] if u["user_id"] == uid)
    r = service.login(wid, uid, email=user["email"])
    assert r["ok"], r
    token = r["result"]["token"]
    if verified:
        assert service.tool(token, "verify_user", {"user_id": uid, "email": user["email"]})["ok"]
    return token


def approve(service, token, request):
    response = service.propose(token, request, str(uuid4()))
    assert response["ok"], response
    p = response["result"]["proposal"]
    assert p, response
    assert service.accept(token, p["proposal_id"], p["terms_hash"], True, str(uuid4()))["ok"]
    return p["proposal_id"]
