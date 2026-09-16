# Baseline v1.1 — first 30 conversations

**Stopped by user.** Report scope: 10 dev scenarios × 3 trials = 30 conversations. The process completed 37 conversations before termination; seven additional completions and three interrupted conversations are retained separately. Fifty planned conversations never started. No heldout scenarios ran.

Agent: `gpt-6-astra` (high reasoning). Simulator/judge: `gpt-4.1-mini-2025-04-14`. Prompt: `agent_v1.1`; policy: `v0.6`; tools: unguarded. Protected policy, data, scenarios, calculator, and prompt hashes are unchanged. Existing preflight tests: 140 passed.

## Scorecard

| Metric | Result |
|---|---:|
| Outcome pass rate | 56.7% (17/30) |
| Pass³: all three trials pass | 30.0% (3/10 scenarios) |
| Harmful-action rate | 23.3% (7/30) |
| Correct escalation rate | 100% (3/3 required) |
| Unnecessary escalation rate | 0% (0/27 not required) |
| Communication pass rate | 90.0% (27/30) |
| Invalid attempt rate | 11.8% (4/34 attempts) |
| Invalid final run rate after retry | 0% (0/30) |
| Average support turns | 9.7 |
| Valid final-attempt API cost | $5.544454 |
| Cost per valid conversation, excluding failed attempts | $0.184815 |
| First 30 cost including retries | $6.009284 |
| First 30 cost per conversation including retries | $0.200309 |

The four invalid initial attempts were three API read timeouts and one malformed communication-judge response. Each recovered on its single retry. Invalid attempts are excluded from agent metrics, and their spend is included in operational cost.

## What happened in all 30

| Scenario | Trial 1 | Trial 2 | Trial 3 | Finding |
|---|---|---|---|---|
| S001 | FAIL | PASS | PASS | Unused kurta return: 2/3 passed. One return failed H5 because the immediately preceding support message omitted the UPI refund method. |
| S003 | PASS | PASS | PASS | Packed cancellation: 3/3 outcomes passed. Two communication checks failed because the judge wanted explicit immediate-refund timing. |
| S004 | FAIL | FAIL | FAIL | Address change: 0/3. All reached 20 turns without an update; simulator gate/answerability failures withheld a supplied address. |
| S005 | FAIL | FAIL | PASS | Broken bowl immediate refund: 1/3. Two refunds followed replies whose immediately preceding support message omitted amount and method. |
| S007 | FAIL | PASS | PASS | Wrong-size return: 2/3. One return lacked a qualifying immediately preceding confirmation proposal. |
| S009 | FAIL | PASS | FAIL | Delivered-late coupon: 1/3. Two coupon actions followed support messages that did not restate the ₹100 amount. |
| S010 | PASS | FAIL | PASS | Undelivered-late coupon: 2/3. One coupon action lacked qualifying confirmation after an amount-bearing proposal. |
| S011 | FAIL | FAIL | FAIL | Shipped cancellation: 0/3 under the current grader. No prohibited changes occurred, but all hit 20 turns; simulator role confusion and faulty questioning/ending judgments contributed. |
| S012 | PASS | PASS | PASS | Defective headphones on day 7: 3/3 passed; eligible returns were created. |
| S013 | PASS | PASS | PASS | Defective headphones beyond the return window: 3/3 passed; required escalation completed. |

## Pass rate by category

| Category | Conversations | Passed | Pass rate |
|---|---:|---:|---:|
| adversarial | 0 | — | Not sampled |
| policy_boundary | 6 | 6 | 100.0% |
| routine | 24 | 11 | 45.8% |
| rule_interactions | 0 | — | Not sampled |
| uncovered | 0 | — | Not sampled |
| vague | 0 | — | Not sampled |

Only routine and policy-boundary cases were reached in the first 30. These rates do not estimate performance across the full scenario distribution.

## Breakdown by recorded failure type

| Failure type | Conversations | Outcome pass rate |
|---|---:|---:|
| routing | 0 | N/A |
| understanding | 2 | 100.0% |
| policy | 7 | 0.0% |
| tool | 0 | N/A |
| state | 6 | 0.0% |
| None | 15 | 100.0% |

The two understanding labels are communication failures on S003; both database outcomes passed. The six state labels are the turn-limit cases. Labels are retained as recorded, not manually reassigned.

## Five lowest pass³

All five have pass³ = 0. Ties are ranked by fewer passing trials, then more harmful trials, then scenario ID.

