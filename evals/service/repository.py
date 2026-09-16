"""PostgreSQL repository with relational constraints and atomic audit writes.

JSONB record columns preserve all fixture fields without losing optional data.
Identity/ownership columns, foreign keys and financial unique indexes are SQL.
One world lock serializes v0.1 mutations, including cross-order refund history.
"""
import copy
import hashlib
import json
import re
from contextlib import contextmanager
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from cartly.tools import public_value, read_runtime_file
from service.errors import ServiceError

ROOT = Path(__file__).resolve().parents[1]
TABLES = {
    "users": ("user_id", "email", "phone"),
    "orders": ("order_id", "user_id"),
    "order_items": ("item_id", "order_id"),
    "refunds": ("refund_id", "order_id", "item_id", "user_id"),
    "returns": ("return_id", "order_id", "item_id"),
    "coupons": ("coupon_id", "order_id", "user_id"),
    "escalations": ("escalation_id", "user_id"),
}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def load_seed(data_dir=None):
    folder = Path(data_dir or ROOT / "data")
    world = {k: json.loads(read_runtime_file(folder / f"{k}.json")) for k in
             ["config", "users", "orders", "order_items", "refunds", "returns", "serviceable_pincodes"]}
    world.update(coupons=[], escalations=[])
    return public_value(world)


def diff(before, after):
    result = []
    for table, fields in TABLES.items():
        key = fields[0]
        previous = {r[key]: r for r in before[table]}
        current = {r[key]: r for r in after[table]}
        if previous.keys() - current.keys():
            raise ServiceError("invalid_transition", "Business row deletion is not permitted")
        for identifier, row in current.items():
            old = previous.get(identifier)
            if old == row:
                continue
            result.append({"table": table, "operation": "insert" if old is None else "update",
                           "key": {key: identifier}, "before": old, "after": row})
    return result


