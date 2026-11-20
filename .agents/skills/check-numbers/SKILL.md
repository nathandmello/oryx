---
name: check-numbers
description: Use for material quantitative claims in any oryx task, including revenue growth, churn, forecasts, and reported metrics.
---

# Check numbers

Use [the numerical evidence procedure](../../../playbook/numbers.md). Identify the decision and the numbers that could change it.

1. Locate the primary data or calculation. Record its owner, date, and coverage.
2. Compare definitions, populations, units, periods, and reporting cutoffs. Confirm which rows belong in the numerator and denominator.
3. Check missing values, duplicates, joins, outliers, and bias where they affect the claim.
4. Recompute from available inputs. Use `pm.py check-metric` for supported calculations.
5. Reconcile differences. Ask for missing information that could change the decision.
6. Keep reported, estimated, and verified figures identifiable in the output. Record the basis and material limitations.
