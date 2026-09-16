ALTER TABLE api_budgets ADD COLUMN carried_over_usd numeric NOT NULL DEFAULT 0
    CHECK (carried_over_usd >= 0);
