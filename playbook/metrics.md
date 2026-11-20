# Business metric definitions

Use the registry for metric definitions in context, analysis, briefs, forecasts, and reviews. Cite the effective definition and the source of the observed value. Keep third-party methods identifiable when they differ.

## Read a definition

```sh
python3 tools/pm.py metric list
python3 tools/pm.py metric show logo-churn --product checkout
python3 tools/pm.py metric show logo-churn --product checkout --as-of 2026-10-01
```

The [bundled definitions](saas-metrics.json) provide documented SaaS starting points. Their formulas state assumptions. An approved private company definition overrides its default. An approved product definition takes precedence for its product.

Use `company.revenue` for the approved company calculation, even within a product that uses a different revenue formula.
The company ID becomes available on its first approval date. Approvals recorded under the original `revenue` ID also qualify.
Each result includes its authority, storage origin, approving owner, approval source, effective date, and revision.
The local registry records the stated approval. Use `metric show company.revenue --as-of YYYY-MM-DD` to recover the definition used for a company report.

Use the definition effective at the measurement cutoff. If definitions change between periods, restate both observations on a common basis or disclose the break. Follow [the numerical evidence procedure](numbers.md).

### Share a company definition

Finance can distribute one approval file containing the full definition, owner, effective date, and decision source.
Each PM applies it in Studio with `python3 tools/pm.py metric set company.revenue --write < finance.json`.
A complete company definition replaces its optional fields too. Compare the resulting revision across Studios.
Each Studio keeps its own product definitions and forecast scenarios.

## Maintain a definition

Use [the maintain-metrics skill](../.agents/skills/maintain-metrics/SKILL.md). Capture the PM-confirmed formula, population, unit, period, and denominator. Record the owner, effective date, and approval source.

Preview a change with `pm.py metric set ID` and JSON on standard input. Add `--product PRODUCT` for a product exception. Add `--write` to save the confirmed change. Each saved revision keeps its full definition in `studio/context/metrics.json`.

```json
{
  "approved_by": "Finance owner",
  "effective_on": "2026-10-01",
  "source": "October metrics review, decision 2",
  "changes": {
    "definition": "Share of the opening paid cohort that loses its last paid subscription.",
    "formula": "100 × opening cohort with a last-subscription cancellation ÷ opening paid customer count.",
    "calculation": "proportion",
    "notes": "Count a cancellation in its effective period. Report reactivation as a separate movement."
  }
}
```

The example changes the treatment of reactivations for `logo-churn`. For a new metric, supply name, aliases, unit, definition, formula, population, period, denominator, and notes in `changes`. An approved definition can specify `calculation` for a formula supported by `check-metric`. Use `proportion` for a bounded subset and `cohort_ratio` for a closing amount divided by its opening cohort amount. When changing a formula or unit, reapprove the calculation type if it still applies.

### Model a scenario

Save a what-if calculation with its own ID, such as `metric set scenario.revenue-upside`. Add `--product checkout` for product-specific planning.
In the approval JSON, set `based_on` to `company.revenue`. Give the scenario a distinct `changes.name` and supply the fields that differ.

The scenario copies the chosen revision. Later company revisions leave its assumptions intact.
Use its ID in numerical checks and initiative proposals. In a forecast prompt, use its ID or its distinct display name.

## Confirm the reporting window

Use `period` to describe the timing and cutoff. Add `reporting_window` when the PM approves a fixed window.

| Reporting window | Required dates |
| --- | --- |
| `day`, `week`, `rolling 30 days` | One, seven, or thirty days from start to exclusive end |
| `calendar month`, `calendar quarter`, `calendar year` | First day of the period through the first day of the next period |
| `snapshot` | Cutoff date as the start and the next day as the exclusive end |

When changing `period` on a fixed definition, confirm `reporting_window` again. Set it to `null` for a definition whose period requires manual review. The checker recognizes exact legacy window descriptions, such as “One closed calendar month.” It reports a null approved window for other descriptions. Check those periods against the source before using the result.

## Use the same definition

- For `check-metric`, pass the `metric` ID and `product` when applicable. Each observation needs the registry reference and population effective on its last included day. Use a currency code in observation units, such as `USD/month` for `currency/month`. Use `as_of` when looking up the definition if an observation date is missing. The checker flags a revision change between periods. Verify and document a restatement on a common definition before comparing those periods.
- For a signed initiative metric, propose `{"type":"metric","metric":"logo-churn"}`. The proposal captures the effective definition and its revision.
- Give qualified definitions a local signing ID. For example, propose `{"type":"metric","metric":"reported-sales","registry_metric":"company.revenue"}`.
- If an initiative needs a revised definition, use a new local metric ID. For example, add `"registry_metric":"logo-churn"` to a proposal with `"metric":"logo-churn-v2"`. Existing signed records still explain how earlier outcomes were measured.
- A legacy signed metric can adopt the same workflow when its name or ID matches the registry. Keep previously signed targets and outcomes on their historical definition. Use the new ID for new targets.
