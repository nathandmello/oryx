# PM Hub context evaluations

Run from the Hub root with Python 3.9 or later.

```sh
python3 -B tests/context-evals/run.py
python3 -B tests/context-evals/run.py --strict
```

The runner creates and removes a disposable Hub checkout. It calls the capture command, checker, area lookup, and hook handler with fixed inputs. It reports strict-mode failures when an expected behavior is absent. Report mode exits successfully if the probes ran and the grader controls passed.

The probes permute capture order and challenge scope isolation, source replay, and the task-to-context loop. They also route an accepted workspace finding into context and test a fresh task. The stop probe supplies a simulated reply. Use its result to assess the hook's response to that reply. Live model output requires a separate replay.

## Public cases

| Source | Coverage |
| --- | --- |
| [Slack change](https://docs.slack.dev/changelog/2025/05/29/rate-limit-changes-for-non-marketplace-apps/) and [clarification](https://docs.slack.dev/changelog/2025/06/03/rate-limits-clarity/) | Install date, distribution, and the internal-app exception |
| [Slack retry guidance](https://docs.slack.dev/apis/web-api/rate-limits/#responding-to-rate-limiting-conditions) | Wait time, method, and workspace |
| [Stripe refunds](https://docs.stripe.com/refunds#issue-refunds) | Cumulative amount, equality, and the next amount above the limit |
| [JPL preliminary findings](https://www.jpl.nasa.gov/news/mars-climate-orbiter-team-finds-likely-cause-of-loss/) and [NASA Phase I report](https://discovery.larc.nasa.gov/PDF_FILES/MCO_report_2.pdf) | Historical knowledge, confirmed root cause, and acceptance checks |
| [Chrome proposal](https://privacysandbox.google.com/blog/privacy-sandbox-update) and [Chrome decision](https://privacysandbox.google.com/blog/privacy-sandbox-next-steps) | Decision authority and removal of an obsolete plan dependency |
| [Stripe subscriber churn](https://docs.stripe.com/billing/subscriptions/analytics#subscriber-churn-rate) and [ChartMogul retention](https://help.chartmogul.com/article/322-chart-paid-subscriber-retention-rate) | Different denominator definitions, arithmetic, and invalid comparisons |

The case file paraphrases the primary sources. Task wording, amounts, and rollout scenarios are evaluation inputs. Dated cases use the source available by the stated date. The runner uses no network or private workspace records.

## Replay workspace tasks

```sh
python3 -B tests/context-evals/run.py --prompts provided
python3 -B tests/context-evals/run.py --prompts withheld
python3 -B tests/context-evals/run.py --grade results.json --strict
```

Run the same tasks in fresh sessions with the same client and model. Supply the evidence for the provided run. Disable web lookup for both runs. For a Hub integration run, seed the evidence in Hub records and capture the actual lookup trace.

Have a reviewer compare each output with the case in `cases.json`. Record these fields under its case ID:

| Field | Value |
| --- | --- |
| `retrieved` | Evidence IDs selected by the integration trace. For replay, use the IDs supplied to the model. |
| `used` | Evidence IDs that support the output. Use IDs from the supplied evidence. |
| `decision` | The action represented by the output, coded against the case's expected action |
| `facts` | The requested facts as JSON values, transcribed from the result |
| `artifact_applies_decision` | True if the actual artifact follows the decision without a contradictory action or commitment |

Keep `cases.json` and the grading key out of the task prompt. Compare the decision, facts, and artifact scores across the two replay runs. Assess retrieval separately on the integration trace. A provided run with decoys can fail retrieval isolation while still applying the right evidence.

The grader controls verify correct outputs and reject altered actions, missing facts, failed reviews, invalid evidence IDs, and forbidden sources.
