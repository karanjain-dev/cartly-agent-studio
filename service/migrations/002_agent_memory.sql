CREATE TABLE agent_context (
    session_id text PRIMARY KEY REFERENCES sessions,
    input jsonb NOT NULL DEFAULT '[]',
    message_sequence bigint NOT NULL DEFAULT 0,
    turns integer NOT NULL DEFAULT 0,
    api_calls integer NOT NULL DEFAULT 0
);
CREATE TABLE agent_turns (
    session_id text NOT NULL REFERENCES sessions,
    request_id text NOT NULL,
    request_hash text NOT NULL,
    result jsonb NOT NULL,
    PRIMARY KEY(session_id,request_id)
);
