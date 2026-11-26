# Release measurements, guardrails and corrections

Use `/pm delivery outcome review PRODUCT INITIATIVE`. Read `initiative show PRODUCT INITIATIVE` for the approved targets, guardrails, evidence and earlier decisions. Prepare changes through the [initiative approval procedure](initiative-approvals.md). The PM approves each decision.

## Approve a guardrail

Register its product metric first. Define the safe bound, unit, population, reporting window, effective date and decision source.

```json
{
  "type": "guardrail",
  "initiative": "product-context-0123456789ab/pilot",
  "guardrail": "setup-errors",
  "metric": "setup-error-rate",
  "operator": "lt",
  "threshold": "2",
  "unit": "percent",
  "basis": "day",
  "population": "Eligible pilot tenants",
  "effective_on": "2026-11-18",
  "source": "Pilot review, decision 3",
  "adopted_from": {
    "target": "activation",
    "on": "2026-11-16",
    "source": "Approved rollout plan, section 4"
  }
}
```

For new limits, omit `adopted_from` and use the approval date or later. A shipped initiative can adopt an earlier bound from dated evidence. Cite its original target, date and source. Keep the target's original guardrail notes.

Use `lt`, `lte`, `gt` or `gte` for the safe side of the bound. With `lt`, equality breaches the bound. With `lte`, equality passes. Use decimal strings to preserve precision. A revised threshold takes effect prospectively. Each reading keeps the bound effective at its measurement cutoff.

## Record a reading

Use `measurement` for a success target. Use `guardrail-reading` with a guardrail ID for a bound. Give each reading a distinct ID, observed date and original report or query version. Record the value in the declared unit.

```json
{
  "type": "guardrail-reading",
  "initiative": "product-context-0123456789ab/pilot",
  "guardrail": "setup-errors",
  "metric": "setup-error-rate",
  "measurement": "pilot-day-1",
  "value": "5",
  "observed_on": "2026-11-19",
  "source": "Pilot cohort export, revision 4",
  "observation": {
    "definition": "setup-error-rate",
    "population": "Eligible pilot tenants",
    "unit": "percent",
    "basis": "day",
    "timezone": "UTC",
    "start": "2026-11-18",
    "end": "2026-11-19",
    "complete": true,
    "source": "Pilot cohort export, revision 4"
  }
}
```

This example uses a local metric. Registry measurements need the pinned definition reference and its [approved calculation inputs](numbers.md). A proportion needs a checked numerator, eligible denominator, denominator basis and subset confirmation.

Check [the reporting window](metrics.md) for each observation. Use the exclusive end date. When the effective registry revision changes, cite the restatement on the approved metric definition in `restatement`. A guardrail observation must fall within one approved threshold revision.

## Correct the source or reading

```json
{
  "type": "correct-measurement",
  "initiative": "product-context-0123456789ab/pilot",
  "measurement": "pilot-day-1",
  "reason": "The extract counted repeated events from internal tenants.",
  "source": "Data quality review, finding 7",
  "replacement": "pilot-day-1-recount"
}
```

Propose the replacement reading first, or include both events in one proposal. Omit `replacement` to invalidate the original. The register retains both sources, the reason, approval date and original review.

Correct a replacement by its active ID. Use the same metric, guardrail and observation window. For a legacy replacement, match its observation date. Cite the original window and population evidence in `comparison_source`.

## Approve the outcome review

Compare the observed change with the original expectation. Check the cohort, time window, and any competing explanation.
A rise after launch can support a measured outcome while its cause remains open.
Show the implications of expanding, adjusting, or gathering evidence. The PM decides what to do.

Review each target independently. Use `unmeasured` when it has no usable readings. Use `pending` and a dated follow-up when more evidence is expected. A registry reading from an older unstructured report needs checked evidence before a new conclusion can cite it.

Inspect `evidence_review` in the proposal. Verify unconfirmed reporting windows against the original sources. A guardrail can breach while activation meets its target. Give the PM's reason or next action in `guardrail_dispositions`, keyed by each breached or unavailable guardrail. If the available guardrail reading predates the latest target observation, the review shows the coverage gap. Cite material changed readings even when scheduling another follow-up.

Inspect `backlog --due` after a correction or material reading. The PM’s recorded decision clears the reminder or schedules follow-up. The initiative trace retains historical breaches, missing evidence and the earlier decision.

## Existing workspaces

Upgrade every active client before recording new approvals or saving typed reporting windows. Older clients reject the new fields. Keep verified private Git recovery copies. Existing registers replay in the original event order. Inspect `backlog --all-phases` and the initiative trace for guardrail notes and unverified readings. Confirm any adoption against the original source.
