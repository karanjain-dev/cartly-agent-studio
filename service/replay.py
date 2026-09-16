"""Replay saved committed changes. No models, new actions, or business writes."""
import copy

from service.repository import TABLES, digest, load_seed


def replay(repository, world_id, seed=None):
    chain = repository.verify_audit(world_id)
    state = copy.deepcopy(seed if seed is not None else load_seed())
    failures = []
    events, mutations = 0, 0
    with repository.connect() as conn:
        actual, policy = repository.world(conn, world_id, lock=True)
        meta = conn.execute("SELECT source_hash FROM worlds WHERE world_id=%s", (world_id,)).fetchone()
        if digest({"world": state, "policy": policy}) != meta["source_hash"]:
            failures.append("Replay seed does not match the world's original seed hash")
        rows = conn.execute("SELECT * FROM audit_events WHERE world_id=%s ORDER BY event_id", (world_id,)).fetchall()
        for event in rows:
            events += 1
            for change in event["changes"]:
                mutations += 1
                table = change["table"]
                pk = TABLES[table][0]
                key = change["key"][pk]
                old = next((r for r in state[table] if r[pk] == key), None)
                if old != change["before"]:
                    failures.append(f"Before-state mismatch at event {event['event_id']}: {table}/{key}")
                if old is None:
                    state[table].append(change["after"])
                else:
                    state[table][state[table].index(old)] = change["after"]
    for table, fields in TABLES.items():
        if sorted(state[table], key=lambda r: r[fields[0]]) != sorted(actual[table], key=lambda r: r[fields[0]]):
            failures.append("Final state differs in " + table)
    return {"pass": chain["pass"] and not failures, "world_id": world_id,
            "audit_chain": chain, "events": events, "database_changes": mutations, "failures": failures,
            "scope": "Replays committed database changes and audit integrity; not a conversation-quality grade"}
