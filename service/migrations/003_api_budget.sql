-- Deployment-wide allowance, independent of demo resets and reference dates.
CREATE TABLE api_budgets (
    budget_id text PRIMARY KEY,
    limit_usd numeric NOT NULL CHECK (limit_usd >= 0),
    spent_usd numeric NOT NULL CHECK (spent_usd >= 0)
);
CREATE TABLE api_reservations (
    reservation_id text PRIMARY KEY,
    budget_id text NOT NULL REFERENCES api_budgets,
    reserved_usd numeric NOT NULL CHECK (reserved_usd >= 0),
    status text NOT NULL CHECK (status IN ('pending','completed')),
    actual_usd numeric,
    usage jsonb
);