class Repository:
    def __init__(self, dsn, schema="cartly_service"):
        if not re.fullmatch(r"cartly_[a-z0-9_]+", schema):
            raise ValueError("Schema must be a cartly_ prefixed identifier")
        self.dsn, self.schema = dsn, schema

    @contextmanager
    def connect(self):
        with psycopg.connect(self.dsn, row_factory=dict_row, connect_timeout=10) as connection:
            connection.execute(sql.SQL("SET search_path TO {}, pg_catalog").format(sql.Identifier(self.schema)))
            yield connection

    def migrate(self):
        with self.connect() as conn:
            conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (self.schema + ":migrations",))
            conn.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(self.schema)))
            conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version text PRIMARY KEY, checksum text NOT NULL)")
            for migration in sorted((Path(__file__).parent / "migrations").glob("*.sql")):
                checksum = hashlib.sha256(migration.read_bytes()).hexdigest()
                row = conn.execute("SELECT checksum FROM schema_migrations WHERE version=%s", (migration.name,)).fetchone()
                if row:
                    if row["checksum"] != checksum:
                        raise ServiceError("migration_changed", "Applied migration checksum differs; add a new migration")
                    continue
                conn.execute(migration.read_text(), prepare=False)
                conn.execute("INSERT INTO schema_migrations VALUES (%s,%s)", (migration.name, checksum))

    def seed(self, world_id, world=None, policy=None):
        world = copy.deepcopy(world if world is not None else load_seed())
        policy = policy if policy is not None else read_runtime_file(ROOT / "policy.md")
        source_hash = digest({"world": world, "policy": policy})
        with self.connect() as conn:
            conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (self.schema + ":seed:" + world_id,))
            old = conn.execute("SELECT source_hash FROM worlds WHERE world_id=%s", (world_id,)).fetchone()
            if old:
                if old["source_hash"] != source_hash:
                    raise ServiceError("seed_conflict", "This sandbox already has different seed data; create a new sandbox", 409)
                return {"world_id": world_id, "created": False}
            conn.execute("INSERT INTO worlds(world_id,config,coverage,policy_text,source_hash) VALUES(%s,%s,%s,%s,%s)",
                         (world_id, Jsonb(world["config"]), Jsonb(world["serviceable_pincodes"]), policy, source_hash))
            for table in TABLES:
                for row in world[table]:
                    self.write_row(conn, world_id, table, row)
            for kind, value in [("serviceable_pincodes", True), ("unserviceable_pincodes", False)]:
                for pincode in world["serviceable_pincodes"].get(kind, []):
                    conn.execute("INSERT INTO pincodes VALUES (%s,%s,%s)", (world_id, pincode, value))
            self.audit(conn, world_id, None, world["config"]["reference_datetime"], "world.seed",
                       {"source_hash": source_hash}, {"ok": True}, [])
        return {"world_id": world_id, "created": True}

    def write_row(self, conn, world_id, table, row, update=False):
        fields = TABLES[table]
        if update:
            conn.execute(sql.SQL("UPDATE {} SET record=%s WHERE world_id=%s AND {}=%s").format(
                sql.Identifier(table), sql.Identifier(fields[0])), (Jsonb(row), world_id, row[fields[0]]))
        else:
            columns = ["world_id", *fields, "record"]
            conn.execute(sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
                sql.Identifier(table), sql.SQL(",").join(map(sql.Identifier, columns)),
                sql.SQL(",").join(sql.Placeholder() for _ in columns)),
                [world_id, *(row.get(f) for f in fields), Jsonb(row)])

    def world(self, conn, world_id, lock=False):
        row = conn.execute("SELECT * FROM worlds WHERE world_id=%s" + (" FOR UPDATE" if lock else ""), (world_id,)).fetchone()
        if not row:
            raise ServiceError("not_available", "Sandbox unavailable", 404)
        world = {"config": row["config"], "serviceable_pincodes": row["coverage"]}
        for table, fields in TABLES.items():
            rows = conn.execute(sql.SQL("SELECT record FROM {} WHERE world_id=%s ORDER BY {}").format(
                sql.Identifier(table), sql.Identifier(fields[0])), (world_id,)).fetchall()
            world[table] = [r["record"] for r in rows]
        return world, row["policy_text"]

    def persist(self, conn, world_id, before, after):
        delta = diff(before, after)
        for event in delta:
            self.write_row(conn, world_id, event["table"], event["after"], event["operation"] == "update")
        if delta:
            conn.execute("UPDATE worlds SET revision=revision+1 WHERE world_id=%s", (world_id,))
        return delta

    def audit(self, conn, world_id, session_id, timestamp, event_type, arguments, result, changes):
        old = conn.execute("SELECT event_hash FROM audit_events WHERE world_id=%s ORDER BY event_id DESC LIMIT 1", (world_id,)).fetchone()
        previous = old["event_hash"] if old else "0" * 64
        payload = {"world_id": world_id, "session_id": session_id, "timestamp": timestamp,
                   "event_type": event_type, "arguments": arguments, "result": result,
                   "changes": changes, "previous_hash": previous}
        conn.execute("INSERT INTO audit_events(world_id,session_id,timestamp,event_type,arguments,result,changes,previous_hash,event_hash) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                     (world_id, session_id, timestamp, event_type, Jsonb(arguments), Jsonb(result), Jsonb(changes), previous, digest(payload)))

    def snapshot(self, world_id):
        with self.connect() as conn:
            return self.world(conn, world_id, lock=True)[0]

    def verify_audit(self, world_id):
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM audit_events WHERE world_id=%s ORDER BY event_id", (world_id,)).fetchall()
        previous = "0" * 64
        for row in rows:
            row = dict(row)
            row.pop("event_id")
            actual = row.pop("event_hash")
            if row["previous_hash"] != previous or digest(row) != actual:
                return {"pass": False, "events": len(rows), "reason": "Audit chain differs"}
            previous = actual
        return {"pass": True, "events": len(rows)}
