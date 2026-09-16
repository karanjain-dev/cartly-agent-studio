# Unified production deployment

The website stays on its existing Sites URL. The same Python backend used locally
runs as a Docker service, with a separate persistent PostgreSQL service.

## Published rollout

- Website: https://cartly-agent-studio.karan-jain-iitbhu.chatgpt.site (Sites version 5).
- Backend: https://cartly-api-production.up.railway.app (Railway, PostgreSQL persistent volume).
- GitHub: https://github.com/karanjainiitbhu/cartly-agent-studio.
- Deployed runtime source: `30e9324fb3c2214234752f1af1b5aaa8a3a44c14`.
- Website release commit: `6a02fb13bd882336df75b6618bc42b5414211d7d`
  (website-rooted release preserving the existing Sites history).
- Railway uses the account's trial; no paid plan was purchased.
- Current support model: `gpt-5.6-terra` with low reasoning. The prompt, policy,
  tools, data, approval flow, and database guardrails are unchanged.

The live Railway service is `cartly-api`, connected to GitHub `main` for deployment.
The user removed the unused `cartly-agent-studio` Railway service. Only the live
`cartly-api` service and PostgreSQL are required.
The website must also be published through Sites when frontend source changes.
Never upload ignored local secrets or local databases.

The shared-playground update uses `<CARTLY_WORLD>-shared-web-v1` in the same
PostgreSQL instance. It starts fresh by explicit user choice. Old isolated worlds
are backed up privately and removed by the administrative cleanup. New conversations reuse
the shared world; only their chat/approval state is new. The additional 20 customers
and 100 orders are inserted once from `service/demo_data/playground_v1.json`, under
the world lock with audit entries. Restarts preserve all later mutations.

## Verification

- 51 service tests passed; frontend proxy checks, typecheck and production build passed.
- Hosted `/health` returned 200 with PostgreSQL storage and guarded mode.
- An unauthenticated session request was rejected; the authenticated session and
  policy endpoint worked.
- One explicitly approved live synthetic U018/O0011 chat verified identity and
  used three tools. Astra asked for the unused-item condition control. The smoke
  driver recorded that condition, requested the exact proposal and approved it
  through the same service endpoints used by the UI.
- Execution before approval was blocked. Approval created one return with a
  ₹1,400 UPI refund due after pickup. Retrying created no duplicate return.
  Pickup was not completed and no refund was issued by this test.
- Recorded model cost for the live smoke: $0.073134. This is one integration
  smoke test, not an accuracy evaluation or a browser interaction test.
- The old site's final allowance usage was $0.9607375, with no pending reservation.
  That amount was carried forward into the shared $3 budget. Increasing a later
  carryover only adds the difference; it never erases new backend spending.

The original deployment smoke above used Astra before the model change. The
subsequent 30-case Terra evaluation is recorded in
`runs/terra_agent_30_single_v0_8/REPORT.md`.

Local test evidence is retained in ignored `.cartly-service/production-live-smoke.json`
and `.cartly-service/production-approval-smoke.json`. These artifacts are not published.

## Backend

Deploy the repository root using `Dockerfile` and `railway.json`. The image copies
only runtime code, `data/`, `policy.md`, and `prompts/current.md`; it excludes secrets,
local databases, scenarios, the answer key, transcripts, and evaluation code.

Required runtime variables (never commit values):

| Variable | Value/source |
|---|---|
| `CARTLY_DATABASE_URL` | Private PostgreSQL connection supplied by the host |
| `CARTLY_SERVICE_KEY` | Random server-to-server secret of at least 32 characters |
| `OPENAI_API_KEY` | Existing approved OpenAI key, stored as a host secret |
| `CARTLY_INITIAL_SPENT_USD` | Old site's spent plus reserved allowance, measured immediately before cutover |
| `CARTLY_API_BUDGET_USD` | `3`, preserving the approved shared allowance |
| `PORT` | Host-provided port; defaults to 8000 |

`python -m service.production` requires the external database and secrets. It does
not start laptop PostgreSQL or read a local `.env`. It migrates and seeds the demo,
then listens on the host's port. `/health` verifies database connectivity.

The production transport reserves allowance in PostgreSQL before each model call.
Reservations are shared across sessions and instances. Restarts and new conversations
do not renew the allowance. Unknown network/process failures retain reservations
until the owner reconciles them. Conservative reservations may stop chat before
every last cent is used. Existing turn/model-call limits continue to apply.

## Frontend cutover

After the backend is healthy, set Sites secrets `CARTLY_BACKEND_URL` (HTTPS backend
origin) and `CARTLY_SERVICE_KEY` (same secret as the backend), then publish the
`website/` build. The OpenAI key stays in Python; frontend routes only proxy HTTP.
Keep the old publication available for rollback until the new session and chat work.

Historical demo conversations remain in the old Sites database. This rollout starts
fresh PostgreSQL demo sessions; it does not claim to migrate old conversations.
Saved repository evaluations remain untouched.

Sources: [Railway Docker builds](https://docs.railway.com/builds/dockerfiles),
[PostgreSQL](https://docs.railway.com/databases/postgresql),
[health checks](https://docs.railway.com/deployments/healthchecks).
