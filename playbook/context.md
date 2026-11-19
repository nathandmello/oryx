# Company, product, product area, and initiative context

Context supports recurring work. Keep facts, rules, examples, and open questions that change the work. Use [the starters](../templates/README.md) and cut unused sections.

## Scope and authority

Keep standing company facts and commitments in `workspace/context/company.md`. Link time-bound developments and detailed records.

Link product context to its company. Area and initiative briefs inherit their product. Apply [the area filing rules](filing.md#product-area-context). Each level records the decisions, exceptions, and practical details it owns.

Apply more specific guidance within its authority. Keep inherited commitments in force. A new exception needs evidence of approval from the decision owner.

Reuse authoritative records for goals, research, and delivery details. Apply [the filing rules](filing.md) before creating any supporting note.

## Make the brief usable

- Write instructions that change a decision, a word, or an action. Include the reason for a guardrail.
- Keep local terms with their meanings, owners, and misleading alternatives.
- Keep closed decisions with the question, scope, named decision-maker and date, evidence and rationale, and the next step.
- Link an approved working example or include a permitted excerpt. Put a recurring mistake beside the concrete example that resolves it.
- Put data boundaries first when access is sensitive. For regulated work, list permitted inputs and name the review roles and approval gates.
- Keep known gaps where they matter. Trim stale material and inherited detail. One-off work can use a short brief in the reply.

| Product type | Emphasis |
| --- | --- |
| Customer-facing SaaS | Buyer and user jobs, account vocabulary, plan entitlements |
| Internal tool | Teams, savings in their measures, dependent systems and owners, prior decisions |
| Platform or API | Integrators and buyers, resource model, versioning, compatibility, approved interface or deprecation examples |
| Regulated or safety-relevant | Applicable obligations, internal owners, dated approvals, permitted inputs, review path |

For company work, emphasise binding policies, exclusions, and shared terminology. For initiatives, emphasise the outcome, scope, dependencies, and release evidence.

## PM remit

Ask once about missing or unfinished ownership when questions are welcome. Accept deferral. Save PM-confirmed scope with `python3 tools/pm.py set-remit` using JSON on standard input.

```json
{
  "status": "confirmed",
  "responsibilities": [
    {"subject": "product/checkout/area/refunds", "role": "owner", "goals": [], "depends_on": ["product/billing"]},
    {"subject": "product/checkout/area/receipts", "role": "shared", "goals": [], "depends_on": []},
    {"subject": "product/catalogue", "role": "owner", "goals": [], "depends_on": []}
  ],
  "follow": ["topic/industry-benchmarks"]
}
```

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

New captures start with the sections they use. Add sections as new evidence warrants them. Retain the context controls, sources, and work state.

```json
{
  "sources": [
    {"reference": "Fictional approved minutes, section 3", "date": "2026-01-01", "coverage": "read", "checked_on": "2026-01-01"}
  ],
  "entries": [
    {"scope": "company", "topic": "constraints", "source": 1, "location": "Section 3", "quote": "We will not create or own LLMs."},
    {"scope": "product", "product": "checkout", "topic": "vocabulary", "source": 1, "location": "Section 3", "quote": "A workspace is the boundary for shared access.", "term": {"name": "workspace", "owner": "Product", "avoid": "account"}},
    {"scope": "initiative", "product": "checkout", "initiative": "renewals", "topic": "decisions", "source": 1, "location": "Section 3", "quote": "We use existing sessions because renewal needs no new login.", "decision": {"question": "How do users authenticate?", "scope": "Renewal pilot", "person": "Fixture PM", "date": "2026-01-01", "next_step": "Brief the pilot team."}}
  ]
}
```

## Brief routing topics

| Scope | Topics |
| --- | --- |
| Company | `organisation`, `markets`, `business-model`, `direction`, `operations`, `constraints` |
| Product | `offer`, `vision`, `purpose`, `customers`, `contribution`, `ownership`, `constraints`, `goals` |
| Initiative | `outcome`, `workflow`, `constraints` |
| Shared | `vocabulary`, `decisions`, `examples`, `data-boundaries`, `reviews` |

For product or initiative context, add `product_area` when the evidence identifies an area of its product. Use `scope: area` and `subject: area/<slug>` for an unqualified responsibility. Ask before assigning an existing unqualified area to a product. For another reference topic, use `reference` with `subject: topic/<slug>`.

Deferred scopes are `delivery`, `detail`, and `unclear`.

Use established slugs. New initiatives use `products/<product>/initiatives/<initiative>/context.md`. Existing product headings still accept their original topics.

Base local Markdown source links on the private workspace root. Each distinct inspection date retains its own source ID.

List each source with coverage `read`, `partial`, or `unavailable`. Omit `checked_on` for unavailable sources. Source numbers start at one.

Supply permitted inspected `text` for pasted material or extracts. Read local Markdown and text links from the workspace root.

The router checks literal excerpts and common commitment sentences against available text. Route an irrelevant commitment as deferred. Report excerpt-only checks explicitly.

Use exact single-line quotes and locators. Provide `rule` for an actionable instruction or `interpretation` for a sourced implication. Cite evidence for factual claims.

Use `question` for an unknown. Cite new evidence with `answers` to resolve the exact question. Keep vocabulary and decision rows in their dedicated tables.

Omit the topic to keep an update at its source. Use `affects` for confirmed effects. For existing records, supply the path and reason. A new supporting record also needs its parent, basis, and review trigger.

## Review and maintain

Set a maintainer and concrete triggers before active use. Review when a decision closes, a release ships, or a material source changes.

Use an event-driven review or a dated deadline. Set Last reviewed after an actual review. Carry parent changes through to the affected briefs and goals.

Try the brief in a fresh task. Add what the worker had to ask. Cut what they never needed. Use [checkpoints](working.md) for unresolved work.

The checker validates structure, source references, parent links, decision rows, and review fields. Assess fidelity, source authority, approvals, and current evidence during review.

## Review existing context

Follow [the upgrade workflow](updates.md). Review older briefs, including those without companions.

List briefs, loose notes, sources, and incoming links. Include untracked notes.

Establish each record’s purpose and authority from its contents.

Compare material claims with the available originals clause by clause. Restore actors, exclusions, conditions, dates, and positive commitments within their documented scope.

If evidence is inaccessible or conflicts, record the specific question and affected claim. Keep decisions open until the evidence supports them.

Show what to retain, merge, reroute, or retire, with reasons and affected links. Keep substantive events and unique evidence where they belong.

Back up affected files. Apply authorised repairs, including links and citations. Use a verified filing plan for reversible folds. Ask before permanent removal.

Rerun the Hub check and compare the repaired claims with their sources. Record the review scope and open questions in the existing checkpoint.

Report remaining gaps and unavailable evidence.

## Basis

Based on the supplied *Product Context File Templates* and PM Hub's existing context and ownership rules.

The company and product outlines also draw on [Strategyzer](https://www.strategyzer.com/library/the-business-model-canvas), [Product Talk](https://www.producttalk.org/business-fundamentals-course/), and [Roman Pichler](https://www.romanpichler.com/tools/product-vision-board/).
