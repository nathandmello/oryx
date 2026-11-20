# Record a decision and forecast its outcome

Ask which record the PM wants. A forecast estimates the probability of a future event. Decision confidence describes trust in a choice. Hypothesis confidence belongs in the initiative assessment.

## Preserve the decision in its owning record

For a registered initiative, add optional `rationale` to the usual decision transaction in `initiative propose`. This example uses fictional details.

```json
{
  "choice": "Keep manual billing reminders for the pilot",
  "alternatives": ["Automate reminders across every billing account"],
  "tradeoff": "Manual follow-up costs the support team a day per cycle and preserves tax delivery capacity",
  "owner": "Mira Chen",
  "scope": "The March billing pilot",
  "reopen_when": "More than five pilot renewals miss their deadline in one cycle",
  "review_on": "2027-04-01"
}
```

Use the decision’s existing `source` for the evidence and `reason` for the PM’s words. Include at least one credible alternative. Match any owner, scope or review date required by the transition. The PM signs the entire decision, including the rationale inside its reason.

For a context-owned choice, use `route-context` and the owning company, product, area or initiative overview. Record the question, scope, person, date, evidence and next step. Capture alternatives, trade-off and reopen condition in the reviewed source or linked rationale. Confirm the review controls and dated Sources entry. Correct an initiative call with a signed successor and a context call with a sourced superseding entry. [Initiative approvals](initiative-approvals.md) · [Context capture](context.md)

## Preview a forecast

Offer a forecast when the PM has made a decision and named an uncertain future event worth reviewing. Accept a decline. Confirm the event wording, probability, date stated, resolution date and the evidence that will establish the outcome.

Find the exact decision the PM means. Select the `decision` object from a returned entry.

```sh
python3 tools/pm.py forecast decisions --product billing
python3 tools/pm.py forecast decisions --context context/products/billing/overview.md
```

For registered decisions, `--initiative` with the full registered ID narrows the first command. It verifies the register with the trusted PM signer. Closed context decisions require a reviewed overview, a named owner, a dated source and an active decision row. The selector binds to the original decision and source identity. The preview includes source coverage and applicable open evidence reviews. Forecast confirmation records the prediction and preserves those advisories.

Replace the example’s `decision` with the returned selector. Use the actual dates and a future resolution date. Probability is a number from 0 to 100, including fractional percentages.

```json
{
  "operation": "create",
  "decision": {"kind": "context", "record": "context/products/billing/overview.md", "artifact_id": "product-context-example", "digest": "replace-with-returned-digest"},
  "event": "More than 80 percent of eligible pilot accounts renew on time",
  "criterion": "Use the billing cohort report at quarter close and exclude accounts that entered after the pilot start",
  "probability": 75,
  "made_on": "2027-01-15",
  "resolve_on": "2027-04-01"
}
```

Keep request and preview files outside both Git repositories. Run the preview, then show the PM the proposed forecast and its source. After they confirm that exact version, apply it.

```sh
python3 tools/pm.py forecast preview < request.json > preview.json
python3 tools/pm.py forecast apply < preview.json
python3 tools/pm.py forecast list --product billing
```

An exact retry returns the existing ID and revision. Event identity combines the decision reference, the event wording with normalized whitespace and case, and the resolution date. If the PM means a different outcome or time window, review a new event. For a changed estimate on the same event, append a dated revision. Each preview shows any prior estimates and the evidence behind the change.

## Revise or resolve

Use the same preview, confirmation and apply commands for each change. Replace the example ID and source with the actual values.

```json
{
  "operation": "revise",
  "id": "forecast-replace-with-returned-id",
  "on": "2027-03-10",
  "probability": 60,
  "evidence": {
    "source": "context/products/billing/sources/pilot-notes.md",
    "quote": "Of the first twenty accounts, four renewed late.",
    "observed_on": "2027-03-10"
  }
}
```

Preserve the observation's original wording. A private Markdown or text citation must contain the exact quote. The preview fingerprints that file. For an external HTTPS source, inspect the evidence with the PM and retain the URL, date and exact excerpt. oryx validates the citation fields and retains the PM-confirmed excerpt. Verification of an external page depends on the reviewer.

```json
{
  "operation": "resolve",
  "id": "forecast-replace-with-returned-id",
  "on": "2027-04-02",
  "outcome": false,
  "evidence": {
    "source": "https://reports.example.org/billing/pilot/quarter-close",
    "quote": "79 of the 100 eligible accounts renewed on time.",
    "observed_on": "2027-04-01"
  }
}
```

Confirm `true` or `false` only when dated evidence on or after the resolution date settles the original criterion. With incomplete coverage, leave the forecast open and unscored. The Brier score squares the difference between the original probability and the outcome. Both use a 0–1 scale. An original 75 percent estimate and a false result score 0.5625, even if later evidence shifted the estimate to 60 percent. Lower scores indicate closer forecasts.

## Compatibility and recovery

Forecasts live in `studio/workspace/forecasts/forecast-<id>.json`. The private record retains the reviewed decision citation and its evidence as they stood at creation. Historical forecasts can be resolved after the owning decision changes. Existing decisions and private files need no conversion.

Use the release’s normal backup and alignment steps on every client before sharing the first new forecast. An earlier oryx release can still replay a signed rationale, but its workspace checker predates the forecast file type. Preserve a backup of the current private checkout before rolling back. Restore matching oryx and Studio backups into a separate checkout for older-client use. Reopen the preserved current checkout with a compatible release to recover later forecast history. [Installation updates and backups](updates.md)

After a failed write, read the error and preview again if the evidence or record changed. Replay the exact saved proposal after a lost receipt. For a saved revision mismatch, inspect private Git history and restore the intended reviewed version.
