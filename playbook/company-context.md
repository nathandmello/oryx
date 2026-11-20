# Bring oryx up to speed on the company

The first win is a company overview the PM recognises and can correct. A partial overview can guide future conversations.

## Start where the PM is

If the PM has already shared context, pick up there. Otherwise, open with one easy question.

> What does your company do?

Follow their answer. If they mention a deck, offer to work from it. If they prefer talking, ask one relevant question at a time. They can also write directly or supply an excerpt. Attribute an interview answer to the speaker, date and discussion.

Learn how this company shares information before suggesting a tool. Offer public research or a connected internal source when it helps. Agree on the question, the source or search boundary, and what you will bring back. A connector's availability says nothing about permission. Ask before expanding the plan. Keep work moving with available sources if one is unavailable.

## Decide what to capture

Use the [five company questions and framework guide](company-frameworks.md) to choose evidence and one relevant follow-up.

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

Before pausing, check which of the five questions still matters to the PM. Offer one practical next check and retain its agreed cue.

Use `finish` when the PM is ready to leave this capture round. On return, bring back one relevant change or open question. Offer [product context and remit](framework.md#product-context-and-remit) when the PM is ready.
