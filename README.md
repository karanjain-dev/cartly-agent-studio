# Cartly Agent Studio

A hosted demonstration of the existing Cartly support agent. Visitors chat as one of three synthetic customers and see actual policy inclusion, tool calls, results, session context, and database changes alongside the conversation.

## What runs

- The exact `agent_v1.1` prompt with policy v0.6, reference date from the original configuration, model `gpt-6-astra`, and high reasoning effort.
- All 13 callable tools from the policy table, in unguarded baseline mode. The TypeScript implementation is checked against the original Python implementation with 895 calls across 216 sequences.
- A fresh synthetic world per conversation. SQLite stores each conversation behind an opaque, HttpOnly session cookie. Reset replaces that session's world, identity, history, and changes.
- No simulator, scenario truth, heldout scenarios, grader, or reference calculator is loaded at runtime. The original project remains the evaluation source of truth.
- Session history is sent with subsequent agent requests. There is no separate long-term memory service. The activity view shows observable events and tool results, not private model reasoning.

## Files

- `app/page.tsx`, `app/globals.css`: responsive chat workspace, activity/context/changes panels, demo customer selection, policy dialog, and conversation download.
- `app/api/session/route.ts`: create, retrieve, and reset isolated sessions.
- `app/api/chat/route.ts`: validate requests, serialize turns, and stream activity to the browser.
- `app/api/policy/route.ts`: serve the exact policy for inspection.
- `lib/agent.ts`: model loop, tool dispatch, live events, usage accounting, and shared spending allowance.
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

Choose a customer, draft a request with a starter button, then send it. Use the displayed demo credentials when asked to verify. Expand activity steps to inspect arguments/results. Context shows what was actually read; Changes shows successful writes. New conversation starts over. Download exports the visible transcript and activity.

The page exposes `get_conversation_activity` and `draft_customer_message` in browsers supporting WebMCP. Drafting does not send a message or spend API credit.

## Limits

20 customer turns per conversation, 20 tool rounds per turn, 3,000 characters per message. This keeps the existing unguarded baseline behavior, including its known policy failures. Refunds and human handoffs affect synthetic session records only. There is no real payment, pickup, or staff notification. No prerequisite-fact grading is added. Sessions persist for demonstrations; this is not a production customer-data system.
