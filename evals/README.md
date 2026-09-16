# Cartly evaluations

**New practical increment:** [Cartly service v0.1](service/README.md) adds a local
PostgreSQL API, stored customer approvals, guarded actions, and replayable audit
events. Run `.venv-service/bin/python -m service demo` for the zero-cost walkthrough.
The evaluation baseline described below remains unchanged.

This folder contains the evaluation project behind the Cartly prototype: fictional customers, world records, customer simulation, the support agent, tools, a reference calculator, and saved experiments. It is independent of the website runtime. The website does not load scenarios, expected answers, or checker feedback.

## Latest measurement: stress_v1

[Read the stress-only result and transcript review](runs/stress_v1_baseline/REPORT.md). Its accuracy uses only these new cases. It does not combine them with the original dev or heldout results.

The supplied specification contains **13 cases**: H01–H12 plus H08b. Eleven request a scored result; H02 and H03 ask for observation only. Prechecks exclude H05 and H06 because their requested outcomes conflict with the frozen policy's A3 escalation rule. The remaining nine graded cases and two observations each receive one conversation attempt, subject to a $3 combined API budget. See [the exact precheck decisions](runs/stress_v1_baseline/precheck.json).

Measurement inputs: policy **v0.8**, `agent_v1.1` prompt, **GPT-6 Astra** agent with high reasoning, **GPT-5.6 Luna** customer with reasoning disabled, and unguarded tools. The model names actually returned by the API are in each case's `api_calls.jsonl`. All project dates come from `data/config.json`: **2026-09-15, IST**.

## How these evaluations are created

1. **Write a concrete customer situation.** Specify the opening message, tone, goal, facts the customer knows, when each fact may be revealed, and any pressure or refusal script. Keep expected answers and policy rules outside the customer profile.
2. **Add fictional world records.** The stress generator appended 14 users, 16 orders and 17 items. Every earlier world record was retained unchanged. Item prices, payment methods, timestamps, evidence, and ownership live in the database; claims and customer intent stay in the scenario. The data validator found zero violations.
3. **Define an observable answer.** An acceptable end state describes exact inserts/updates, including target order/item and return reason. Scheduled returns carry an expected future refund; they do not count as money already refunded. Declines require no business-state changes. Escalations require a saved handoff.
4. **Check the answer before running.** `reference_inputs` translates relevant hidden facts into the existing calculator's structured interface. `simulation/reference_calculator.py` determines eligibility, amount, method and shipping. A disagreement is reported and skipped, not fixed to make the agent look better. This is a test oracle, not an agent tool.
5. **Run an isolated conversation.** Each attempt starts a new `CartlySession` from the JSON database. Luna plays the customer, Astra sees the saved support prompt and tools, and successful tools modify only that session's memory. Twenty support turns is the limit. Nothing writes back into `data/` during a conversation.
6. **Keep evidence and grade it.** Compare the final database delta with the expected state, check financial terms against the calculator, and inspect confirmation, clarification, communication, privacy, and forbidden actions in the transcript. Customer and checker mistakes are reported separately from agent mistakes. No agent conversation is retried to improve its score.

### Customer isolation and stress scripts

The customer receives only credentials, persona, goal, opening style, hidden facts and behavior rules, plus the config date. It does not receive the policy, calculator decisions, grading targets or world tables. The existing semantic fact gate, grounding checks, and terminal checks are reused.

The stress runner adds two explicit adapters: it emits the supplied opening verbatim, and Luna selects scripted events by meaning (for example, “after verification”). The original simulator's keyword scheduler cannot express every supplied trigger. This changes script scheduling for the new suite; it does not change the support agent or its prompt. Deviations from the requested customer script are recorded in the final review.

### What “accuracy” means here

The report distinguishes exact database outcome from full conversation correctness. A full pass also requires the requested communication, valid prior consent, correct identity/targets and no forbidden action. Observations, precheck skips and incomplete attempts do not enter the graded denominator. This is one trial per case; it is not pass^3 and is not an estimate across all customer traffic.

The first automated stress audit sometimes returned event IDs or policy numbers where numbered communication-requirement IDs were expected. Its raw failures remain saved. The separate transcript review records any corrected assessment, the exact evidence, and the review method; it never silently rewrites the raw results. An automatic-checker error is not evidence that the support agent failed.

## Folder map

