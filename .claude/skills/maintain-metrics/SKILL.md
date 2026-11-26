---
name: maintain-metrics
description: Use when the PM asks to define, review, or change a business metric or adopt a company or product calculation.
---

# Maintain metric definitions

Read [the registry procedure](../../../playbook/metrics.md) and [the numerical evidence procedure](../../../playbook/numbers.md).

Use the [conversation guide](../../../playbook/conversation.md) when a metric choice changes a consequential product decision.

1. Find the current definition and its scope with `pm.py metric list` or `pm.py metric show`.
2. Compare the proposed formula, population, unit, period, and exclusions with the current definition.
3. Confirm the cutoff and set `reporting_window` when the definition specifies a fixed basis.
4. Resolve differences that can change a decision. Confirm the owner, effective date, and approval source.
5. Preview the definition with `pm.py metric set`. Apply the confirmed change with `--write`.
6. Use `metric show` to verify the resulting reference. Identify any comparisons or approved targets that need review.

Use `company.<metric>` for an official company calculation. Record what-if assumptions under `scenario.<name>` and cite the original revision with `based_on`.
Link to the registry from working records. Preserve source definitions when reporting third-party figures.