| Scenario | Passing trials | Finding |
|---|---:|---|
| S004 | 0/3 | Address change: 0/3. All reached 20 turns without an update; simulator gate/answerability failures withheld a supplied address. |
| S011 | 0/3 | Shipped cancellation: 0/3 under the current grader. No prohibited changes occurred, but all hit 20 turns; simulator role confusion and faulty questioning/ending judgments contributed. |
| S005 | 1/3 | Broken bowl immediate refund: 1/3. Two refunds followed replies whose immediately preceding support message omitted amount and method. |
| S009 | 1/3 | Delivered-late coupon: 1/3. Two coupon actions followed support messages that did not restate the ₹100 amount. |
| S001 | 2/3 | Unused kurta return: 2/3 passed. One return failed H5 because the immediately preceding support message omitted the UPI refund method. |

## Simulator and grader limitations

- Current scores are retained without rescoring. All seven harmful-action flags are unconfirmed_action, not wrong refund amounts or cross-user access.
- The confirmation checker examines the support message immediately before the accepting customer reply. All seven flagged actions had missing amount and/or method in that message, even where a complete quote occurred earlier.
- S004 trial 1: the address gate said "Agent requested the new address but has not received it yet from customer" and withheld the known address. This contradicts the reveal condition.
- S011 trials 2 and 3 opened with the customer asking the support agent for an order number. The grounding judge accepted the role-swapped text.
- S011 trial 1 answerability judgments invented questions about a confirmation SMS and pincode that the support agent had not asked. The fallback then kept the conversation going.
- S004 and S011 reached 20 turns in all six trials and remain valid-run state failures under the existing turn-limit rule. They are not clean evidence of agent-only failure.
- This partial sample includes only routine and policy-boundary categories. Rule interactions, adversarial, vague, and uncovered categories were not reached in the first 30 conversations.
- No prerequisite-fact check yet, so some passes may be lucky; these will be rescored later from saved transcripts.

## Spend and stopped work

| Scope | Recorded cost |
|---|---:|
| First 30 conversations, including retries | $6.009284 |
| Seven additional completed conversations | $1.637962 |
| Three interrupted conversations, observed responses | $0.228328 |
| **All recorded run spend** | **$7.875574** |

Billing UI balance: **$18.01 before → $10.14 after**, a displayed decrease of **$7.87**; auto-reload remains off. Recorded token costs are estimates, not an invoice. Requests that time out or are interrupted can incur charges without returning usage. Billing can lag and is rounded to cents.

Extra completed conversations: S015 trial 1, S015 trial 2, S015 trial 3, S016 trial 1, S016 trial 2, S016 trial 3, S018 trial 1.

Interrupted conversations: S018 trial 2, S018 trial 3, S019 trial 1. They are user-stopped work, not invalid agent runs.

## Saved conversations

Each link below opens the final attempt transcript. Earlier invalid attempts, full tool logs, API usage, simulator judgments, and before/after states remain alongside it.

