# Cartly Agent Studio

A natural-language customer support chatbot with visible guardrails and exact proposal approval. Talk to GPT-6 Astra, watch real tool calls and server checks, then approve an action inside the conversation. All customers and transactions are synthetic.

## Try the product

1. Choose a demo customer and type a request, such as “I'd like to return the kurta in O0011.”
2. The agent asks for verification and any missing details. The demo credentials are shown above the chat.
3. **Activity** shows actual model requests, tool arguments/results, policy checks and blocked actions. Expand any step to see its data. **Context** shows verified identity, history and orders read. **Changes** shows resulting database changes.
4. The agent prepares an exact proposal with the action, amount, refund method and timing. Review it and press **Accept and proceed**, or decline and keep chatting.
5. The server rechecks eligibility before executing. Its result appears in chat and is included in subsequent conversation memory.

A typed “yes” remains a chat message. Execution requires the approval button bound to the exact displayed terms. Any new message invalidates an unexecuted proposal. Duplicate clicks or retries cannot execute the same proposal twice.

## How the hosted flow works

```text
Customer message
  → /api/chat
  → GPT-6 Astra + policy + conversation history
  → read tools / decide_policy
  → live tool results and guardrail events
  → agent asks a question or calls propose_action
  → exact proposal appears inside chat
  → customer accepts
  → /api/proposal checks session, proposal ID, terms hash and revision
  → eligibility recalculated against the latest stored session
  → action executes once; result and changes saved
  → conversation continues with that result in memory
```

The model cannot call mutation tools directly. Even a fabricated call with `confirmed=true` is rejected. Read tools enforce identity and ownership. Proposal execution enforces return windows, category restrictions, evidence, refund history, cumulative limits, shipping rules, duplicate protection, cancellation states, address eligibility and coupon eligibility. Amounts and payment methods come from database values.

The unused-item statement comes from the conversation and is reconfirmed explicitly in change-of-mind proposal terms. This is a customer assertion, not independently observed evidence. Escalation routing still depends on the agent following the policy; its tool requires the G3 summary.

## Files

| File | Responsibility |
| --- | --- |
| `app/page.tsx`, `app/globals.css` | Chat, inline proposal card, live activity, context, changes, demo selection and policy dialog. |
| `app/api/chat/route.ts` | Same-origin chat endpoint, session lock and streamed events. |
| `lib/agent.ts` | Astra tool loop, history, canonical proposal messages, usage accounting and spending gate. |
| `lib/chat-contract.ts` | Restricted agent tool schemas and hosted interaction instructions. |
| `lib/guarded-flow.ts` | Deterministic decisions, check events, proposals, acceptance, revalidation and action execution. |
| `app/api/proposal/route.ts` | Customer-only approval/rejection endpoint; locks before reading the latest session. |
| `lib/tools.ts` | Existing baseline tool implementation, called through the guarded hosted wrapper. |
| `lib/session.ts`, `app/api/session/route.ts` | Durable isolated sessions, reset and browser-safe snapshots. |
| `lib/reference/` | Policy, world data and original tool schemas; loaded only on the server. |
| `db/schema.ts`, `drizzle/` | Hosted SQLite session and shared API-spending tables. |
| `tests/agent-flow.ts` | Mocked multi-turn integration, guardrail, approval, concurrency and budget tests. |
| `tests/run.mjs` | Runs those tests and regenerates independent Python-tool parity expectations. |

Run `node tests/run.mjs` to test without making OpenAI API requests. It requires Python 3 for the baseline parity fixtures. Run the checked-in build/dev scripts for the website.

The hosted service uses a TypeScript wrapper and Sites SQLite storage. The separate Python/PostgreSQL service remains in the desktop project and the `evals/service/` export. The website does not call that local service. Each hosted conversation has its own synthetic world; separate conversations do not share order changes.

## Evaluation project

The complete evaluation project is in [evals/](evals/README.md): policies, prompts, fictional data, scenarios, simulator, reference calculator, tests and saved transcripts. Its guide explains case creation and grading.

The [stress suite report](evals/runs/stress_v1_baseline/REPORT.md) distinguishes precheck skips, observation-only cases, checker errors and transcript-reviewed results. Those historical scores do not evaluate this new guarded chat wrapper. No new paid evaluation run was started for this UI change.

The runtime never imports the simulator, scenario truth, expected outcomes, grader or reference calculator. Policy v0.8, world data and evaluation prompts remain unchanged; the hosted chat contract is a separate application instruction layer.

## Hosting, cost and limits

The existing Sites project uses a protected server-side `OPENAI_API_KEY`. `DEMO_BUDGET_USD` sets a shared lifetime allowance, default $3 across visitors; resetting a conversation does not reset spending. The server reserves a conservative request estimate and settles against API usage. Unknown-cost interruptions consume the reservation conservatively. This is an application allowance, not an API-account billing limit.

Sessions persist behind an opaque HttpOnly cookie. Simultaneous chat and approval requests serialize using the stored session lock. Actions, tool logs, visible messages and proposals persist together in the session payload.

Refunds, returns, coupons and escalations create demo records only. There is no real payment, pickup, evidence-upload flow or staff notification. Activity displays observable events, never private model reasoning.

Supporting browsers expose read-only `get_conversation_activity` and draft-only `draft_customer_message` WebMCP tools. Drafting never sends a message or approves a proposal.
