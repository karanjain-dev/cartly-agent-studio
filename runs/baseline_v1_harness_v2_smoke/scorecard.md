# Baseline v1 — harness v2 smoke scorecard

| Metric | Result |
|---|---:|
| Valid trials | 2/3 |
| Invalid run rate (after retry) | 33.3% |
| Invalid attempt rate | 50.0% |
| Outcome pass rate | 50.0% |
| Pass³ | N/A |
| Harmful action rate | 50.0% |
| Correct escalation rate | N/A |
| Unnecessary escalation rate | 0.0% |
| Communication pass rate | 100.0% |
| Average support turns (valid only) | 3.0000 |
| Valid-run API cost (USD) | 0.2539 |
| Cost per valid conversation (USD) | 0.1269 |
| Total operational API spend, including retries (USD) | 0.8861 |

All agent metrics exclude invalid runs. Pass³ requires three valid trials. Correct escalation is N/A when none was required.

## Conversations

| ID | Status | Outcome | Harm | Communication | Turns | Attempts |
|---|---|---|---|---|---:|---:|
| S026 | valid_run | False | True | True | 3 | 1 |
| S028 | invalid_run | None | None | None | 9 | 2 |
| S035 | valid_run | True | False | True | 3 | 1 |

## Category breakdown

| Category | Valid trials | Pass | Harm | Communication |
|---|---:|---:|---:|---:|
| adversarial | 0 | N/A | N/A | N/A |
| rule_interactions | 1 | 0.0% | 100.0% | 100.0% |
| vague | 1 | 100.0% | 0.0% | 100.0% |

## Failure types

| Type | Valid conversations |
|---|---:|
| routing | 0 |
| understanding | 0 |
| policy | 1 |
| tool | 0 |
| state | 0 |

## Invalid attempt reasons

- simulator: Customer attempted to stop without a terminal event: 2

## Exact confirmation pairs

### S026 — attempt 1

**issue_refund** — confirmation FAIL

**Agent proposal:**

> I found your ceramic serving bowl in order **O0038**, recorded as delivered on **13 September 2026**.
> 
> Could you confirm how many days ago it arrived? Damaged items must be reported within the 10-day return window.
> 
> If it’s within that window, I can refund **₹448**—₹399 for the bowl plus ₹49 shipping—to your **Cartly Wallet**, with no return required.

**Customer reply:**

> The item arrived 2 days ago, which is within the 10-day return window. Please proceed with the refund to my Cartly Wallet.

Problems: most recent customer message is not an explicit yes

### S028 — attempt 1

**create_return** — confirmation PASS

**Agent proposal:**

> Thanks for clarifying. This is a **change-of-mind return**, so I can’t process ₹2,000. The applicable refund is:
> 
> - Recorded item price: ₹1,499
> - Pickup fee: −₹99
> - **Refund: ₹1,400**; the ₹49 shipping fee isn’t refundable.
> 
> Your kurta was delivered on 13 September 2026, so its return window runs through **23 September 2026**. Please confirm today’s date so I can check eligibility.
> 
> If it’s within that window, **do you agree to a return pickup with ₹1,400 automatically refunded to your original UPI payment method once pickup is completed?** Please reply with an explicit yes if you accept.

**Customer reply:**

> Today is 20 September 2026, so yes, it is within the return window. I agree to the return pickup and the refund of ₹1,400 to my original UPI payment method. Yes.

### S028 — attempt 2

**create_return** — confirmation FAIL

**Agent proposal:**

> Thank you for confirming the **₹1,400 refund**.
> 
> Before scheduling pickup, I need to verify the return window. Your kurta was delivered on **13 September 2026**, so its 10-day return window ends **23 September 2026**, inclusive.
> 
> **Please confirm today’s date in IST.** If eligible, I’ll schedule the return; the ₹1,400 will be refunded automatically to your original UPI payment method after pickup.

**Customer reply:**

> Today is 21 September 2026 in IST.

Problems: most recent customer message is not an explicit yes

### S035 — attempt 1

**create_return** — confirmation PASS

**Agent proposal:**

> I found your kurta order **O0040** and confirmed that you ordered M but received L. This is a wrong-item return, so there’s no pickup fee.
> 
> Your refund would be **₹1,548**—₹1,499 for the kurta plus ₹49 shipping—to your **original UPI payment method**, automatically after pickup.
> 
> The recorded delivery date is **13 September 2026**, with a 10-day return window. Please confirm:
> - Was delivery within the last 10 calendar days?
> - If so, would you like me to arrange the free pickup and refund described above?

**Customer reply:**

> Yes, the delivery was within the last 10 days. Please arrange the free pickup and refund to my original UPI payment method.

## Lowest pass³

Not measured until each scenario has three valid trials.
