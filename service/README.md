# Cartly v0.1 — persistent support service

This is the first practical increment after the v0 agent demo. Conversations now
share a real PostgreSQL order database. The server checks policy, displays an exact
proposal, records the customer's approval, and commits each action with an audit
entry. A second conversation sees the first conversation's refund.

The original `cartly/`, `simulation/`, `evaluation/`, policy, prompts, scenarios and
world fixtures remain the v0 evaluation baseline. This service wraps its guarded
business tools. It never imports the reference calculator or hidden scenario truth.
The local website and terminal now use this same service. Start both with
`.venv-service/bin/python scripts/dev.py --enable-model` from the repository root.
The public website uses this same service, hosted with PostgreSQL on Railway.
See [deployment details](DEPLOYMENT.md) for hosting, allowance and verification.
The active product instructions live in `prompts/current.md`; `service/prompt.py`
adds the configured date and the policy saved with the conversation's sandbox.

## Shared website playground

The website, HTTP API and terminal use one durable world, `<configured world>-shared-web-v1`.
Startup resolves this ID once and does not seed a second base dataset.
New conversation creates only a chat/session; it does not reset orders, returns,
refunds or coupons. Visitors who select the same demo customer share that
customer's business history, while their chat messages and approvals stay private
to each conversation. Retired isolated browser datasets are exported to a private backup and removed
from production. Their conflicting refunds are not merged. A removed conversation
cookie starts a new chat; active shared conversations remain intact.

`service/demo_data/playground_v1.json` adds 20 customers (U201–U220), 100 orders
(O2001–O2100), and 100 items (I2001–I2100). Each customer has two cancellable orders,
two delivered orders and one shipment. Delivery windows, payment methods, evidence,
size mismatches and late-delivery eligibility vary. All dates use the fixed config
date. `service/playground.py` imports this once with audited inserts and a database
lock; a restart never restores modified orders. The frozen `data/` and eval
scenarios remain unchanged. Combined shared data has 74 customers and 266 orders;
the website selector exposes the original three demo customers plus the 20 new ones.
Browse the selected customer's orders to see IDs, products, status and refunds.

Verification: service tests cover a refund persisting into a second browser
session and across service reconstruction, a blocked repeat action, foreign-order
protection, concurrent/idempotent fixture import, fixture validity, and audit replay.

## Try the first working increment

From the project root (the desktop folder is now the Git checkout):

```sh
python3.12 -m venv .venv-service
.venv-service/bin/python -m pip install -r service/requirements-dev.txt
.venv-service/bin/python -m service demo
```

The desktop environment is already installed. The demo makes **no model calls**.
It uses the actual PostgreSQL database and HTTP handlers to:

1. Authenticate and verify U018.
2. Record the customer's assertion that the O0011 kurta is unused.
3. Offer a return with a ₹1,400 UPI refund after pickup.
4. Prove execution is blocked before approval.
5. Record approval, then create the return.
6. Retry the action and reconstruct the API: the same return is returned.
7. Complete pickup as a system event: exactly one ₹1,400 refund is recorded.
8. Reconstruct the final database from the audit trail and compare it with PostgreSQL.

The transcript of HTTP requests/results is saved to `.cartly-service/latest-demo.json`.
This is a deterministic service demonstration, not a fresh model evaluation or a
new accuracy result. Every invocation creates a separate demo sandbox.

## Start the API

```sh
.venv-service/bin/python -m service setup
.venv-service/bin/python -m service serve
```

Open http://127.0.0.1:8010/docs for the interactive endpoint documentation.
The service binds to this laptop only. PostgreSQL runs over a local Unix socket.
Its data is retained in `.cartly-service/postgres` when the process stops.

For an existing PostgreSQL installation, set `CARTLY_DATABASE_URL`; the bundled
local server is then unused. SQL migrations run once and their checksums are
verified. A changed applied migration is rejected.

## Talk to the agent

```sh
.venv-service/bin/python -m service chat --user U018 --enable-model
```

This command opts in to paid model calls. It uses the existing `OPENAI_API_KEY`
environment variable or local `.env`, and `gpt-5.6-terra` with low reasoning.
It does not run the simulated customer or any evaluation suite.

Try: `I want to return my kurta, order O0011.`

When asked about use, enter `/unused O0011 I0011 yes`. Then ask it to prepare the
return. Read the proposal and enter `/accept` to approve its exact terms, or
`/decline` to refuse. `/quit` exits. The active agent instructions live in
`prompts/current.md`; the original `agent_v1.1.md` is untouched.

To enable the same agent through `POST /v1/chat`, start `serve --enable-model`.
Without that flag, model calls are disabled. Sessions are limited to 20 customer
turns, 12 tool rounds per turn, and 40 model requests across restarts. These are
call limits, not a dollar spending cap; provider account limits still apply.

## Identity and confirmation

`POST /v1/sessions` requires the private `X-Cartly-Service-Key` header. The default
local key is generated in `.cartly-service/operator.key` with owner-only file
permissions. Alternatively set `CARTLY_SERVICE_KEY`. Never put it in browser code.

