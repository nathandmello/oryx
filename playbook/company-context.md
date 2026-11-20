# Walk through company context

An ordinary request starts or resumes onboarding. Acknowledge it and keep it for after the walkthrough.
With hooks disabled, run `python3 tools/pm.py onboarding status` yourself before starting PM work.

Onboarding covers company, PM, then product context. Completion means the PM has reviewed each framework with oryx once.
Company is the first available walkthrough. The PM and product frameworks are pending design.
Use existing records to prepare each discussion. Saved context alone leaves the walkthrough pending.

## Start where the PM is

Connect the first question to what the PM has already said. Ask one question at a time.

> **Founder:** It’s just me. I have an idea for independent clinics.
>
> **Oryx:** What got you interested in clinics?

The speaker’s own account can be the first source. Ask before capturing it. Preserve who said what, when, and how they know.
If the PM already has a brief, offer to use it. They can also write directly or share an excerpt.

Learn where this company keeps information before suggesting a tool. Offer public research or a connected source when useful.
Agree on the question, source scope and what you will bring back. Ask before expanding the search.

## Decide what to capture

Discuss the [five company topics](company-frameworks.md) in order. Adapt each opener to what exists today and what this person knows firsthand.
Reflect relevant evidence and invite correction. A PM can leave every topic open or mark a topic inapplicable.

Document choices already made and options the PM mentions. Leave future decisions open. When an answer exists elsewhere, agree how to find it.

Keep business implications in the overview when they explain a segment, the portfolio, economics, growth or a strategic choice.
When a PM mentions product-market fit, clarify whether the priority applies to the company or one product.
Evidence about how a particular offering serves that market belongs with the product. See [scope and authority](context.md#scope-and-authority).

Give recurring detail a [supplementary company note](filing.md#when-a-file-earns-its-place) when it has its own reader need and review trigger. Show the proposed link and its purpose. Add it to the overview with the PM’s approval. Keep product detail with its product.

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

Show one finding with its wording, attribution and qualifications. Offer to save it, correct it, or leave it open.
Preview corrections. Accept only wording the PM approves. The PM retains each strategic choice.

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

Use `finish` to end a source capture round. A pause preserves the next walkthrough topic.

## When the PM brings back new learning

A company update can happen between walkthroughs or after onboarding. Keep the completed pass.
If a founder brings a pilot call, check which open question it informs. Offer to review any business implication in their wording.
Leave product-specific findings at the source until the PM agrees to capture them with the product. A company review only approves the company entry.

Keep product work on hold until the PM and product walkthroughs are complete. Then check the needs of the requested activity.
See [goal alignment](framework.md#goal-alignment) for strategy.
