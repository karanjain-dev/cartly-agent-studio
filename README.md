# Cartly Customer Support

A hosted demonstration of Cartly's guarded support flow. Visitors choose one of three synthetic customers, select a supported request, review the exact policy-backed resolution, and explicitly approve it before any synthetic order change is made.

## Evaluation project

The complete evaluation project is stored in [`evals/`](evals/README.md): policies, prompts, fictional world data, scenarios, simulator, reference calculator, tools, tests and saved transcripts. The guide explains how cases are created and how outcomes are checked.

The newest suite is [`stress_v1`](evals/scenarios/stress_v1.json). Read its [separate accuracy report](evals/runs/stress_v1_baseline/REPORT.md), including precheck skips, observation-only cases, checker errors and transcript-reviewed results. These scores do not mix in the original dev or heldout cases.

GitHub stores the evaluation source and evidence. It does not run paid evaluations automatically, and the website does not load hidden facts or expected answers. New evaluation fixtures do not modify the live demo's runtime database.

## What runs

- The guided request flow computes eligibility, amount, payment method, timing, and rules from the synthetic order values. The customer never supplies the amount used for an action.
- A stored proposal contains the exact terms and a SHA-256 terms hash. Acceptance requires that same proposal; execution recalculates the decision before calling the action tool.
- A fresh synthetic world per conversation. SQLite stores each conversation behind an opaque, HttpOnly session cookie. Reset replaces that session's world, proposal, and changes.
- The older free-form agent route remains read-only. It cannot call a return, refund, cancellation, address update, or coupon tool; order-changing work is available only through the proposal flow.
- No simulator, scenario truth, heldout scenarios, grader, or reference calculator is loaded at runtime. The original project remains the evaluation source of truth.

## Files

- `app/page.tsx`, `app/globals.css`: responsive guided support workspace, request selection, exact-terms approval dialog, demo customer selection, policy dialog, and visible activity.
- `app/api/session/route.ts`: create, retrieve, and reset isolated sessions.
- `app/api/proposal/route.ts`: creates a policy-backed proposal, validates acceptance of its exact terms, rechecks it, and executes the approved action.
- `lib/guarded-flow.ts`: deterministic policy decisions, proposal terms, acceptance binding, final recheck, and action dispatch.
- `app/api/chat/route.ts`: legacy read-only conversational lookup route. It cannot execute order-changing tools.
- `app/api/policy/route.ts`: serve the exact policy for inspection.
- `lib/agent.ts`: read-only model loop, live events, usage accounting, and shared spending allowance.
- `lib/tools.ts`: equivalent implementation of the baseline support tools.
- `lib/session.ts`: session persistence and browser-safe snapshots.
- `lib/reference/`: unchanged world values, policy/prompt, tool schemas, and hashes of the original inputs. These imports stay on the server.
- `db/schema.ts`, `drizzle/`: SQLite session and shared spending tables plus migration.
- `tests/`: Python-to-TypeScript tool parity and a deterministic agent-loop check that makes no API requests.
- `.openai/hosting.json`: the existing Sites project and storage binding. No credentials belong here.

## Runtime configuration

Set `OPENAI_API_KEY` as a server-side secret in Sites. `DEMO_BUDGET_USD` sets a shared lifetime allowance, defaulting to $3 across all visitors. A new conversation does not reset spending. Each request first reserves a conservative maximum cost; the website pauses if insufficient allowance remains. The displayed API cost uses response usage at the baseline's configured rates. Unknown-cost interruptions conservatively consume their reservation. This is a prototype budget control, not an OpenAI account billing limit.

Use the checked-in package scripts to install dependencies, start the development server, and build. Apply the generated SQLite migration for local development. Publish through the Sites build/package/version/deploy workflow; the production migration is included in the artifact.

## Demo

Choose a customer, request a return, cancellation, or late-delivery coupon, then select **Review my resolution**. Cartly displays the exact action, amount, method, and timing. The customer must open the approval dialog and choose **I agree to these terms** before the server executes anything. Activity shows the order lookup, policy decision, stored proposal, acceptance, final recheck, and resulting synthetic change.

The page exposes `get_conversation_activity` and `draft_customer_message` in browsers supporting WebMCP. Drafting does not send a message or spend API credit.

## Limits

Refunds, returns, coupons, and human handoffs affect synthetic session records only. There is no real payment, pickup, or staff notification. The site is a product prototype, not a production customer-data system.
