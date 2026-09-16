# Original S035 fact-gate failure

## Admitted transcript

**customer:**

I received the kurta, but the size doesn't seem right. I want to return it and get my money back.

**support:**

I can help check your return eligibility. Please share your user ID, either your registered email or phone number, and the order ID.

Was the kurta’s size different from the size you ordered, or did you receive the ordered size but the fit isn’t right? If it’s a fit issue, is the kurta unused?

## Hidden fact

I ordered size M and color Blue, but received size L and color Blue.

**reveal_when:** agent asks what is wrong or whether the item differs from the order

## Exact cause

The size comparison fact (`problem`) was already released. The released IDs were request, order, condition, problem. The rejected response cited request, order, credentials, problem. The set difference was therefore {credentials}. Credentials were present in the simulator prompt but had no permitted source ID. The guard raised `Customer attempted to use an unreleased fact` before adding the response to the transcript.

The new gate gives credentials an explicit source ID after semantic verification intent is detected. All other releases are semantic model decisions. Generic problem questions withhold size comparisons as explicitly requested, without editing scenario text.
