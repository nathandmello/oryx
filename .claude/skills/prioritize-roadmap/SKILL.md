---
name: prioritize-roadmap
description: Help the PM compare investments and choose trade-offs, or display a roadmap from approved selections.
---

# Prioritize the roadmap

For a request to see the roadmap, run `roadmap --product PRODUCT`. For an area-specific request, add `--area AREA`. Exports use the selected [roadmap view](../../../playbook/customization.md#roadmap-data-and-views).

For a new roadmap, start with the PM’s existing choices. Help them work through the next open trade-off.
Draft from their reasoning and review the wording together. A deadline can change the [pace](../../../playbook/working.md#modes).

For a selection decision, read [the initiative workflow](../../../playbook/opportunities.md). Load the product strategy, current objectives, obligations, existing commitments, and each candidate's evidence.

Before selection, use the [conversation guide](../../../playbook/conversation.md) to establish outcomes and what would lose capacity.
When an option ranks highly, ask which existing commitment would move if the team took it on.
Use the PM's comparison method. Show how a changed estimate affects the order. The PM selects the trade-off.
If company context calls a market an opportunity, carry that wording forward until its strategic priority is confirmed.

## Compare investments

1. Find approved options with `backlog --product PRODUCT --phase candidate`. Read each initiative with `initiative show`.
2. Agree the planning period, available capacity, effort unit, and intended outcomes with the PM and accountable owners.
3. Identify how each option supports acquisition, retention, expansion, margin, obligations, product health, or strategic advantage.
4. Cite the buyer, customer, engineering, or financial evidence. Distinguish commercial exposure from attributable impact. Mark estimates and unresolved claims.
5. Compare customer benefit, urgency, confidence, effort, risk, dependencies, and reversibility. Identify which existing commitment or alternative would give way.
6. Open the planning comparison for the cycle. Create a missing comparison with the [draft command](../../../templates/README.md#create-a-draft). Keep incomplete comparisons in draft.
7. Under `Comparison`, use the columns `Initiative ID` and `Assessment`. Include each proposed cycle option exactly once.
8. With one eligible option, compare it with existing commitments or keeping capacity available. Record that alternative in prose.

## Record the decision

Propose the cycle with its approved option IDs. For each selected initiative, propose a `decision` with action `plan`, rank, horizon, effort, and trade-off.
Use `initiative propose` to validate the proposal. Generate the roadmap after the PM approves the selections.

Before delivery starts, propose `unplan` to release capacity and return the same approved initiative to the candidate pool.
The PM can review the release and revised selections in one proposal.

Held candidates remain eligible. Propose reopening an initiative when new uncertainty could change the investment decision.
