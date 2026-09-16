# v0.1 verification

These are software/service checks, not a new agent-accuracy measurement.

- **43 new service tests passed** against an actual temporary PostgreSQL server.
- **129 of 132 existing baseline tests passed.** Three historical preservation
  tests still expect snapshots from before the authorized stress fixture additions:
  `test_prompt_exact_and_protected_files_unchanged`,
  `test_data_scenarios_and_calculator_unchanged`, and
  `test_split_preserves_every_original_value_and_policy`.
- Compared desktop policy, world data, reference calculator and baseline prompt
  with the existing Git checkout copy: no differences.
- The new operational policy was compared with the independent reference
  calculator on the known ₹1,400 and ₹1,548 O0011 quotes and the ₹6,100 cumulative
  escalation case. Cancellation above ₹5,000 was also tested through PostgreSQL.
- The new agent adapter was tested with controlled API responses, including
  persisted memory, proposal handoff, a forged direct refund call and an API error.
  **No paid live-model trial was run.**

## Actual local walkthrough

The `demo` command exercised the real HTTP handlers and PostgreSQL tables. It
recorded an unused-item assertion, proposed a ₹1,400 UPI refund after pickup,
blocked execution before approval, created a return after approval, retried
without creating a second return, reconstructed the API and retrieved the same
result, then completed pickup and inserted one ₹1,400 refund.

The resulting database was reconstructed from saved audit changes and matched
PostgreSQL. The demonstration made **zero API calls, costing $0**.
The full request/result evidence is local at `.cartly-service/latest-demo.json`.
Run the demo again to create a new, isolated sandbox with new evidence.

## Limits of this increment

The website has not been switched to this API. The local auth exchange uses
synthetic credentials, money movement is a durable simulated ledger entry, and
escalations are saved handoffs. Natural-language approval alone is not accepted;
the customer must use the structured approval control. This milestone does not
repair historical checker results or establish a new support-agent pass rate.
