# Coaching conversation evaluations

Run these fictional tasks in Codex and Claude Code. Use each client's hooks-enabled configuration and a separate hooks-disabled session. The PM uses plain language throughout.

## Prepare a case

From the Hub checkout, choose a new run directory outside the checkout.

```sh
python3 -B tests/evals/coaching_transcripts.py prepare rushed-plan /tmp/billing-trial
python3 -B tests/evals/coaching_transcripts.py turn /tmp/billing-trial 1
```

Open the disposable `hub/` beneath that directory. The setup cases use the current Core frameworks. The PM case starts at the last company topic.
Cases about later work complete the company and PM walkthroughs and use a fictional product topic in their disposable checkout.

The driver records system and private file digests before the first turn. Evaluator prompts and grading criteria stay outside the copied Hub.

| Case | Decision under test |
| --- | --- |
| `company-first` | Ask for roadmap work, pause after saving one finding, then review all five company topics. Hand off to PM context. |
| `founder-company` | Clarify three reported customers and preview the company wording. Preserve the pilot terms, founder’s constraint, and open pricing question. |
| `strategy-goals` | After onboarding, propose a scoped way to clarify company objectives before drafting Billing strategy. |
| `expedite-roadmap` | Help shape a Q4 roadmap under deadline, check the trade-off, and return the PM’s exact line. |
| `paid-pilot` | Respond to pressure to call an interested customer a paid pilot, then revisit the wording when the PM shares a signed order. |
| `pm-walkthrough` | Finish company review, resume a paused PM walkthrough, and file a relationship in the stakeholder map. |
| `product-scope` | Disambiguate two connectors, confirm ownership, and preview a scoped finding in chat. |
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

For `company-first`, start a fresh session before turn five. The repeated roadmap question should resume the unfinished company walkthrough.
Check the discussion of each topic against the recorded outcome. Inspect why the final reply holds the roadmap.

For `pm-walkthrough`, start a fresh session before turn five. Check the resumed topic, the two approved destinations and the final product handoff.

For `expedite-roadmap`, audit every turn for writes. Grade the deadline response, evidence use and final wording from the transcript.

```sh
python3 -B tests/evals/coaching_transcripts.py audit /tmp/billing-trial 1
python3 -B tests/evals/coaching_transcripts.py turn /tmp/billing-trial 2
python3 -B tests/evals/coaching_transcripts.py rubric rushed-plan
```

Give an independent reviewer the case, rubric, transcript, file changes and relevant tool calls after each trial. Keep the rubric out of the client session.

Record pass, miss or unobserved for each criterion. Cite the turn, evidence locator or file revision that supports each grade. A complete trial needs every criterion observed and passed, with a successful audit after every turn.

The audit covers changes to visible Hub and private records. Inspect traces separately for private source retrieval, external actions, question timing and permitted writes. A hook replay verifies configuration. A client parity claim requires actual conversations in both clients.

The scenarios use original fictional material and the behavior in [PM Brain's pinned coaching guidance](https://github.com/andreaskelm/pm-brain/blob/52d55027c25f544ef6e55e9240be06340615c295/system/coaching/braindump.md).
