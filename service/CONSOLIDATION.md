# Local consolidation verification

Historical record of the local consolidation stage, before deployment. The
subsequent [production rollout](DEPLOYMENT.md) supersedes hosting status below.

At this stage, the change had not been deployed or pushed. The public site remained on its
previous release. The existing Git history now belongs to the desktop project
root, with the UI under `website/` and Python packages at the root.

## Results

- 47 current service tests passed, including real PostgreSQL browser API tests.
- 6 frontend proxy checks passed: credentials, cookies, response redaction,
  origin checks, validation, streaming and error propagation.
- Frontend typecheck and production build passed.
- Actual local HTTP path verified: website → Python → PostgreSQL session,
  followed by loading the effective prompt. Disabled paid calls return HTTP 503.
- Zero-cost service walkthrough passed against the independent calculator:
  O0011 unused return, ₹1,400 UPI, approval required, duplicate execution blocked,
  pickup completed, exactly one refund, audit replay matched the database.
- Data validator: zero violations; 54 users, 166 orders, 171 items, 40 refunds,
  12 seeded returns.
- 284 policy/data/scenario/simulator files match the previous Git snapshot byte
  for byte. No scenario answers, calculator rules or business data were edited.

## Pre-existing test failures

The historical evaluation suite has **129 passes and 3 failures**. The same three
failures were reproduced from the complete pre-change export in a temporary
directory, so they are not caused by this consolidation:

1. `test_prompt_exact_and_protected_files_unchanged`
2. `test_data_scenarios_and_calculator_unchanged`
3. `test_split_preserves_every_original_value_and_policy`

These compare the expanded fixtures against older saved preservation hashes.
Those hashes were deliberately not rewritten to manufacture a passing result.
Local reproduction evidence: `.migration-backup/preexisting-tests.txt`.

## Scope and practical limits

The local UI, terminal and current service tests use the same Python backend.
Historical baseline runners remain frozen for reproducing old experiments and
must not be presented as current-product accuracy. The calculator remains an
independent evaluation oracle, never an agent tool.

No paid model evaluation or new live-Astra accuracy measurement was run.
Browser integration uses recorded Astra-shaped replies. The existing live model
name and service instructions are unchanged; the instructions have moved to
`prompts/current.md` and are inspectable through the UI.

The local demo requires the approval control for actions and the item-condition
control for an unused assertion. Every browser reset starts an isolated sandbox;
reloading retains its conversation. Terminal/API sessions can share a world.

Public deployment requires a reachable authenticated Python backend, PostgreSQL,
and production access/spending controls. The archived hosted D1 budget gate is
not part of this local service. The old public deployment continues to enforce
its existing controls until a later, explicit cutover.
