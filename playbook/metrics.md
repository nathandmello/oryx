# Business metric definitions

Use the registry for metric definitions in context, analysis, briefs, forecasts, and reviews. Cite the effective definition and the source of the observed value. Keep third-party methods identifiable when they differ.

## Read a definition

```sh
python3 tools/pm.py metric list
python3 tools/pm.py metric show logo-churn --product checkout
python3 tools/pm.py metric show logo-churn --product checkout --as-of 2026-10-01
```

The [bundled definitions](saas-metrics.json) provide documented SaaS starting points. Their formulas state assumptions. An approved private company definition overrides its default. An approved product definition takes precedence for its product.

Use the definition effective at the measurement cutoff. If definitions change between periods, restate both observations on a common basis or disclose the break. Follow [the numerical evidence procedure](numbers.md).

## Maintain a definition

Use [the maintain-metrics skill](../.agents/skills/maintain-metrics/SKILL.md). Capture the PM-confirmed formula, population, unit, period, and denominator. Record the owner, effective date, and approval source.

Preview a change with `pm.py metric set ID` and JSON on standard input. Add `--product PRODUCT` for a product exception. Add `--write` to save the confirmed change. Each saved revision keeps its full definition in `private/context/metrics.json`.

```json
{
  "approved_by": "Finance owner",
  "effective_on": "2026-10-01",
  "source": "October metrics review, decision 2",
  "changes": {
    "definition": "Share of the opening paid cohort that loses its last paid subscription.",
    "formula": "100 × opening cohort with a last-subscription cancellation ÷ opening paid customer count.",
    "notes": "Count a cancellation in its effective period. Report reactivation as a separate movement."
  }
}
```

The example changes the treatment of reactivations for `logo-churn`. For a new metric, supply name, aliases, unit, definition, formula, population, period, denominator, and notes in `changes`.

## Use the same definition

- Read the registry reference when calculating or reviewing a known metric. For `check-metric`, pass its `metric` ID and the observation's `definition` reference. Pass `product` and `as_of` when applicable.
- For a signed initiative metric, propose `{"type":"metric","metric":"logo-churn"}`. The proposal captures the effective definition and its revision.
- If an initiative needs a revised definition, use a new local metric ID. For example, add `"registry_metric":"logo-churn"` to a proposal with `"metric":"logo-churn-v2"`. Existing signed records still explain how earlier outcomes were measured.
