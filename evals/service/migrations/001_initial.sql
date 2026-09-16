-- All business times are supplied by config, never DEFAULT now().
CREATE TABLE IF NOT EXISTS schema_migrations (version text PRIMARY KEY, checksum text NOT NULL);
CREATE TABLE worlds (
    world_id text PRIMARY KEY,
    config jsonb NOT NULL,
    coverage jsonb NOT NULL,
    policy_text text NOT NULL,
    source_hash text NOT NULL,
    revision bigint NOT NULL DEFAULT 0
);
CREATE TABLE users (
    world_id text NOT NULL REFERENCES worlds,
    user_id text NOT NULL,
    email text NOT NULL,
    phone text NOT NULL,
    record jsonb NOT NULL,
    PRIMARY KEY (world_id, user_id),
    UNIQUE (world_id, email), UNIQUE (world_id, phone),
    CHECK (record->>'user_id' = user_id)
);
CREATE TABLE orders (
    world_id text NOT NULL,
    order_id text NOT NULL,
    user_id text NOT NULL,
    record jsonb NOT NULL,
    PRIMARY KEY (world_id, order_id),
    UNIQUE (world_id, order_id, user_id),
    FOREIGN KEY (world_id, user_id) REFERENCES users,
    CHECK (record->>'order_id' = order_id AND record->>'user_id' = user_id),
    CHECK (record->>'status' IN ('Placed','Packed','Shipped','Out for delivery','Delivered','Cancelled','Returned'))
);
CREATE TABLE order_items (
    world_id text NOT NULL,
    item_id text NOT NULL,
    order_id text NOT NULL,
    record jsonb NOT NULL,
    PRIMARY KEY (world_id, item_id), UNIQUE (world_id, order_id, item_id),
    FOREIGN KEY (world_id, order_id) REFERENCES orders,
    CHECK (record->>'item_id' = item_id AND record->>'order_id' = order_id),
    CHECK ((record->>'price')::numeric >= 0 AND (record->>'quantity')::integer > 0)
);
CREATE TABLE refunds (
    world_id text NOT NULL,
    refund_id text NOT NULL,
    order_id text NOT NULL,
    item_id text,
    user_id text NOT NULL,
    record jsonb NOT NULL,
    PRIMARY KEY (world_id, refund_id),
    FOREIGN KEY (world_id, order_id, user_id) REFERENCES orders(world_id, order_id, user_id),
    FOREIGN KEY (world_id, order_id, item_id) REFERENCES order_items(world_id, order_id, item_id),
    CHECK (record->>'refund_id' = refund_id AND record->>'order_id' = order_id AND record->>'user_id' = user_id),
    CHECK ((record->>'item_id') IS NOT DISTINCT FROM item_id),
    CHECK ((record->>'amount')::numeric >= 0)
);
CREATE UNIQUE INDEX one_completed_refund_per_item ON refunds(world_id,item_id)
    WHERE record->>'status' = 'completed' AND item_id IS NOT NULL;
CREATE UNIQUE INDEX shipping_once ON refunds(world_id,order_id)
    WHERE record->>'status' = 'completed' AND (record->>'shipping_refunded')::boolean;
CREATE UNIQUE INDEX cancellation_once ON refunds(world_id,order_id)
    WHERE record->>'status' = 'completed' AND record->>'reason' = 'cancellation';
CREATE TABLE returns (
    world_id text NOT NULL,
    return_id text NOT NULL,
    order_id text NOT NULL,
    item_id text NOT NULL,
    record jsonb NOT NULL,
    PRIMARY KEY(world_id,return_id), UNIQUE(world_id,item_id),
    FOREIGN KEY(world_id,order_id,item_id) REFERENCES order_items(world_id,order_id,item_id),
    CHECK(record->>'pickup_status' IN ('scheduled','completed'))
);
CREATE TABLE pincodes (
    world_id text NOT NULL REFERENCES worlds, pincode text NOT NULL,
    serviceable boolean NOT NULL, PRIMARY KEY(world_id,pincode)
);
CREATE TABLE coupons (
    world_id text NOT NULL, coupon_id text NOT NULL, order_id text NOT NULL,
    user_id text NOT NULL, record jsonb NOT NULL,
    PRIMARY KEY(world_id,coupon_id), UNIQUE(world_id,order_id),
    FOREIGN KEY(world_id,order_id,user_id) REFERENCES orders(world_id,order_id,user_id),
    CHECK((record->>'amount')::numeric = 100)
);
CREATE TABLE escalations (
    world_id text NOT NULL, escalation_id text NOT NULL, user_id text NOT NULL,
    record jsonb NOT NULL, PRIMARY KEY(world_id,escalation_id),
    FOREIGN KEY(world_id,user_id) REFERENCES users
);
CREATE TABLE sessions (
    session_id text PRIMARY KEY,
    world_id text NOT NULL REFERENCES worlds,
    principal_id text NOT NULL,
    token_hash text NOT NULL UNIQUE,
    verified_user_id text,
    revision bigint NOT NULL DEFAULT 0,
    facts jsonb NOT NULL DEFAULT '{}',
    created_at text NOT NULL,
    revoked boolean NOT NULL DEFAULT false,
    FOREIGN KEY(world_id,principal_id) REFERENCES users(world_id,user_id),
    CHECK (verified_user_id IS NULL OR verified_user_id = principal_id)
);
CREATE TABLE messages (
    message_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    session_id text NOT NULL REFERENCES sessions,
    sequence bigint NOT NULL,
    role text NOT NULL CHECK(role IN ('customer','support','system')),
    content text NOT NULL,
    timestamp text NOT NULL,
    UNIQUE(session_id,sequence)
);
CREATE TABLE proposals (
    proposal_id text PRIMARY KEY,
    session_id text NOT NULL REFERENCES sessions,
    request jsonb NOT NULL,
    decision jsonb NOT NULL,
    terms text NOT NULL,
    terms_hash text NOT NULL,
    proposal_sequence bigint NOT NULL,
    acceptance_sequence bigint,
    status text NOT NULL CHECK(status IN ('proposed','accepted','executed','rejected','superseded','stale')),
    result jsonb,
    created_at text NOT NULL
);
CREATE TABLE idempotency (
    session_id text NOT NULL REFERENCES sessions,
    request_key text NOT NULL,
    request_hash text NOT NULL,
    response jsonb NOT NULL,
    PRIMARY KEY(session_id,request_key)
);
CREATE TABLE audit_events (
    event_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    world_id text NOT NULL REFERENCES worlds,
    session_id text REFERENCES sessions,
    timestamp text NOT NULL,
    event_type text NOT NULL,
    arguments jsonb NOT NULL,
    result jsonb NOT NULL,
    changes jsonb NOT NULL,
    previous_hash text NOT NULL,
    event_hash text NOT NULL
);
CREATE INDEX audit_by_world ON audit_events(world_id,event_id);
CREATE FUNCTION prevent_audit_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'audit_events is append-only'; END $$;
CREATE TRIGGER immutable_audit BEFORE UPDATE OR DELETE OR TRUNCATE ON audit_events
    FOR EACH STATEMENT EXECUTE FUNCTION prevent_audit_mutation();
