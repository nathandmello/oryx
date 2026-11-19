---
name: prioritize-roadmap
description: Compare approved candidates, verify capacity, propose investment selections, or generate the roadmap.
---

# Prioritize the roadmap

For a request to see the roadmap, run `roadmap --product PRODUCT`. For an area-specific request, add `--area AREA`. Use [the view templates](../../../playbook/initiative-views.md) for exports.

For a selection decision, read [the initiative workflow](../../../playbook/opportunities.md). Load the product strategy, current objectives, obligations, existing commitments, and each candidate's evidence.

Before selection, use the [conversation guide](../../../playbook/conversation.md) to establish outcomes and what would lose capacity.

## Compare investments

1. Find approved options with `backlog --product PRODUCT --phase candidate`. Read each initiative with `initiative show`.
2. Agree the planning period, available capacity, effort unit, and intended outcomes with the PM and accountable owners.
3. Identify how each option supports acquisition, retention, expansion, margin, obligations, product health, or strategic advantage.
4. Cite the buyer, customer, engineering, or financial evidence. Distinguish commercial exposure from attributable impact. Mark estimates and unresolved claims.
5. Compare customer benefit, urgency, confidence, effort, risk, dependencies, and reversibility. Identify which existing commitment or alternative would give way.
6. Open the [planning comparison](../../../templates/prioritization.md) named for the cycle ID. Keep incomplete comparisons in draft.
7. Under `Comparison`, use the columns `Initiative ID` and `Assessment`. Include each proposed cycle option exactly once.
8. With one eligible option, compare it with existing commitments or keeping capacity available. Record that alternative in prose.

## Record the decision

Propose the cycle with its approved option IDs. For each selected initiative, propose a `decision` with action `plan`, rank, horizon, effort, and trade-off.
Use `initiative propose` to validate the proposal. Generate the roadmap after the PM signs the selections.

Before delivery starts, propose `unplan` to release capacity and return the same approved initiative to the candidate pool.
The PM can review the release and revised selections in one proposal.

Held candidates remain eligible. Propose reopening an initiative when new uncertainty could change the investment decision.
