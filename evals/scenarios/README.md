# Cartly scenarios

`scenarios.json` contains 40 cases: 30 dev and 10 heldout. Do not print heldout
case content in development summaries. The terminal mode accepts an explicit
heldout ID for a deliberate manual run, but the listing command lists dev only.

Each expected state describes exact business changes in `changes`, plus a refund
quote/timing when relevant. Generated row IDs/timestamps are intentionally excluded.
`no_other_changes: true` prohibits extra writes. Escalation rows require all four
G3 fields; their natural-language contents need not match a fixed sentence.
A future refund quote after pickup is not an immediate refund database row.

The self-check sends each case twice in separate stateless API requests. Inputs
contain only policy.md, the user's own world records (with fixed clock and
pincode coverage), and all hidden facts. No expected state, split, label, rule
list, other decision, or scenario ID enters those requests. The fixed output
schema is the same for every case. Each response is retained with its API ID,
model, usage, and input hash. The checker never edits scenarios. Exact canonical
comparison can flag formatting differences as well as substantive disagreements.

`self_check/report.json` is the complete private disagreement report, including
heldout details. The public summary suppresses heldout content. A previous
rate-limited GPT-4.1 partial attempt is retained separately for audit.
