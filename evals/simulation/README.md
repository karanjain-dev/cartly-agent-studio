# Customer simulator and manual support chat

The baseline support agent is in evaluation/. The simulator uses the Python standard library only. The simulator
uses GPT-4.1 mini through the Responses API. Configure OPENAI_API_KEY in the shell
or the existing project .env. The key is never printed or saved to chat logs.

From the project directory:

```sh
python3 -B -m simulation.chat S028
python3 -B -m simulation.chat S035
python3 -B -m simulation.chat --list-dev
```

You type the support replies. The model plays only the customer. Type `/quit` or
press Ctrl-D to exit. The customer ends after completion, final refusal with pressure exhausted, human handoff, or at the turn limit. Both `###STOP###` and a clear natural closing are accepted.
Use `--model MODEL_ID` to override the model. Logs are saved per chat under
`logs/customer_chats/` using only the fixed configuration timestamp.

## Information boundary

The customer profile contains only persona, goal, opening_style, hidden_facts,
behavior_rules and credentials. The simulator also knows the fixed current date and IST timezone from config, just as a real customer would. No policy, other world database values, expected outcomes,
rule labels, must-communicate list, or forbidden-action list is passed to it.
The routing CLI selects the profile and discards the rest before constructing
the customer. A separate semantic gate call to the same simulator model reads the candidate facts and reveal conditions. Hidden fact text is withheld from the speaking-model request until that gate releases it. Only active behavior instructions enter a request.
The customer is instructed not to invent unknown facts. Used fact IDs are checked against released IDs, including the explicitly gated credentials source. A rejected reference triggers rephrasing; after two unsuccessful repairs the simulator gives a fact-free clarification request instead of aborting. Before answering factual questions, the simulator model must identify exact supporting profile text. Missing or fabricated evidence causes a fixed unsure/need-to-check answer before generation. The simulator model also reviews actual draft text for unsupported assertions. Unknown pincodes, SMS messages, dates, amounts, IDs, and events must receive an unsure/need-to-check response. Unsupported wording is rephrased, with a safe fallback if repair fails. This check also identifies natural closings and recognizes that “shipping is not refunded” does not negate a scheduled pickup. Customer acceptance of a pending action is distinct from completion; the former always continues the conversation. All judgments are logged. These are model judgments, so regression tests and transcript review remain necessary.

Fact release uses semantic judgments from GPT-4.1-mini, not keyword matching.
The size-comparison fact is released for questions about ordered versus delivered
size or wrong size versus fit; a generic “What's the problem?” does not release it.
Every fact decision and rephrasing attempt is recorded in the simulator trace.
Opening facts are available at the opening. Existing finite behavior and terminal
state checks are separate from fact release. Never put facts that must remain
hidden into the always-visible goal/persona.

## Independent scenario checks

```sh
python3 -B -m simulation.self_check --workers 4
```

Two independent GPT-4.1-mini decisions per case (80 total). Failed API requests
are retried with bounded rate-limit pacing; completed matching input hashes can
be resumed without paying for duplicate calls. Each request uses store=false and
has no previous-response context. Disagreements are recorded without changing the
scenario or its expected outcome. The optional stronger-model override is
`--model gpt-4.1`. API use is billable to the configured account.

## Verification

```sh
python3 -B -m unittest discover -s tests -v
python3 -B scripts/test_validate_data.py
python3 -B scripts/validate_data.py
python3 -B -m simulation.smoke
```

The last command makes live API calls for two dev cases using fixed test replies;
it is a test harness, not a support agent.

Official API references:
- https://developers.openai.com/api/docs/models/gpt-4.1-mini
- https://developers.openai.com/api/reference/cli/resources/responses/methods/create