| Path | Purpose |
|---|---|
| `policy.md` | Locked business rules; v0.8 was unchanged during this measurement. |
| `prompts/agent_v1.1.md` | Exact saved agent system prompt, including reference date and policy. |
| `data/` | Tool-visible users, orders, items, refunds, returns, pincodes and config. |
| `scenario_truth/` | Hidden labels and historical fixture facts; tools never read this layer. |
| `scenarios/scenarios.json` | Original 40 scenarios, including 30 dev and 10 heldout. Unchanged. |
| `scenarios/stress_v1.json` | The separate 13-case stress suite, expected states and factual calculator inputs. |
| `cartly/tools.py` | Verification, order reads, mutations, reset, logging and optional guarded mode. |
| `simulation/customer.py`, `fact_gate.py`, `answerability.py`, `customer_checks.py` | Customer speech, fact release, grounding and ending checks. |
| `simulation/reference_calculator.py` | Deterministic expected business outcomes. Frozen for this measurement. |
| `simulation/model_client.py` | API client and environment-only/local-secret API-key lookup. No key is committed. |
| `evaluation/agent.py`, `tool_schema.py` | Support-agent loop and model-facing tool definitions. |
| `evaluation/stress.py` | Stress prechecks, isolated one-attempt runner, all-role budget accounting and raw grading. |
| `evaluation/grader.py`, `confirmation.py`, `judge.py` | Existing state, confirmation and transcript checks used by the baseline. |
| `evaluation/run.py`, `scorecard.py` | Original dev/heldout runner and scorecard. The stress run does not use its dev aggregation. |
| `scripts/create_stress_v1.py` | Append-only fixture/scenario generator; refuses to regenerate an existing suite. |
| `scripts/validate_data.py` | Referential integrity, dates, refund math, status and planted-condition validation. |
| `scripts/export_evals.py` | Desktop-to-`website/evals/` export with an allowlist and a credential scan. It leaves the website's runtime world alone. |
| `tests/` | Local calculator, tool, simulator, harness and stress-fixture regression tests. |
| `runs/stress_v1_baseline/` | New run results, raw transcripts, tool logs, usage, review and stress-only report. |
| Other `runs/` directories | Historical experiments, retained unchanged; not part of the new accuracy. |
| `EXPORT_MANIFEST.json` | SHA-256 hashes of exported files for checking the GitHub copy. |

Historical README files describe their original versions. For the current stress measurement, use this document, the saved run manifest and per-case metadata.

## Inspect and validate without API spending

From the GitHub checkout:

```sh
cd evals
python3 -m evaluation.stress --precheck
python3 scripts/validate_data.py --report /tmp/cartly-stress-validation.json
python3 -m unittest tests.test_stress tests.test_reference_calculator
```

These are local checks. They do not call a model. The relevant test run passed 23 tests. One separate historical harness test still compares the entire world-data file to its old hash; it fails after the explicitly authorized append. We have not changed that historic baseline to hide the difference. The stress preservation check instead proves each original row, frozen component and earlier run file is unchanged.

For a new, unstarted measurement checkout, `python3 -m evaluation.stress --run` makes paid API calls using `OPENAI_API_KEY`. This checked-in run already exists, so that command deliberately refuses to overwrite it. Create a separately named future experiment rather than deleting these results. Do not run `create_stress_v1.py` against the already-expanded data.

## Read an individual result

Under `runs/stress_v1_baseline/H01/` (and each other attempted ID):

- `transcript.json`: exact customer/support messages and tool events in order.
- `tool_log.json` and `session_logs/`: every tool's arguments and result/error.
- `initial_state.json` / `final_state.json`: exact session database before and after.
- `api_calls.jsonl`: full model requests/responses and token usage; no authorization headers.
- `simulator_trace.json`: fact releases, script triggers, grounding and stop judgments.
- `metadata.json`: model, policy, prompt, data hashes, mode, split and trial.
- `result.json`: original automatic result, including checker errors if any.

The run-level `budget.json` sums agent, customer and checker usage at the saved rates. It is a usage-based estimate in USD, not the account invoice. The conservative preflight reserves the maximum next request before spending, and blocks requests that could exceed $3. `preservation_before.json` and `preservation_check.json` prove the measurement did not change frozen inputs or previous results.

## Desktop, GitHub and the website

The desktop authoring project and this `evals/` folder contain matching evaluation files. GitHub stores and displays them; it does not automatically run the models or host the agent backend. The website uses its own `lib/reference/` runtime bundle and Sites deployment. Adding new test fixtures here does not add these customers to the public demo or deploy a new website version.

The previous public evaluation snapshot was older than the desktop project. This export also synchronizes the already-existing desktop v0.8/Luna files and previously saved runs. Those Git differences predate this stress measurement; the preservation hashes prove that the measurement itself left the protected desktop components unchanged.
