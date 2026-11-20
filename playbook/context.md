# Company, PM, product, product area, and initiative context

Use [the starters](../templates/README.md) for recurring reference.

## Scope and authority

Keep standing company facts and commitments in `studio/context/company/overview.md`. Link separately maintained reference notes.

Link product context to its company. Area and initiative briefs inherit their product. Record each decision and exception under its owner.

For a single-product startup, the chosen market and business model belong to the company.
Customer problems, usage and product-market fit evidence belong with the specific product and segment.
For a mixed source, review each claim under its owner. Link the evidence when a separate company implication matters.
Ask the PM when ownership or the implication is unclear.

Keep inherited commitments in force. Cite the decision owner’s approval for any exception. Follow [evidence reviews](evidence-reviews.md) for conflicts and changed assumptions.

Link existing goals, research, and delivery details. Apply [the filing rules](filing.md) before creating a note.

## Make the brief usable

- Explain each guardrail and the action it changes.
- Keep local terms with their meanings, owners, and misleading alternatives.
- Record each closed decision’s question, scope, owner, date, evidence, rationale, and next step.
- Link an approved example or use a permitted excerpt. Pair recurring mistakes with their corrections.
- Put data boundaries first when access is sensitive. For regulated work, list permitted inputs and name the review roles and approval gates.
- State material gaps in place. Trim stale material. One-off work can stay in the reply.

| Product type | Emphasis |
| --- | --- |
| Customer-facing SaaS | Buyer and user jobs, account vocabulary, plan entitlements |
| Internal tool | Teams, savings in their measures, dependent systems and owners, prior decisions |
| Platform or API | Integrators and buyers, resource model, versioning, compatibility, approved interface or deprecation examples |
| Regulated or safety-relevant | Applicable obligations, internal owners, dated approvals, permitted inputs, review path |

For company work, emphasise binding policies, exclusions, and shared terminology. For initiatives, capture reusable rules and approved scope. Keep plans and release progress in the workspace.

## PM remit

