---
name: define-initiative
description: Draft or review an Initiative Brief for the existing initiative ID and prepare approval to enter the candidate pool.
---

# Define an initiative

Read [the initiative workflow](../../../playbook/opportunities.md). Use `initiative show` to read the established problem, audience, outcome, evidence, and any discovery findings. Read the linked company, product, and applicable area evidence. Keep area membership on the registered initiative.

Use the [conversation guide](../../../playbook/conversation.md) to compare credible alternatives before drafting.

1. Open the Initiative Brief for the registered initiative. Create a missing brief with the [draft command](../../../templates/README.md#create-a-draft). Enter known facts and leave gaps open.
2. Propose `prepare-brief` when the PM chooses definition. Cite the discovery findings or the evidence supporting direct definition.
3. Describe the solution, customer benefit, business value, and credible options.
4. With the PM and delivery owners, define the first increment, exclusions, rough effort, dependencies, delivery approach, rollout, and enablement.
5. Review value, usability, feasibility, and viability with the relevant owners. Give material gaps a next step.
6. Reuse a product metric. Use [the registry](../../../playbook/metrics.md) for the definition. Propose the target, baseline, date, and guardrails with sources.
7. Inspect the metric's existing experiment or linked draft with `initiative show`. Keep unknown test details empty.
8. Apply [the brief-review checks](../../../playbook/brief-review.md). Resolve gaps that block approval or return them to the PM.
9. Review the wording with the PM. After acceptance, mark the brief complete and use `initiative propose` for `approve-initiative`.
10. Hand the exact brief revision to the PM. Wait for the signed change before treating the work as a candidate.

Reopen for material changes. Keep approved source references and historical decisions visible.
