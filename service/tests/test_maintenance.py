from uuid import uuid4

import psycopg
import pytest

from service.approval_flow import CartlyService
from service.maintenance import export_backup, prune, records, restore_to_empty_schema
from service.playground import ensure_playground, shared_world_id
from service.repository import Repository
from service.tests.conftest import approve, login


@pytest.fixture
def maintenance_db(repo):
    isolated = Repository(repo.dsn, 'cartly_maintenance_' + uuid4().hex)
    isolated.migrate()
    isolated.seed('production-demo')
    return isolated, 'production-demo', CartlyService(isolated)


def test_cleanup_backup_restore_and_active_refund_preservation(maintenance_db):
    repo, old, s = maintenance_db
    active = shared_world_id(old)
    ensure_playground(repo, active)
    token = login(s, active, 'U104')
    pid = approve(s, token, {'intent': 'return', 'order_id': 'O1005', 'item_id': 'I1006', 'reason': 'wrong_item'})
    assert s.execute(token, pid, 'execute')['ok']
    old_token = login(s, old)
    s.message(old_token, 'An old private conversation', 'old-message')
    with repo.connect() as conn:
        conn.execute("INSERT INTO api_budgets VALUES ('test',3,1,0)")
    backup = export_backup(repo, active)
    restored = Repository(repo.dsn, 'cartly_restore_' + uuid4().hex)
    restore_to_empty_schema(restored, backup)
    assert restored.verify_audit(old)['pass'] and restored.verify_audit(active)['pass']
    before = repo.snapshot(active)
    report = prune(repo, active, backup['retired_hash'], backup['data_hash'])
    assert old in report['removed_worlds'] and report['deleted']['users'] >= 54
    assert repo.snapshot(active) == before
    assert repo.verify_audit(active)['pass']
    assert s.view(token)['ok']  # Current conversation token still works.
    with pytest.raises(Exception):
        s.view(old_token)
    with repo.connect() as conn:
        assert conn.execute('SELECT count(*) AS n FROM worlds').fetchone()['n'] == 1
        assert conn.execute('SELECT count(*) AS n FROM users').fetchone()['n'] == 74
        assert str(conn.execute("SELECT spent_usd FROM api_budgets WHERE budget_id='test'").fetchone()['spent_usd']) == '1'
        with pytest.raises(psycopg.Error):
            conn.execute('DELETE FROM audit_events')


def test_cleanup_refuses_stale_backup_and_unknown_world(maintenance_db):
    repo, old, s = maintenance_db
    active = shared_world_id(old)
    ensure_playground(repo, active)
    backup = export_backup(repo, active)
    t = login(s, old)
    s.message(t, 'Changed after export', 'changed')
    with pytest.raises(ValueError, match='changed since backup'):
        prune(repo, active, backup['retired_hash'], backup['data_hash'])
    assert repo.snapshot(old)
    repo.seed('unrecognized-dataset')
    with pytest.raises(ValueError, match='unrecognized'):
        export_backup(repo, active)


def test_shared_world_resolution_is_idempotent():
    active = 'production-demo-shared-web-v1'
    assert shared_world_id('production-demo') == active
    assert shared_world_id(active) == active
