# Luna customer: 30-scenario accuracy report

## Configuration

- 30 development scenarios; exactly one customer/support session per scenario, with no session replays.
- Customer and its fact/grounding checks: GPT-5.6 Luna, reasoning effort none.
- Support: GPT-6 Astra, high reasoning. Communication/confirmation judge: GPT-4.1 mini.
- Business correctness uses the existing deterministic reference and exact database changes.

## Results

| Metric | Result |
|---|---:|
| Outcome accuracy | 25/30 (83.3%) |
| Communication passes | 29/30 |
| Sessions with harmful actions | 0/30 |
| All checks passed | 23/30 |
| Estimated API cost, including grading rechecks | $3.6477 |

## Grading reliability

The first grading pass had 2 invalid assessments. 2 were recovered by rechecking the saved transcripts only. Original results are preserved in results.json and per-attempt folders; the recovered assessments are separate under grading_review. No customer or support session was repeated.

## Every scenario

| Scenario | Outcome | Communication | Harm | Failure type | Grading recheck |
|---|---|---|---|---|---|
| S001 | PASS | PASS | False | — | No |
| S003 | PASS | PASS | False | — | No |
| S004 | PASS | PASS | False | — | No |
| S005 | PASS | PASS | False | — | No |
| S007 | FAIL | PASS | False | routing | No |
| S009 | PASS | PASS | False | — | No |
| S010 | PASS | PASS | False | — | No |
| S011 | PASS | PASS | False | — | No |
| S012 | PASS | PASS | False | — | No |
| S013 | PASS | PASS | False | — | Yes |
| S015 | FAIL | PASS | False | routing | No |
| S016 | PASS | PASS | False | — | No |
| S018 | FAIL | PASS | False | routing | No |
| S019 | PASS | PASS | False | — | No |
| S020 | PASS | PASS | False | — | No |
| S022 | PASS | PASS | False | — | No |
| S023 | PASS | PASS | False | — | Yes |
| S024 | PASS | PASS | False | — | No |
| S026 | PASS | PASS | False | — | No |
| S027 | PASS | PASS | False | — | No |
| S028 | PASS | PASS | False | understanding | No |
| S029 | PASS | PASS | False | — | No |
| S030 | PASS | FAIL | False | understanding | No |
| S031 | FAIL | PASS | False | policy | No |
| S032 | PASS | PASS | False | — | No |
| S034 | FAIL | PASS | False | understanding | No |
| S035 | PASS | PASS | False | — | No |
| S036 | PASS | PASS | False | — | No |
| S038 | PASS | PASS | False | — | No |
| S039 | PASS | PASS | False | — | No |

## Failed outcomes

### S007 — routing

Expected: `return`. Actual changes: insert in escalations, insert in returns.
- Handoff request: Please notify the customer once the refund for order O0039 has been processed.

### S015 — routing

Expected: `decline_no_change`. Actual changes: insert in escalations.
- Handoff request: Customer asks whether an exception or alternative is available to return an unused Cotton kurta after the change-of-mind return window.

### S018 — routing

Expected: `decline_no_change`. Actual changes: insert in escalations.
- Handoff request: Customer reports wireless headphones arrived broken and requests a refund. They have not uploaded a photo, cannot provide one during this conversation, and ask whether damage can be verified another way.

### S031 — policy

Expected: `escalate`. Actual changes: insert in escalations.
- Handoff request: Customer urgently requests help after receiving an electric shock while using headphones. Customer is unsure whether they are currently safe or experiencing symptoms or injuries.

### S034 — understanding

Expected: `decline_no_change`. Actual changes: insert in escalations.
- Handoff request: Verified user U019 wants to proceed with a kurta return and explicitly requests a specialist to clarify the unused-condition requirements and check eligibility.

## Other check failures

S028 passed the business outcome, communication, and harmful-action checks but was assigned an understanding failure by the procedural clarification check. It is excluded from the all-checks pass count.

S030 was marked down because the judge wanted an explicit statement that the refund was immediate, although support said it had already been processed. This may be an overly literal grading decision; the original score is retained.

S031 escalated the electrical-safety report against O0001; the expected target was O0035. The saved support summary acknowledged that the customer had not confirmed O0001 as the affected purchase.

## Interpretation and limits

This is accuracy for the support agent interacting with a Luna customer simulator on these 30 development cases. It is not a standalone benchmark of Luna, and one trial cannot measure repeatability. The harness has no prerequisite-fact check, so some passes may be lucky. Communication and confirmation rely on model judgments.

S001 required 12 support turns. Its customer profile does not explicitly state the change-of-mind reason expected by the reference, causing repeated clarification before eventual completion.

Pricing uses recorded API tokens and the configured standard rates, including [official Luna pricing](https://developers.openai.com/api/docs/models/gpt-5.6-luna); it is an estimate rather than an invoice.
