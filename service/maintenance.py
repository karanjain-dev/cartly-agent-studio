"""Offline administrator cleanup, never exposed as an agent tool or HTTP route.

Export a complete logical backup first. Pruning requires the exact retired-state
fingerprint from that backup and retains the active world and all budget records.
"""
import argparse
import base64
import gzip
import json
import os

from psycopg import sql
from psycopg.types.json import Jsonb

from service.repository import Repository, canonical, digest

TABLE_ORDER = ["worlds", "users", "orders", "order_items", "refunds", "returns", "pincodes",
               "coupons", "escalations", "sessions", "messages", "proposals", "idempotency",
               "audit_events", "agent_context", "agent_turns", "api_budgets", "api_reservations",
               "schema_migrations"]
GLOBAL = {"api_budgets", "api_reservations", "schema_migrations"}


def records(conn):
    tables = {r["tablename"] for r in conn.execute(
        "SELECT tablename FROM pg_tables WHERE schemaname=current_schema()")}
    if tables != set(TABLE_ORDER):
        raise ValueError("Unexpected database tables; review the cleanup before proceeding")
    result = {}
    for table in TABLE_ORDER:
        rows = conn.execute(sql.SQL("SELECT * FROM {}").format(sql.Identifier(table))).fetchall()
        result[table] = sorted(json.loads(json.dumps(rows, default=str)), key=canonical)
    return result


def partition(data, keep_world):
    if not any(w["world_id"] == keep_world for w in data["worlds"]):
        raise ValueError("The shared world must exist; refusing cleanup")
    retired = {w["world_id"] for w in data["worlds"] if w["world_id"] != keep_world}
    # Production cleanup is restricted to the known retired demo naming scheme.
    if any(not (w.startswith("web-") or w == keep_world.removesuffix("-shared-web-v1")) for w in retired):
        raise ValueError("An unrecognized dataset exists; inventory and review it first")
    session_ids = {s["session_id"] for s in data["sessions"] if s["world_id"] in retired}
    removed = {t: [r for r in rows if r.get("world_id") in retired or r.get("session_id") in session_ids]
               for t, rows in data.items() if t not in GLOBAL}
    return retired, removed


def export_backup(repo, keep_world):
    with repo.connect() as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        data = records(conn)
    retired, removed = partition(data, keep_world)
    return {"format": "cartly-logical-backup-v1", "schema": repo.schema, "keep_world": keep_world,
            "retired_worlds": sorted(retired), "retired_hash": digest(removed), "data": data,
            "data_hash": digest(data)}


def prune(repo, keep_world, retired_hash, backup_hash):
    if not backup_hash or len(backup_hash) != 64:
        raise ValueError("A verified backup checksum is required")
    with repo.connect() as conn:
        conn.execute("SET LOCAL lock_timeout='10s'")
        conn.execute(sql.SQL("LOCK TABLE {} IN ACCESS EXCLUSIVE MODE").format(
            sql.SQL(",").join(map(sql.Identifier, TABLE_ORDER))))
        before = records(conn)
        retired, removed = partition(before, keep_world)
        if digest(removed) != retired_hash:
            raise ValueError("Retired records changed since backup; export and verify a fresh backup")
        active = {t: [r for r in rows if r not in removed.get(t, [])] for t, rows in before.items()}
        if not retired:
            return {"removed_worlds": [], "deleted": {}}
        session_ids = [s["session_id"] for s in removed["sessions"]]
        # Temporarily relax append-only audit protection only inside this locked
        # admin transaction. A rollback restores both records and the trigger.
        conn.execute("ALTER TABLE audit_events DISABLE TRIGGER immutable_audit")
        for table in ["audit_events", "agent_turns", "agent_context", "idempotency", "proposals", "messages",
                      "sessions", "coupons", "escalations", "returns", "refunds", "order_items", "orders",
                      "users", "pincodes", "worlds"]:
            column, values = ("session_id", session_ids) if table in {
                "agent_turns", "agent_context", "idempotency", "proposals", "messages"} else ("world_id", list(retired))
            conn.execute(sql.SQL("DELETE FROM {} WHERE {} = ANY(%s)").format(
                sql.Identifier(table), sql.Identifier(column)), (values,))
        conn.execute("ALTER TABLE audit_events ENABLE TRIGGER immutable_audit")
        if records(conn) != active:
            raise ValueError("Protected state changed; cleanup rolled back")
        timestamp = next(w for w in active["worlds"] if w["world_id"] == keep_world)["config"]["reference_datetime"]
        summary = {"removed_worlds": sorted(retired), "deleted": {t: len(r) for t, r in removed.items()},
                   "kept": {t: len(r) for t, r in active.items()}, "backup_sha256": backup_hash}
        repo.audit(conn, keep_world, None, timestamp, "admin.retired_demo_cleanup",
                   {"retired_hash": retired_hash, "backup_sha256": backup_hash}, {"ok": True, "result": summary}, [])
        return summary


def restore_to_empty_schema(repo, backup):
    """Restore-test helper; refuses any schema that already contains worlds."""
    if digest(backup["data"]) != backup["data_hash"]:
        raise ValueError("Backup checksum mismatch")
    repo.migrate()
    with repo.connect() as conn:
        if conn.execute("SELECT 1 FROM worlds LIMIT 1").fetchone():
            raise ValueError("Restore requires an empty schema")
        json_columns = {(r["table_name"], r["column_name"]) for r in conn.execute(
            "SELECT table_name,column_name FROM information_schema.columns WHERE table_schema=current_schema() AND data_type='jsonb'")}
        for table in TABLE_ORDER:
            if table == "schema_migrations":
                continue
            for row in backup["data"][table]:
                cols = list(row)
                values = [Jsonb(row[k]) if (table, k) in json_columns else row[k] for k in cols]
                conn.execute(sql.SQL("INSERT INTO {} ({}) OVERRIDING SYSTEM VALUE VALUES ({})").format(
                    sql.Identifier(table), sql.SQL(",").join(map(sql.Identifier, cols)),
                    sql.SQL(",").join(sql.Placeholder() for _ in cols)), values)
        for table, column in [("messages", "message_id"), ("audit_events", "event_id")]:
            conn.execute(sql.SQL("SELECT setval(pg_get_serial_sequence(%s,%s), COALESCE(MAX({}),1), MAX({}) IS NOT NULL) FROM {}").format(
                sql.Identifier(column), sql.Identifier(column), sql.Identifier(table)), (table, column))
        if records(conn) != backup["data"]:
            raise ValueError("Restored data differs; restore rolled back")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["export", "prune"])
    parser.add_argument("--keep-world", required=True)
    parser.add_argument("--retired-hash")
    parser.add_argument("--backup-sha256")
    args = parser.parse_args()
    repo = Repository(os.environ["CARTLY_DATABASE_URL"])
    if args.command == "export":
        payload = gzip.compress(canonical(export_backup(repo, args.keep_world)).encode(), mtime=0)
        print("CARTLY_BACKUP:" + base64.b64encode(payload).decode())
    else:
        print(json.dumps(prune(repo, args.keep_world, args.retired_hash, args.backup_sha256)))


if __name__ == "__main__":
    main()