The demo uses the policy's user ID plus matching email/phone verification. This is
synthetic identity matching, **not production login or OTP verification**. A real
identity provider must replace this exchange before external customer access.
The returned bearer token is bound to exactly one customer and is hashed at rest.
The agent's `verify_user` cannot switch that identity.

Customer routes require that bearer token. Agent/operator routes additionally
require the private service key. The agent's registered tools do not include
customer acceptance, customer condition assertions, pickup completion, or direct
financial mutations. Even an invented call with `confirmed=true` is rejected.

The proposal is generated by the server, not free-form model text. It contains the
action, target, amount, method and timing, or the full new address. Customer
approval includes the proposal ID and a hash of those exact terms. The approval
endpoint records an explicit customer acceptance immediately after the proposal.
Free-text `yes` does not grant permission in v0.1; the terminal approval control
or a future UI button must be used. New conditions belong in a new chat message,
which invalidates the proposal. This is stricter than accepting natural-language
consent, and avoids guessing what a vague response meant.

Approval is bound to one session and one action. Before execution the service
rechecks current eligibility and financial terms. Changed terms require a new
proposal. An executed proposal returns its saved result on retry.

## Storage and consistency

The schema has separate users, orders, items, refunds, returns, pincodes, coupons,
escalations, sessions, messages, proposals and audit tables. Core identity/ownership
fields are relational columns with foreign keys; JSONB `record` columns preserve
all original and optional fixture fields. Unique indexes independently prevent a
second completed refund for an item and a second shipping refund for an order.

A PostgreSQL transaction commits the mutation, consumed approval, idempotency
result, and audit entry together. Failure to write the audit rolls back the action.
v0.1 serializes operations per sandbox using a world-row lock. This deliberately
simple locking protects cross-order refund history and financial limits; measure
throughput before replacing it with finer locks.

Audit events reject SQL UPDATE, DELETE and TRUNCATE and form a hash chain. Database
administrators can still change the schema; this is not external tamper-proof
storage. The development database uses its local owner account. A production
deployment needs separate migration/runtime roles and normal backup controls.

All application dates come from the seed config: **2026-09-15 IST**, even if the
laptop date changes. PostgreSQL/service operational logs are infrastructure logs;
they are never used for business eligibility. Runtime actions never write `data/`.

Refunds and handoffs are durable synthetic records. No payment provider, courier,
or real support inbox is connected yet. Pickup completion is an operator/system
event, not an agent tool.

## Reset and replay

```sh
.venv-service/bin/python -m service reset
.venv-service/bin/python -m service serve --world THE_NEW_SANDBOX_ID
.venv-service/bin/python -m service replay --world THE_DEMO_SANDBOX_ID
```

Reset creates a fresh sandbox from the original seed; it never deletes previous
orders or audits. Existing conversations stay attached to their original sandbox.
Replay validates the seed hash and audit chain, reapplies committed changes, and
compares the result with PostgreSQL. It does not grade conversation quality or
claim that a model followed policy simply because replay succeeded.

## Verification

```sh
.venv-service/bin/python -m pytest service/tests -q
.venv-service/bin/python -B -m unittest discover -s tests -q
```

The service tests run against actual PostgreSQL. They cover ownership, financial
boundaries, explicit approval, changed quotes, concurrency, retries, restart
persistence, audit rollback, HTTP access, agent memory and independent calculator
comparisons. Agent API responses in tests are controlled fixtures, so tests spend
no model credits. See [VALIDATION.md](VALIDATION.md) for the results and existing
historical test failures.

## File guide

| File | What it does |
| --- | --- |
| `api.py` | HTTP routes, strict request schemas and customer/operator access |
| `core.py` | Sessions, proposals, approvals, idempotent action execution |
| `policy.py` | Operational policy decisions and exact customer quotes |
| `engine.py` | Adapter for the existing guarded Cartly tool implementation |
| `repository.py` | PostgreSQL transactions, seed import and audit chain |
| `migrations/` | Versioned SQL schema, constraints and agent memory |
| `agent.py` | Terra conversation loop, persistent context and restricted tool registry |
| `prompts/agent_v0.1.md` | New service protocol instructions, combined with the locked policy |
| `local.py`, `__main__.py` | Local setup, server and terminal commands |
| `demo.py`, `replay.py` | Zero-cost practical walkthrough and saved-state verification |
| `tests/` | Automated service, policy, concurrency and agent-adapter checks |

Next increment: connect a UI to this API and replace demo identity matching with a
real login provider. Then measure agent conversations against the existing evals
using a service adapter, while preserving the old baseline scores separately.

## Administrative cleanup

`service/maintenance.py` is an offline administrator command, never a tool or HTTP
endpoint. Export saves a complete logical backup with checksums. Pruning requires
the exported retired-record fingerprint, locks the tables, removes only retired
demo worlds, and verifies current records and all spending state are unchanged.
Audit immutability is restored within the same transaction. A restore helper is
tested against an empty schema. Keep backups outside Git and restrict file access.
The retained world identifier supports isolated test databases; production has
only one dataset. Frozen evaluation fixtures and test scenarios are not live DB copies.
