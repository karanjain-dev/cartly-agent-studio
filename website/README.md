# Cartly browser UI

This folder is the frontend of the single Cartly project in the parent directory.

- `app/page.tsx`: chat, item condition, exact approval controls, activity, prompt viewer.
- `app/api/*`: same-origin checks and transport to Python.
- `lib/session.ts`: opaque HttpOnly cookie and server-authenticated HTTP forwarding.
- No OpenAI client, eligibility rules, world snapshot or reference calculator lives here.

Start from the project root with `.venv-service/bin/python scripts/dev.py --enable-model`.
The launcher supplies `CARTLY_BACKEND_URL` and `CARTLY_SERVICE_KEY` as server-only
bindings. The browser never receives either credential or the OpenAI key.
The frontend can stream `/web/chat` from Python without interpreting its tool calls.

All product behavior is in the parent `service/` and `cartly/` packages.
All evaluations are at the project root; `website/evals/` no longer exists.

This UI is published at https://cartly-agent-studio.karan-jain-iitbhu.chatgpt.site
and forwards to the authenticated Python backend on Railway. Runtime bindings
are configured as server-side values in Sites. See `../service/DEPLOYMENT.md`.
The website has no database binding. PostgreSQL on Railway is the sole product database.
Retired database code remains available through Git history only.

Checks: `node tests/run.mjs`, TypeScript typecheck, `node scripts/run-framework.mjs build`.
