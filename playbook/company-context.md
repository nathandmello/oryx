# Walk through company context

An ordinary request starts or resumes onboarding. Acknowledge it and keep it for after the walkthrough.
With hooks disabled, run `python3 tools/pm.py onboarding status` yourself before starting PM work.

Onboarding covers company, PM, then product context. Completion means the PM has reviewed each framework with oryx once.
Company is the first available walkthrough. The PM and product frameworks are pending design.
Use existing records to prepare each discussion. Saved context alone leaves the walkthrough pending.

## Start where the PM is

Pick up where the PM left off. Connect the first question to what they came to do.

> We can come back to your Q4 roadmap. First, what does your company do?

Follow their answer. If they mention a deck, offer to work from it. If they prefer talking, ask one relevant question at a time. They can also write directly or supply an excerpt. Attribute an interview answer to the speaker, date and discussion.

Learn how this company shares information before suggesting a tool. Offer public research or a connected internal source when it helps. Agree on the question, the source or search boundary, and what you will bring back. A connector's availability says nothing about permission. Ask before expanding the plan. Keep work moving with available sources if one is unavailable.

## Decide what to capture

Work through the [five company questions](company-frameworks.md) in order with the PM.
Use the coaching framework that helps explain the current topic. If earlier evidence covers this topic, reflect it briefly and invite correction.
The PM can share what they know, leave a topic open, or say it does not apply.
All five topics can remain open after a complete pass. Ask one question at a time.

Keep a standing claim in the overview when it changes how oryx would guide company or product work. Preserve the source, scope, date, qualifications and unresolved conflicts.

Give recurring detail a [supplementary company note](filing.md#when-a-file-earns-its-place) when it has its own reader need and review trigger. Show the note’s proposed link and the implication it explains. With the PM’s approval, add the link to the overview during maintenance. Route product detail to its product. Leave other detail with its source.

## Review and resume

Use `python3 tools/pm.py company-onboarding status` for the current review and revision. Offer the saved overview on request. Use `plan` to describe the proposed work. Call `approve` once the PM agrees to that source scope. Use the existing [context routing contract](context.md#route-supplied-evidence) for findings.

Send mutations as JSON on standard input. Include the revision returned by the previous operation. Read fresh status after a stale revision.

| Operation | Additional fields |
| --- | --- |
| `plan` | `purpose`, `sources`. Give exact source references or bounded HTTPS paths ending in `/`. A named interview can be a source. |
| `propose` | `source_scope`, one router `sources` item and one company `entries` item. Include the locator and a short excerpt. |
| `gap`, `defer` | `question`, `why`, `next_action`, `resume_when` |
| `resolve` | The exact open `question`, after reviewing a proposed answer |
| `approve`, `accept`, `finish` | Revision only |

An approved channel search might return message permalinks outside its URL path. Show those references and agree on a revised source plan before reading them.

This example starts with `company-onboarding plan` in a fresh Studio.

```json
{"revision":0,"purpose":"Find which customer segments the company serves or is considering.","sources":["Company overview deck"]}
```

Show the plan. After the PM approves it, send `{"revision":1}` to `company-onboarding approve`. Inspect the deck, then send one finding to `company-onboarding propose`.

```json
{
  "revision": 2,
  "source_scope": "Company overview deck",
  "sources": [{
    "reference": "Company overview deck", "date": "2026-01-12",
    "coverage": "partial", "checked_on": "2026-01-16",
    "text": "Enterprise is an opportunity we are exploring."
  }],
  "entries": [{
    "scope": "company", "topic": "direction", "source": 1, "location": "Slide 4",
    "quote": "Enterprise is an opportunity we are exploring."
  }]
}
```

> The deck describes enterprise as a segment you're exploring. Shall I save that wording?

If the PM agrees, send `{"revision":3}` to `company-onboarding accept`. Use the actual returned revision and dates in a live session.

Use `propose` for one finding from an approved source. Show its wording, attribution and anything that would change its meaning. Offer to save, correct, or leave it open. Preview a correction again. Use `accept` for the specific finding the PM agreed to save. Acknowledging what a deck says leaves any strategic choice with its owner.

Use `defer` for a pending finding or `gap` for a material unknown. Keep the question, its consequence, a feasible next action and a revisit cue. Offer a source check when relevant new evidence arrives or the PM reaches the agreed cue. Skip unsolicited offers in quiet mode.

To resolve a gap, propose the sourced answer with `answers` set to the exact question. When the PM confirms the answer, call `resolve` while it is pending. This saves it and closes the gap.

Read `walkthroughs.company.next_topic` from `pm.py onboarding status`. Discuss that topic and establish its disposition with the PM.
Run `pm.py onboarding review-topic` with the onboarding revision, stage, topic, outcome and PM reply.

| Field | Value |
| --- | --- |
| `revision` | Current revision from `onboarding status`. The company source plan has a separate revision. |
| `stage`, `topic` | `company` and the current topic ID from `next_topic`. |
| `outcome` | `reviewed`, `open`, or `not_applicable`. |
| `pm_reply` | The PM’s actual reply about this topic. |

If the PM says “I don’t know our margins,” the economics topic can remain open.
Save its next evidence check with `gap` if the PM agrees.
Use `finish` to end a source capture round. A pause preserves the next topic for a later conversation.

After all five topics, acknowledge the company pass and keep the PM and product stages pending until their workflows exist.
After onboarding, revisit an open item when it matters to the requested work. See [goal alignment](framework.md#goal-alignment) for strategy.
