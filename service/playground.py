"""Shared website fixtures, separate from the frozen evaluation seed."""
import copy
import json
from pathlib import Path

from service.repository import load_seed

ADDITIONS = json.loads((Path(__file__).parent / "demo_data/playground_v1.json").read_text())
DEMOS = {"return": "U018", "cancel": "U014", "delay": "U031",
         **{u["user_id"]: u["user_id"] for u in ADDITIONS["users"]}}


def shared_world_id(configured):
    """Retain the existing live dataset ID; never seed a second base copy."""
    return configured if configured.endswith("-shared-web-v1") else configured + "-shared-web-v1"


def catalog():
    users = {u["user_id"]: u for u in [*load_seed()["users"], *ADDITIONS["users"]]}
    return [{"id": key, "user": uid, "name": users[uid]["name"], "email": users[uid]["email"]}
            for key, uid in DEMOS.items()]


def ensure_playground(repo, world_id):
    """Append once under the same world lock used by financial writes.

    Never restore a modified order or remove an existing refund on restart.
    Audit the inserts so replay still starts from the unchanged original seed.
    """
    repo.seed(world_id)
    with repo.connect() as conn:
        world, _ = repo.world(conn, world_id, lock=True)
        if conn.execute("SELECT 1 FROM audit_events WHERE world_id=%s AND event_type='world.playground_v1'", (world_id,)).fetchone():
            return
        before = copy.deepcopy(world)
        for table, rows in ADDITIONS.items():
            world[table].extend(copy.deepcopy(rows))
        changes = repo.persist(conn, world_id, before, world)
        repo.audit(conn, world_id, None, world["config"]["reference_datetime"], "world.playground_v1",
                   {"customers": 20, "orders": 100}, {"ok": True}, changes)
