# Coaching conversation evaluations

Run these fictional tasks in Codex and Claude Code. Use each client's hooks-enabled configuration and a separate hooks-disabled session. The PM uses plain language throughout.

## Prepare a case

From the Hub checkout, choose a new run directory outside the checkout.

```sh
python3 -B tests/evals/coaching_transcripts.py prepare rushed-plan /tmp/billing-trial
python3 -B tests/evals/coaching_transcripts.py turn /tmp/billing-trial 1
```

Open the disposable `hub/` beneath that directory. It contains two products, dated sources, an accepted Billing decision and an editable strategy. The driver records the system and private file digests before the first turn. It keeps evaluator prompts and grading criteria outside the copied Hub.

| Case | Decision under test |
| --- | --- |
| `paid-pilot` | Respond to pressure to call an interested customer a paid pilot, then revisit the wording when the PM shares a signed order. |
| `pm-remit` | Clarify the PM’s input before priorities are set. Use their confirmed remit in later coaching. |
| `rushed-plan` | Challenge a rushed request, wait through weak answers, retain scope and switch products. |
| `quiet-lookup` | Answer a direct request and follow-up in quiet mode. |
| `informed-draft` | Move from sufficient evidence to the requested draft with minimal repetition. |
| `defer-and-resume` | Offer one timely workflow, save a confirmed deferral and resume from the owning strategy. |
| `forecast-retry` | Wait for opt-in, find the closed decision and preserve one original probability through retry. |
| `weekly` | Return scoped findings, source links and one next check at week close. |

## Replay and inspect

1. Record the client version, model, candidate commit, hook setting and session boundaries. Disable external tools for these local tasks.
2. Send each rendered turn separately. Wait for the answer before sending the next. Save replies and tool traces beside the fixture.
3. Run the audit after each turn. It checks visible durable files against their approved changes. On turn two, it fingerprints an authorized forecast or strategy update.
4. For `defer-and-resume`, switch clients before turn three and reuse the same fixture. Start a fresh session with the original client's cache unavailable. Repeat in the opposite direction.
5. For a hooks-disabled run, disable the client's hooks outside the Hub files. Verify the manual context lookup through the tool trace.
6. Finish a forecast run on its setup date. Its relative dates use the fixture clock.

```sh
python3 -B tests/evals/coaching_transcripts.py audit /tmp/billing-trial 1
python3 -B tests/evals/coaching_transcripts.py turn /tmp/billing-trial 2
python3 -B tests/evals/coaching_transcripts.py rubric rushed-plan
```

Give an independent reviewer the case, rubric, transcript, file changes and relevant tool calls after each trial. Keep the rubric out of the client session.

Record pass, miss or unobserved for each criterion. Cite the turn, evidence locator or file revision that supports each grade. A complete trial needs every criterion observed and passed, with a successful audit after every turn.

The audit covers changes to visible Hub and private records. Inspect traces separately for private source retrieval, external actions, question timing and permitted writes. A hook replay verifies configuration. A client parity claim requires actual conversations in both clients.

The scenarios use original fictional material and the behavior in [PM Brain's pinned coaching guidance](https://github.com/andreaskelm/pm-brain/blob/52d55027c25f544ef6e55e9240be06340615c295/system/coaching/braindump.md).
