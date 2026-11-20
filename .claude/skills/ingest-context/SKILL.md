---
name: ingest-context
description: Use for company or PM onboarding and requests to capture, file, update, or reconcile context, including existing briefs, mixed evidence, and open questions.
---

# Ingest context

Use the [company](../../../playbook/company-context.md) or [PM walkthrough](../../../playbook/pm-context.md). Carry open questions forward.
Apply the [context rules](../../../playbook/context.md) and [conversation guidance](../../../playbook/conversation.md) across captures.

For initiative meetings, use the transcript retrieval and summary workflow in [summarize-meeting](../summarize-meeting/SKILL.md). Route reusable findings with this skill.

When a release flags older records, follow [the context cleanup procedure](../../../playbook/context.md#review-existing-context) before using an affected brief. Surface legacy conflicts during ordinary capture.

## Inspect

- Read `studio/context/pm/context.md` when present. Use PM-confirmed responsibilities, goal links, dependencies, and interests.
- Replace superseded roles when the PM confirms a change. Preserve unrelated entries and save the agreed scope with `pm.py set-remit`.
- Find the existing record and accountable owner. Compare new evidence with accepted decisions.
- Read applicable data boundaries before opening, transferring, or quoting sensitive source material.
- For area work, run `pm.py area-context PRODUCT AREA`. Read the listed records and their local citations.
- Read parent briefs for inherited rules. Resolve conflicting authority before applying an exception.
- Inspect permitted material in each supplied source. Record coverage as read, partial, or unavailable.
- Supply inspected plaintext in each source’s `text` field when permitted. Use a private-root-relative link for a local source.
- Split source evidence by claim. Leave omissions open. Clarify material gaps.
- Use [check-numbers](../check-numbers/SKILL.md) for material figures. Keep an unverified metric identifiable as a reported claim.
- Keep actors, negation, conditions, exceptions, numbers, and locators. Record material implications with [evidence reviews](../../../playbook/evidence-reviews.md).
- Inspect `risk_preview`. State material warnings in quiet mode. File risk history with the authorized source record.
- Quote each material claim, commitment, and explicit exclusion. Preserve its scope and time.
- Attribute hypotheses to their owners in `interpretation`. Keep tentative wording, open questions, and each observation’s original scope.
- Flag proposals, uncertain authority, and conflicts for review.

## Route

- Choose the purpose first. Put reusable context under its entity in `context/`. Put plans, experiments, and other work in `workspace/`. Use the remit to explain why the item matters.
- Keep the company overview focused on the market, business model, portfolio and company choices. Link to detailed records.
- File product-market fit evidence with the offering and segment. Confirm any separate company implication before recording it.
- Keep product information with its product. Set `product_area` for area-specific product or initiative claims, questions, and answers.
- Route standing area guidance to its maintained area brief. Start inline until the [area filing test](../../../playbook/filing.md#product-area-context) passes.
- Route PM facts with `scope: pm`. Confirm ownership changes separately. File relationships in the [stakeholder map](../../../playbook/stakeholders.md).
- Use `area` for cross-product responsibilities and `reference` for other topics the PM values.
- Put reusable initiative guidance in its context brief. Keep plans and progress in the initiative’s workspace.
- Surface a sibling product update as an FYI when relevant. Flag its concrete effect on an owned product.
- Keep the original source with its owner. Save a product-specific implication separately with its citation when requested.
- Reuse a suitable record. Apply [the filing test](../../../playbook/filing.md) before creating a file. Supply its parent, basis, reader need, and review trigger.
- Apply the [section rules](../../../playbook/filing.md#when-a-section-earns-its-place) inside the owning record. Check its parent for overlapping claims.
- Give a new or revised section a brief lead. Name what it covers and when a PM would read it.
- Use a custom heading for a distinct lookup. Preserve the date and scope of event evidence.
- Reuse an existing topic folder whenever its reader question fits. Apply the filing limits before naming another.
- Use delivery for requirements and design. Use detail to retain the source. Use unclear when ownership needs review.
- Record a specific open question where its answer matters. Supply an answer only when an excerpt resolves it.
- Capture actionable rules. Use vocabulary and decision fields for structured entries. Link permitted examples from actual work.
- Confirm the specific choice with the PM before recording a decision. Preserve its owner, scope, rationale and next step.

## Apply

- Review onboarding findings with the current stage’s capture command. For ordinary capture, preview `route-context`. Inspect routes and source coverage.
- Run `route-context --write PATH` for one authorised record at a time. Use an existing artifact's workflow for other records.
- Use the PM's approved source scope. Seek separate permission to expand the search or save generated content.
- Report FYIs in chat. An unmatched topic leaves involvement open. Save out-of-scope items only on request.
- Keep ingestion diagnostics in the reply. A lasting note needs a distinct purpose and authorisation.
- Keep earlier facts and open questions visible. Report conflicts before replacing accepted content.
- Remove unused sections and stale material during an authorised review. Tie the review to a decision, release, or source change.
- Report the path written, source coverage, verification from `source_checks`, deferred entries, open questions, and checks run. State any limits on claim review.
- Capture can yield a usable draft with open questions. Request review when an unresolved item affects a decision.
