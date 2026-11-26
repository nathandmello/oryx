# Check numerical evidence

Apply this procedure to material quantities in capture, analysis, notes, replies, plans, forecasts, presentations, and reviews. A trusted source can still use a different definition or provide an incorrect result.

## Establish what the number means

| Check | What to establish |
| --- | --- |
| Provenance | Owner, original report or data extract, date, version, query or formula, and later revisions |
| Definition | Metric, unit, grain, counting key, numerator, denominator, inclusions, and exclusions |
| Time | Start and end, reporting cutoff, time zone, late events, calendar or fiscal basis, and any seasonal adjustment |
| Comparability | Same cohort, filters, recognition basis, currency, geography, product coverage, and measurement method |
| Input quality | Coverage, freshness, duplicates, missing values, outliers, validity, and known collection or sampling bias |
| Transformations | Join cardinality, filters, conversions, weighted aggregation, rounding, and treatment of reversals |
| Reconciliation | Recompute from inputs. Compare with source totals, adjacent periods, and an independent check where available. |
| Interpretation | Label actuals, estimates, targets, forecasts, and assumptions. State uncertainty and avoid causal claims without evidence. |

Check the items that can change the decision. Inspect the primary data or calculation when it is available. Compare credible sources using equivalent definitions before choosing between them.

Use [the metric registry](metrics.md) for the effective company or product definition. Label any different definition used by the source.

## Growth and rates

- For revenue growth, obtain both amounts and comparable windows. Confirm recognized, booked, billed, or collected revenue. Check gross or net, currency, and one-off adjustments. Compare matched calendar or fiscal periods. Label a partial-period comparison and align both cutoffs. Record seasonality and changes in business scope.
- Compute relative growth as `(current − baseline) / baseline`. Use an absolute change when the baseline is zero or negative. Give percentage points for the difference between percentages. For example, 4% to 5% is 1 percentage point or 25% relative growth.
- For churn, name what churns: accounts, subscribers, subscriptions, or recurring revenue. Define the eligible population and event time. Check cancellations, downgrades, failed payments, reactivations, trials, and new subscribers. Match the numerator to the eligible denominator. A 30-day Stripe subscriber rate and a retention measure for a fixed paid starting cohort use different denominators. [Stripe analytics](https://docs.stripe.com/billing/subscriptions/analytics#churn), [ChartMogul retention](https://help.chartmogul.com/article/322-chart-paid-subscriber-retention-rate)
- Recompute aggregate rates from their components. Check sample size, weighting, and mix changes before interpreting a headline. Compare the relevant segments when the aggregate conceals a materially different result.

## Record the result

State which checks ran, what they support, and which gap could change the conclusion. Preserve the source's value as a reported claim when calculation or comparability remains open. Ask for the specific missing input when it matters. Document any estimate, range, or assumption beside the figure.

For structured inputs, run `python3 tools/pm.py check-metric` with JSON on standard input. It checks arithmetic and declared comparability. Inspect the underlying extract to verify its coverage, joins, and population.

Each observation needs `definition`, `population`, `unit`, `basis`, `timezone`, `source`, `start`, `end`, and `complete`. Use an exclusive ISO end date. For `growth` and `percentage_points`, provide `current` and `baseline` observations with `value`. Supply `reported` to compare a stated result at its precision.

Use the [approved reporting window](metrics.md#confirm-the-reporting-window) as the observation basis. Check each observation's cutoff. If `approved_reporting_windows` shows null for a registry definition, verify its period against the source.

For `proportion` and `cohort_ratio`, provide `current` with `numerator`, `denominator`, and `denominator_basis`. Set `numerator_subset` for a proportion after checking membership. Set `same_cohort` for a cohort ratio after verifying the opening cohort on both sides. A cohort ratio can exceed 100%.

| Reference | What to check |
| --- | --- |
| [UK Government Data Quality Framework](https://www.gov.uk/government/publications/the-government-data-quality-framework/the-government-data-quality-framework-guidance) | Validity, completeness, uniqueness, accuracy, consistency, and timeliness |
| [SEC guidance on KPIs](https://www.sec.gov/files/rules/interp/2020/33-10751.pdf) | Define calculation, assumptions, and changes in methods |
