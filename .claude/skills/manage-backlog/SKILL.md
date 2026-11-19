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
3. For a distinct problem, propose `capture` with the observed date and source locator. Resolve uncertain ownership with the PM.
4. Use `describe` for the supported problem, audience, and intended outcome. Leave missing facts open.
5. For `evaluate`, put `value`, `strategic_fit`, `urgency`, `sources`, and `unknowns` inside the `evaluation` object. Cite locators already captured on this initiative.
6. Identify which unknown could change the next decision. State when customer value, urgency, or strategic fit remains unverified.

| Evidence and decision | Next action |
| --- | --- |
| A material unknown justifies a timebox | Prepare [discovery](../run-discovery/SKILL.md) for PM review. |
| Evidence supports defining the investment | Prepare the [Initiative Brief](../define-initiative/SKILL.md) under the same ID. |
| Work can wait | Propose `defer` with the reason and a date or event for review. |
| Further investment has no current justification | Propose `decline` with the PM's reason and source. |

Use `initiative propose` to validate changes. The PM reviews and signs them. In quiet mode, complete the requested task without unsolicited advice.

## Reassess

The default backlog contains uncommitted work. Use `--phase` to inspect a specific status. Use `--due` for dated reviews across phases.
Read deferred items separately for event triggers. A dated review cannot detect a customer renewal or a change in obligations.

Review active discovery weekly against its learning goals. At the open-item limit, review existing work with the PM before adding another initiative.
Use `signal` for new evidence and `reopen` for a decision to reconsider an existing initiative.

## Deliver and learn

1. Confirm delivery scope and the tracker URL with the owner. Include the initiative ID in the handoff.
2. Propose `start-delivery` after implementation starts. Use `expedite` for a verified critical exception.
3. Propose `ship` after release verification. Name a review date and cite the release evidence.
4. Propose each `measurement` against its existing target and metric ID. Cite the observed result.
5. Capture a distinct follow-up problem through intake. Link the release or outcome review as its source.
