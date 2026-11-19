---
name: manage-backlog
description: Capture product signals, evaluate initiatives, review backlog limits and overdue items, record deferral proposals, or follow delivery and outcomes.
---

# Manage the backlog

Read [the initiative workflow](../../../playbook/opportunities.md), company context, product context, and the product's current goals. Run `initiative schema` before preparing transactions.

Record only areas supported by an explicit source or a PM decision. Put their qualified subjects in the initiative's `areas` field.
For product-wide work, omit `areas`. Use sourced `set-areas` to replace existing links. Read cited area evidence with `area-context PRODUCT AREA`.

## Capture and evaluate

1. Search `backlog --product PRODUCT --all-phases` for the source, problem, and audience. Include deferred and closed work.
2. If the same observation is already recorded, return its initiative ID. Use `signal` for new evidence about that problem.
3. For a possible new problem, propose `capture` with the observed date and source locator.
4. Use `describe` for the supported problem, audience, and intended outcome. Leave missing facts open.
5. For `evaluate`, put `value`, `strategic_fit`, `urgency`, `sources`, and `unknowns` inside the `evaluation` object. Cite locators already captured on this initiative.
6. Identify which unknown could change the next decision. State when customer value, urgency, or strategic fit remains unverified.

| Evidence and decision | Next action |
| --- | --- |
| A material unknown justifies a timebox | Prepare [discovery](../run-discovery/SKILL.md) for PM review. |
| Evidence supports defining the investment | Prepare the [Initiative Brief](../define-initiative/SKILL.md) under the same ID. |
| Work can wait | Propose `defer` with the reason and a date or event for review. |
| Further investment has no current justification | Propose `decline` with the PM's reason and source. |

Use `initiative propose` to validate changes. For each new ID, review `intake_reviews` with the PM when the product already has work.
The shortlist includes up to five existing initiatives. It compares wording and confirmed areas across all phases. Other initiatives can describe the same problem.

Read the closest records with `initiative show`. Search the full backlog when the shortlist misses the likely owner.
For a shared problem, propose `signal` on its existing ID. For a distinct problem, the PM supplies `--confirm-distinct NEW_ID` when signing.
Leave uncertain ownership in the proposal, including in quiet mode.

## Reassess

The default backlog contains uncommitted work. Use `--phase` to inspect a specific status. Use `--due` for dated reviews across phases.
Read deferred items separately for event triggers. A dated review cannot detect a customer renewal or a change in obligations.

Review active discovery weekly against its learning goals. At the open-item limit, review existing work with the PM before adding another initiative.
Use `signal` for new evidence and `reopen` for a decision to reconsider an existing initiative.

## Deliver and learn

1. Confirm delivery scope and the tracker URL with the owner. Include the initiative ID in the handoff.
2. Propose `start-delivery` after implementation starts. Use `expedite` for a verified critical exception.
3. Propose `ship` after release verification. Name a review date and cite the release evidence.
4. Follow the [release evidence procedure](../../../playbook/outcome-evidence.md). Check success measurements and guardrail readings against their approved windows.
5. Sign corrections against the original reading. Retain the source and cite any comparable replacement.
6. Propose `review-outcomes` with the PM's assessment for each target. Explain each breached or unavailable guardrail.
7. Use `unmeasured` when no usable reading exists. Schedule a dated `follow_up` for pending evidence.
8. Check `backlog --due` for material evidence. Cite changed observations before closing or rescheduling.
