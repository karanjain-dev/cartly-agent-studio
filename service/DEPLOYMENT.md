# Unified production deployment

The website stays on its existing Sites URL. The same Python backend used locally
runs as a Docker service, with a separate persistent PostgreSQL service.

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