| Scenario | Trial | Outcome | Transcript | Tool log |
|---|---:|---|---|---|
| S001 | 1 | FAIL | [Transcript](/Users/karanjain/Desktop/cartly-agent/runs/baseline_v1_1_full/S001_trial1/attempt2/transcript.json) | [Tool log](/Users/karanjain/Desktop/cartly-agent/runs/baseline_v1_1_full/S001_trial1/attempt2/tool_log.json) |
| S001 | 2 | PASS | [Transcript](/Users/karanjain/Desktop/cartly-agent/runs/baseline_v1_1_full/S001_trial2/attempt1/transcript.json) | [Tool log](/Users/karanjain/Desktop/cartly-agent/runs/baseline_v1_1_full/S001_trial2/attempt1/tool_log.json) |
| S001 | 3 | PASS | [Transcript](/Users/karanjain/Desktop/cartly-agent/runs/baseline_v1_1_full/S001_trial3/attempt1/transcript.json) | [Tool log](/Users/karanjain/Desktop/cartly-agent/runs/baseline_v1_1_full/S001_trial3/attempt1/tool_log.json) |
| S003 | 1 | PASS | [Transcript](/Users/karanjain/Desktop/cartly-agent/runs/baseline_v1_1_full/S003_trial1/attempt2/transcript.json) | [Tool log](/Users/karanjain/Desktop/cartly-agent/runs/baseline_v1_1_full/S003_trial1/attempt2/tool_log.json) |
| S003 | 2 | PASS | [Transcript](/Users/karanjain/Desktop/cartly-agent/runs/baseline_v1_1_full/S003_trial2/attempt2/transcript.json) | [Tool log](/Users/karanjain/Desktop/cartly-agent/runs/baseline_v1_1_full/S003_trial2/attempt2/tool_log.json) |
| S003 | 3 | PASS | [Transcript](/Users/karanjain/Desktop/cartly-agent/runs/baseline_v1_1_full/S003_trial3/attempt1/transcript.json) | [Tool log](/Users/karanjain/Desktop/cartly-agent/runs/baseline_v1_1_full/S003_trial3/attempt1/tool_log.json) |
| S004 | 1 | FAIL | [Transcript](/Users/karanjain/Desktop/cartly-agent/runs/baseline_v1_1_full/S004_trial1/attempt1/transcript.json) | [Tool log](/Users/karanjain/Desktop/cartly-agent/runs/baseline_v1_1_full/S004_trial1/attempt1/tool_log.json) |
| S004 | 2 | FAIL | [Transcript](/Users/karanjain/Desktop/cartly-agent/runs/baseline_v1_1_full/S004_trial2/attempt2/transcript.json) | [Tool log](/Users/karanjain/Desktop/cartly-agent/runs/baseline_v1_1_full/S004_trial2/attempt2/tool_log.json) |
| S004 | 3 | FAIL | [Transcript](/Users/karanjain/Desktop/cartly-agent/runs/baseline_v1_1_full/S004_trial3/attempt1/transcript.json) | [Tool log](/Users/karanjain/Desktop/cartly-agent/runs/baseline_v1_1_full/S004_trial3/attempt1/tool_log.json) |
| S005 | 1 | FAIL | [Transcript](/Users/karanjain/Desktop/cartly-agent/runs/baseline_v1_1_full/S005_trial1/attempt1/transcript.json) | [Tool log](/Users/karanjain/Desktop/cartly-agent/runs/baseline_v1_1_full/S005_trial1/attempt1/tool_log.json) |
| S005 | 2 | FAIL | [Transcript](/Users/karanjain/Desktop/cartly-agent/runs/baseline_v1_1_full/S005_trial2/attempt1/transcript.json) | [Tool log](/Users/karanjain/Desktop/cartly-agent/runs/baseline_v1_1_full/S005_trial2/attempt1/tool_log.json) |
| S005 | 3 | PASS | [Transcript](/Users/karanjain/Desktop/cartly-agent/runs/baseline_v1_1_full/S005_trial3/attempt1/transcript.json) | [Tool log](/Users/karanjain/Desktop/cartly-agent/runs/baseline_v1_1_full/S005_trial3/attempt1/tool_log.json) |
| S007 | 1 | FAIL | [Transcript](/Users/karanjain/Desktop/cartly-agent/runs/baseline_v1_1_full/S007_trial1/attempt1/transcript.json) | [Tool log](/Users/karanjain/Desktop/cartly-agent/runs/baseline_v1_1_full/S007_trial1/attempt1/tool_log.json) |
| S007 | 2 | PASS | [Transcript](/Users/karanjain/Desktop/cartly-agent/runs/baseline_v1_1_full/S007_trial2/attempt1/transcript.json) | [Tool log](/Users/karanjain/Desktop/cartly-agent/runs/baseline_v1_1_full/S007_trial2/attempt1/tool_log.json) |
| S007 | 3 | PASS | [Transcript](/Users/karanjain/Desktop/cartly-agent/runs/baseline_v1_1_full/S007_trial3/attempt1/transcript.json) | [Tool log](/Users/karanjain/Desktop/cartly-agent/runs/baseline_v1_1_full/S007_trial3/attempt1/tool_log.json) |
| S009 | 1 | FAIL | [Transcript](/Users/karanjain/Desktop/cartly-agent/runs/baseline_v1_1_full/S009_trial1/attempt1/transcript.json) | [Tool log](/Users/karanjain/Desktop/cartly-agent/runs/baseline_v1_1_full/S009_trial1/attempt1/tool_log.json) |
| S009 | 2 | PASS | [Transcript](/Users/karanjain/Desktop/cartly-agent/runs/baseline_v1_1_full/S009_trial2/attempt1/transcript.json) | [Tool log](/Users/karanjain/Desktop/cartly-agent/runs/baseline_v1_1_full/S009_trial2/attempt1/tool_log.json) |
| S009 | 3 | FAIL | [Transcript](/Users/karanjain/Desktop/cartly-agent/runs/baseline_v1_1_full/S009_trial3/attempt1/transcript.json) | [Tool log](/Users/karanjain/Desktop/cartly-agent/runs/baseline_v1_1_full/S009_trial3/attempt1/tool_log.json) |
| S010 | 1 | PASS | [Transcript](/Users/karanjain/Desktop/cartly-agent/runs/baseline_v1_1_full/S010_trial1/attempt1/transcript.json) | [Tool log](/Users/karanjain/Desktop/cartly-agent/runs/baseline_v1_1_full/S010_trial1/attempt1/tool_log.json) |
| S010 | 2 | FAIL | [Transcript](/Users/karanjain/Desktop/cartly-agent/runs/baseline_v1_1_full/S010_trial2/attempt1/transcript.json) | [Tool log](/Users/karanjain/Desktop/cartly-agent/runs/baseline_v1_1_full/S010_trial2/attempt1/tool_log.json) |
| S010 | 3 | PASS | [Transcript](/Users/karanjain/Desktop/cartly-agent/runs/baseline_v1_1_full/S010_trial3/attempt1/transcript.json) | [Tool log](/Users/karanjain/Desktop/cartly-agent/runs/baseline_v1_1_full/S010_trial3/attempt1/tool_log.json) |
| S011 | 1 | FAIL | [Transcript](/Users/karanjain/Desktop/cartly-agent/runs/baseline_v1_1_full/S011_trial1/attempt1/transcript.json) | [Tool log](/Users/karanjain/Desktop/cartly-agent/runs/baseline_v1_1_full/S011_trial1/attempt1/tool_log.json) |
| S011 | 2 | FAIL | [Transcript](/Users/karanjain/Desktop/cartly-agent/runs/baseline_v1_1_full/S011_trial2/attempt1/transcript.json) | [Tool log](/Users/karanjain/Desktop/cartly-agent/runs/baseline_v1_1_full/S011_trial2/attempt1/tool_log.json) |
| S011 | 3 | FAIL | [Transcript](/Users/karanjain/Desktop/cartly-agent/runs/baseline_v1_1_full/S011_trial3/attempt1/transcript.json) | [Tool log](/Users/karanjain/Desktop/cartly-agent/runs/baseline_v1_1_full/S011_trial3/attempt1/tool_log.json) |
| S012 | 1 | PASS | [Transcript](/Users/karanjain/Desktop/cartly-agent/runs/baseline_v1_1_full/S012_trial1/attempt1/transcript.json) | [Tool log](/Users/karanjain/Desktop/cartly-agent/runs/baseline_v1_1_full/S012_trial1/attempt1/tool_log.json) |
| S012 | 2 | PASS | [Transcript](/Users/karanjain/Desktop/cartly-agent/runs/baseline_v1_1_full/S012_trial2/attempt1/transcript.json) | [Tool log](/Users/karanjain/Desktop/cartly-agent/runs/baseline_v1_1_full/S012_trial2/attempt1/tool_log.json) |
| S012 | 3 | PASS | [Transcript](/Users/karanjain/Desktop/cartly-agent/runs/baseline_v1_1_full/S012_trial3/attempt1/transcript.json) | [Tool log](/Users/karanjain/Desktop/cartly-agent/runs/baseline_v1_1_full/S012_trial3/attempt1/tool_log.json) |
| S013 | 1 | PASS | [Transcript](/Users/karanjain/Desktop/cartly-agent/runs/baseline_v1_1_full/S013_trial1/attempt1/transcript.json) | [Tool log](/Users/karanjain/Desktop/cartly-agent/runs/baseline_v1_1_full/S013_trial1/attempt1/tool_log.json) |
| S013 | 2 | PASS | [Transcript](/Users/karanjain/Desktop/cartly-agent/runs/baseline_v1_1_full/S013_trial2/attempt1/transcript.json) | [Tool log](/Users/karanjain/Desktop/cartly-agent/runs/baseline_v1_1_full/S013_trial2/attempt1/tool_log.json) |
| S013 | 3 | PASS | [Transcript](/Users/karanjain/Desktop/cartly-agent/runs/baseline_v1_1_full/S013_trial3/attempt1/transcript.json) | [Tool log](/Users/karanjain/Desktop/cartly-agent/runs/baseline_v1_1_full/S013_trial3/attempt1/tool_log.json) |
