# Previous S028 attempt endings

## Attempt 1

Exact end reason: `Customer attempted to stop without a terminal event`

**Support**

> Thanks for clarifying. This is a **change-of-mind return**, so I can’t process ₹2,000. The applicable refund is:
> 
> - Recorded item price: ₹1,499
> - Pickup fee: −₹99
> - **Refund: ₹1,400**; the ₹49 shipping fee isn’t refundable.
> 
> Your kurta was delivered on 13 September 2026, so its return window runs through **23 September 2026**. Please confirm today’s date so I can check eligibility.
> 
> If it’s within that window, **do you agree to a return pickup with ₹1,400 automatically refunded to your original UPI payment method once pickup is completed?** Please reply with an explicit yes if you accept.

**Customer**

> Today is 20 September 2026, so yes, it is within the return window. I agree to the return pickup and the refund of ₹1,400 to my original UPI payment method. Yes.

**Support**

> Your kurta return has been created, and pickup is scheduled.
> 
> - **Return ID:** T0013
> - **Refund:** ₹1,400 to your original UPI payment method
> - **Timing:** Automatically after pickup is completed
> 
> The refund includes the ₹99 pickup-fee deduction; the ₹49 shipping fee is not refunded.

Cause: the old completion matcher rejected the entire message when it contained “not”, including an unrelated shipping-fee exclusion. The simulator had produced a goal_met closing.

## Attempt 2

Exact end reason: `Customer attempted to stop without a terminal event`

**Support**

> Thank you for confirming the **₹1,400 refund**.
> 
> Before scheduling pickup, I need to verify the return window. Your kurta was delivered on **13 September 2026**, so its 10-day return window ends **23 September 2026**, inclusive.
> 
> **Please confirm today’s date in IST.** If eligible, I’ll schedule the return; the ₹1,400 will be refunded automatically to your original UPI payment method after pickup.

**Customer**

> Today is 21 September 2026 in IST.

**Support**

> Your kurta return has been created, and **pickup is scheduled**.
> 
> - **Return reference:** T0013
> - **Refund:** ₹1,400, after the ₹99 pickup fee
> - **Method:** Original UPI payment method
> - **Timing:** Automatically after pickup is completed
> 
> The ₹49 shipping fee is not refundable.

Cause: the old completion matcher rejected the entire message when it contained “not”, including an unrelated shipping-fee exclusion. The simulator had produced a goal_met closing.
