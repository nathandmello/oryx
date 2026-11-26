# Understand the product today

## Step 3. Review the parent product

After [PM and stakeholder context](pm-context.md), start with the product in the PM’s confirmed remit. If they own a plugin, start with its parent.

> You mentioned you own the Salesforce plugin for Analytics. What does Analytics help people do today?

Read `pm.py onboarding status`. Use the team’s terminology and preserve who owns what. Ask which parent they mean if a name is ambiguous.
When several products qualify, record the PM’s choice with `onboarding select-product`. Supply the current revision, parent `subject`, and actual `pm_reply`.
If the PM confirms they have no assigned product, use a null subject and review what applies.

Cover six topics at product level. Draw on what the PM already shared and explore one detail at a time.

| Topic | What belongs here |
| --- | --- |
| Purpose | What the product enables today, why it exists, where it fits in the company, and existing direction or commitments. |
| Customers | Who uses it, who buys or chooses it, the job they need done, their alternatives and desired outcomes. |
| Experience | A real journey through the product, including access, capabilities, integrations and friction. |
| Business value | How the product is intended to contribute, including distribution, retention, revenue, costs or value to an internal team. |
| Performance | What happened, for whom and when. Check the metric definition, baseline, result, source and limitations. |
| Operating environment | Market alternatives, team responsibilities, decision rights, dependencies, constraints and existing commitments. |

A founder can describe an intended user and a hypothesis before launch. Attribute both. A reported customer interview establishes what that person said.
Keep expected business benefits distinct from measured performance. Preserve conflicting accounts with their sources. Offer a proportionate cross-check when it matters.

## Step 4. Offer an area walkthrough

Completing step 3 unlocks the hub, including when questions remain open. Check `area_offers` for confirmed areas under the reviewed product.
If the PM owns one, offer the choice once at handoff. A whole-product owner can finish at step 3.

> That covers Analytics. Would you like to look at the Salesforce plugin now, or leave it for later?

Start an area only after the PM chooses it. Use `onboarding select-area` with the current revision, qualified `subject`, and actual `pm_reply`.
A null subject records a skip or pause. Use `area_options` when the PM asks to return. Ordinary work stays available throughout step 4.

Review the six topics for that area. Use the parent brief as background with permission. Ask what differs for the area’s users, journey, and contribution.
Keep area results tied to their population. Confirm the team’s directory name and file area findings in their own brief.

## Optional stakeholder profiles

After the product walkthrough, offer the area choice first when it applies. Completing or deferring the area also leads to the profile option.
Offer this once at the handoff. Respect quiet or expedited requests and give waiting work priority.
For those cases, pass `offer_profiles: false` on the final topic review or area deferral.

> Would it help to start a profile for someone you work with?

The PM can start, come back later, or skip it. Send their actual reply to `onboarding profiles` with `choice` and `stakeholder_profiles.revision` as `revision`.
Use `start`, `later`, `skip`, or `finish`. An explicit request can start or resume setup after any earlier choice.

Choose one person together. Review one sourced detail at a time with the [profile guide](stakeholder-profiles.md). Resume the PM’s work when they’re ready.

## Review and save findings

Offer conversation, the PM’s own writing, or a bounded source check. Agree on purpose, sources and destinations before inspecting material.
Get fresh permission to expand the plan. Keep chat-only details in the conversation.

Run `pm.py product-onboarding status` for the capture revision. Send the plan through `product-onboarding plan`. A step 3 example follows.

```json
{"revision":0,"subject":"product/analytics","purpose":"Describe Analytics today.","sources":["PM conversation"],"destinations":["context/products/analytics/overview.md"]}
```

Show the proposed home and any brief to create. Optional plan `titles` preserve the team’s names. Use `approve` after agreement.
In step 4, use the qualified area subject and its home, such as `context/products/analytics/plugins/salesforce/overview.md`.

Name each reusable Studio brief by exact path in the agreed sources. Use `product-onboarding status --evidence` for one relevant passage.
Review its scope, date, qualifications and open reviews. An empty result leaves the question open.

Use `propose` with one inspected source and one [product entry](context.md#route-supplied-evidence). Set `product_area` for an area finding.
Show wording, citation and destination. Accept approved wording, preview edits again, or discard the draft. Read the revision after each operation.

For an existing decision, preview it with `route-context` within the approved plan. Confirm the exact decision, owner, scope and source before using `--write`.
An area decision needs an existing parent product brief. Confirm a shared area relationship before recording `shared_area` on its receiving product.

Use `defer` or `gap` for an open question. Agree on its destination, consequence, next check and revisit cue.
Use `resolve` after reviewing a sourced answer. Use `finish` to end a capture round.

Record each topic with `onboarding review-topic`. Supply the walkthrough revision, current stage (`product` or `area`), topic, outcome and actual PM reply.
Use the exact `product_scope.subject`, including null. Topics may be reviewed, open or inapplicable. When the PM brings work, retrieve its [task context](context-search.md).
