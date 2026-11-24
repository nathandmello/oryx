# Understand the product today

After the [PM walkthrough](pm-context.md), pick up the product or part of a product the PM already described. Keep their original request for later.

> You mentioned you own the Salesforce plugin for Analytics. We can start with the Analytics brief, then fill in where the plugin fits. Sound good?

Use one short question when the relationship is unclear. “Healthcare” might describe a product, a customer segment, or work across several products.

## Start from the remit

Read `pm.py onboarding status` and the PM’s [confirmed remit](context.md#pm-remit). Use the team’s terminology.
For a product owner, review the product brief. For an area owner, cover the parent product and the area in one conversation.
Establish enough about the parent to explain the area’s purpose, users, journey, and contribution. Keep ownership with its confirmed subject.

When several subjects qualify, let the PM choose where to start. Record their choice with `onboarding select-product`.
Supply the current onboarding revision, the selected remit `subject`, and their actual `pm_reply`.
If they confirm they have no assigned product, use a null subject and leave inapplicable topics open for later.

## Follow six questions

Use these topics in order. Reflect what the PM or an authorised source already established. Explore one relevant detail at a time.

| Topic | What belongs here |
| --- | --- |
| Purpose | What the product enables today, why it exists, where it fits in the company, and existing direction or commitments. |
| Customers | Who uses it, who buys or chooses it, the job they need done, their alternatives and desired outcomes. |
| Experience | A real journey through the product, including access, capabilities, integrations, friction and where an area contributes. |
| Business value | How the product is intended to contribute, including distribution, retention, revenue, costs or value to an internal team. |
| Performance | What happened, for whom and when. Check the metric definition, baseline, result, source and limitations. |
| Operating environment | Market alternatives, team responsibilities, decision rights, dependencies, operating constraints and existing commitments. |

A founder can describe an intended user and a hypothesis before launch. Attribute both. A reported customer interview establishes what that person said.
Distinguish the expected business benefit from measured performance. Keep area results tied to their population. Preserve conflicting accounts with their sources.

When a claim matters, offer one cross-check. A customer account or usage report can help test a leadership claim.

## Agree on capture

Offer conversation, the PM’s own writing, or a bounded source check. Use their language for where useful material lives.
Agree on the purpose, sources and destinations before inspecting material. Get fresh permission to expand the plan.
Choose a reusable finding that answers the current question. Keep personal or chat-only details in the conversation.

When reusing a Studio brief, include its exact Studio-relative path in the agreed sources.
After approval, use `product-onboarding status --evidence` for one sourced passage relevant to the current topic.
Check its scope, timeframe, qualifications and open reviews with the PM. A company observation needs separate evidence before applying it to one product.
An empty result leaves the question open. Offer one relevant next source if it would help.

Run `pm.py product-onboarding status` for the capture revision. Send the plan as JSON through `product-onboarding plan`. For example:

```json
{"revision":0,"subject":"product/analytics/area/salesforce","purpose":"Describe how operators use the Salesforce plugin.","sources":["PM conversation"],"destinations":["context/products/analytics/overview.md","context/products/analytics/plugins/salesforce/overview.md"]}
```

Show both homes, their parent link, and any brief that would be created. Optional plan `titles` map each new brief’s path to the team’s name. Use `approve` after agreement. Read the new revision after each operation.

Use `propose` with the agreed source scope, one inspected source, and one [product entry](context.md#route-supplied-evidence).
Set `product_area` for an area finding. A product-wide fact belongs in the parent brief.

For a decision already made, preview it with `route-context` inside the approved source and destination plan.
Ask the PM to confirm the exact decision, owner, scope and source before using `--write`.
An area decision needs an existing parent product brief. Capture the agreed parent context first when that brief is missing.

If another product uses an existing area, verify the relationship with the PM.
On a sourced finding for that product, use `shared_area` with the canonical subject, such as `product/analytics/area/salesforce`.
Review that relationship in the receiving product’s brief. Later searches can follow it to the original area evidence.

> I’d save “Sales operators use the Salesforce plugin to export weekly pipeline reports” in the plugin brief. Does that capture it?

Show the wording, citation and destination. Accept their exact wording, re-propose an edit, or discard the draft if they decline retention.

For an open question, agree on its destination, why it matters, the next check, and when to revisit it.
Use `defer` or `gap` for that question. When the cue arrives, offer the agreed check. Use `resolve` after reviewing a sourced answer.
Resume only the relevant pending finding or gap. Use `finish` to close a capture round.

## Return to the work

Use `onboarding review-topic` with the walkthrough revision, stage `product`, current topic, outcome, and actual PM reply.
Include the exact `subject` from `product_scope` in the latest status, including null.
A topic may be reviewed, open, or inapplicable. The six-topic pass can finish with unanswered questions.
Check the next stage and scope on resume. Once ready, offer to return to the original request.

Use [task context](context-search.md) to retrieve what that activity needs, including applicable parent commitments and scoped area evidence.
A missing strategy objective may warrant a source check. A question about pilot performance needs the pilot’s evidence and metric definition.