The PM profile is `studio/context/pm/context.md`. Manage [reply preferences](working.md#reply-preferences) with oryx commands.
Keep captured preferences as context.

Use the PM’s own description of their responsibilities. Saving a remit provides material for the [onboarding walkthrough](company-context.md).
For a fresh profile, use `python3 tools/pm.py new pm-context context/pm/context.md`.

Ownership in `## PM remit` guides routing. The PM can edit it directly. For example:

```markdown
## PM remit

Status: confirmed

| Responsibility | Role | Goals | Depends on |
| --- | --- | --- | --- |
| product/checkout/area/refunds | owner | | product/billing |
| product/checkout/area/receipts | shared | | |
| product/catalogue | owner | | |

| Follow |
| --- |
| topic/industry-benchmarks |
```

Separate multiple values within a cell with `<br>`. Resolve local goal links from the profile file. Agents can update remit fields with `pm.py set-remit` using JSON on standard input. Preserve surrounding prose.

| Remit case | Agent action |
| --- | --- |
| New or changed responsibilities | Ask which products or named areas the PM owns or shares. Confirm each area's parent. Retain existing goals, dependencies, and interests. |
| Invalid saved remit | Report the validation error; keep the file for repair. Continue capture with unknown PM responsibilities. |
| More scope to add | Save `draft`; ask what is missing. |
| PM confirms scope, including no current responsibilities | Save `confirmed`. |
| Whole product | Apply the role to its areas. An explicit area role takes precedence there. |
| Narrowed ownership | Replace the former whole-product entry with the confirmed areas. Preserve unrelated roles. |
| One area | Use that area's role. Parent and sibling news needs a confirmed consequence for the area to count as affected. |
| Follow or dependency | A whole product includes its areas. Use `affects` for a confirmed consequence. |

## Route supplied evidence

[Ingestion](../.agents/skills/ingest-context/SKILL.md) applies automatically. Use `python3 tools/pm.py route-context` with JSON on standard input. Preview first. Write one authorised record per `--write PATH` call.

Apply the [section rules](filing.md#when-a-section-earns-its-place). Retain controls, sources, and work state.

```json
{
  "sources": [
    {"reference": "Fictional approved minutes, section 3", "date": "2026-01-01", "coverage": "read", "checked_on": "2026-01-01"},
    {"reference": "Fictional UK rollout announcement", "date": "2026-06-15", "coverage": "read", "checked_on": "2026-06-15"}
  ],
  "entries": [
    {"scope": "pm", "topic": "preferences", "question": "How does the PM prefer to review a roadmap?"},
    {"scope": "company", "topic": "constraints", "source": 1, "location": "Section 3", "quote": "We will not create or own LLMs."},
    {"scope": "company", "heading": "UK merchant adoption before rollout", "lead": "Consult when comparing UK merchant adoption across the portfolio before and after rollout.", "source": 2, "location": "Paragraph 1", "quote": "On 31 May, we had 2,000 active UK merchants across all our products."},
    {"scope": "product", "product": "checkout", "topic": "vocabulary", "source": 1, "location": "Section 3", "quote": "A workspace is the boundary for shared access.", "term": {"name": "workspace", "owner": "Product", "avoid": "account"}},
    {"scope": "initiative", "product": "checkout", "initiative": "renewals", "topic": "decisions", "source": 1, "location": "Section 3", "quote": "We use existing sessions because renewal needs no new login.", "decision": {"question": "How do users authenticate?", "scope": "Renewal pilot", "person": "Fixture PM", "date": "2026-01-01", "next_step": "Brief the pilot team."}}
  ]
}
```

## Brief routing topics

| Scope | Topics |
| --- | --- |
| Company | `organisation`, `markets`, `business-model`, `portfolio`, `growth`, `direction`, `operations`, `constraints` |
| Product | `offer`, `vision`, `purpose`, `customers`, `contribution`, `ownership`, `constraints`, `goals` |
| Initiative | `outcome`, `workflow`, `constraints` |
| PM | `background`, `preferences`, `stakeholders`, `context` |
| Shared | `vocabulary`, `decisions`, `examples`, `data-boundaries`, `reviews` |

Use `context` for other PM facts. Update confirmed ownership separately.

Supply `product_area` for an evidenced product or initiative area. Use `scope: area` and `subject: area/<slug>` for unqualified responsibilities. Confirm the parent before assigning one. Other reference topics use `reference` with `subject: topic/<slug>`.

Deferred scopes are `delivery`, `detail`, and `unclear`.

File new initiative guidance in `context/products/<product>/initiatives/<initiative>/overview.md`. Reuse an older brief linked to the same product.

Base local Markdown source links on the private repository root. Each inspection date retains its source ID.

Number sources from one. Mark coverage `read`, `partial`, or `unavailable`. Omit `checked_on` for unavailable sources.

Supply permitted inspected `text` for pasted material or extracts.

The router checks excerpts and commitments against available text. Defer irrelevant commitments. Report excerpt-only checks.

Preserve the source wording and locator. Use `interpretation` for an inference. Attach an open `uncertainty` to qualify a sourced claim.
For interviews, cite the speaker, discussion, date, and their words. Keep conflicting accounts attributed in their owning brief.

Check material quantities using [the numerical evidence procedure](numbers.md). Keep unverified figures as reported claims.

For an authorised replacement, add `supersedes` with the earlier local `source` ID and exact `entry` text or decision question. Cite dated replacement evidence in the same scope.

Use `question` for an unknown. Cite new evidence with `answers` to resolve the exact question.

Preview a decision first. Show the PM the choice, original decision owner, scope, evidence, and next step.
Offer “Record this decision” for that preview. Attach `record_decision` only when the PM selects or writes that response.

Copy `decision_revision` into `revision`. Supply the recording `pm`, confirmation `date`, discussion `reference`, and exact `reply`.
A changed choice or source needs fresh confirmation.

Omit the topic to retain an update at source. Use `affects` for confirmed effects. Record paths require reasons. New notes need parent, basis, and review trigger.

## Review and maintain

Name a maintainer and review triggers. Review closed decisions, releases, and changed sources.

Use an event-driven review or a dated deadline. Set Last reviewed after an actual review. Carry parent changes through to the affected briefs and goals.

Try the brief in a fresh task. Review fidelity, source authority, and approvals. Use [checkpoints](working.md) for unresolved work.

## Review existing context

Follow [the upgrade workflow](updates.md). Include untracked records and briefs without companions. Check incoming links.
Identify each record’s purpose and authority. Compare claims with their sources, preserving actors, exclusions, conditions, dates, and commitments.

Keep conflicts open. Ask for missing authority. Preview proposed changes and preserve unique evidence.
Back up affected records, apply authorised repairs, and verify links and citations. Confirm before deletion.

Rerun the oryx check. Record reviewed scope, remaining gaps, and inaccessible evidence in the checkpoint.

## Basis

The outlines draw on the supplied *Product Context File Templates*, [Strategyzer](https://www.strategyzer.com/library/the-business-model-canvas), [Product Talk](https://www.producttalk.org/business-fundamentals-course/), and [Roman Pichler](https://www.romanpichler.com/tools/product-vision-board/).
