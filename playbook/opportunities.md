# Initiative workflow

The PM owns the decisions. Use company context, product context, strategy, and current goals. Cite material facts. Record missing facts and request the evidence or decision needed.

| Stage | Authoritative record or view | Decision |
| --- | --- | --- |
| Capture | Product initiative register | Open one initiative ID for a distinct problem or add a signal |
| Evaluate | Initiative description and evaluation | Investigate, define, defer, or decline |
| Authorize discovery | Discovery Brief and hypothesis IDs | Allocate capacity and authorize the timebox |
| Investigate | Discovery Brief, hypothesis assessments, experiments, and results | Define, extend, defer, or stop |
| Review | Initiative Brief and linked success measures | Approve a reviewed revision as a candidate |
| Prioritize | Planning cycle and signed capacity decision | Select work, defer it, or keep it eligible |
| Deliver and learn | Delivery reference, release evidence, and measured outcomes | Verify the release and review outcomes |

## Follow a single ID

A product register links its product context and that context's company parent. Each initiative's permanent ID combines the product context ID and an initiative slug. Capture gives it that ID.

The PM may link zero, one, or several areas of the owning product. Store each qualified subject once in the initiative's `areas` list.
For example, `product/checkout/area/refunds` identifies checkout's refunds area. Omit `areas` on capture for product-wide work.

Use a sourced `set-areas` transaction to replace the list. An empty list clears area links.
Read the company and product overviews, then consult the linked area's labelled evidence with `pm.py area-context PRODUCT AREA`.
Assign areas only from explicit evidence or a PM decision. A separate area overview exists when its standing guidance needs one.

Discovery and the Initiative Brief belong to the same initiative. Use their Markdown files for analysis. Store the problem, audience, intended outcome, and structured relationships in the register. Refer to the ID in briefs, planning comparisons, and delivery artifacts.

An experiment links a hypothesis and the product metric it measures. Its results link the experiment. A target links an initiative to a product metric definition. Post-release measurements reference that same metric.

Use `initiative show PRODUCT ID` to locate working briefs and the current planning comparison under `files`.
Each brief entry gives its canonical path and whether the file exists. The initiative's signed decisions identify reviewed revisions.

## Evaluate incoming evidence

Propose `evaluate` with value, strategic fit, urgency, source locators, and open questions.
Reference signal sources already on the initiative. Add a new signal when evidence arrives.
Use null for an unknown dimension and name the gap. A quick assessment can use an empty source list.

The `evaluation` object below refers to the signal added by the [capture example](initiative-approvals.md).

```json
{
  "value": "Help administrators renew before access expires.",
  "strategic_fit": null,
  "urgency": null,
  "sources": ["Support ticket 12, initial report"],
  "unknowns": "How often does this happen, and which retention objective would it support?"
}
```

The PM can reassess an initiative under consideration. Each signed evaluation preserves the earlier assessment.

## Start an experiment draft

Recording a success target creates one editable JSON draft when that metric has no experiment on the initiative.
The filename is `experiment.<metric-id>.draft.json`. Find its path and missing fields with `initiative show`.
The draft lives in `workspace/experiments/<product>/<initiative>/` inside the private repository. It references the metric definition and initiative target by ID.

Start earlier with just a registered initiative and product metric:

```sh
python3 tools/pm.py initiative draft-experiment example PRODUCT_CONTEXT_ID/renewals renewal-rate
```

Fill in known fields. Leave other fields null or omit them. Use a cited test criterion chosen for this experiment.
Repeating the command or revising the target preserves edits. The draft stays outside the signed register during editing.

Each signed update reconciles drafts for the affected initiative and metric pairs. Use `initiative sync-drafts PRODUCT` for product-wide recovery.

Check that the linked metric answers the hypothesis. [Review the test and decision rule](brief-review.md#match-the-test-to-the-hypothesis).

Propose `approve-experiment` with the initiative and metric IDs when the plan is ready.
The PM reviews the resolved plan before signing. Approval records the same experiment ID and retires the draft file.
Results use that ID. The [approval procedure](initiative-approvals.md) explains review and recovery.

```sh
python3 tools/pm.py initiative show example
python3 tools/pm.py initiative show example PRODUCT_CONTEXT_ID/renewals
python3 tools/pm.py backlog --product example --phase candidate
python3 tools/pm.py backlog --product example --due
python3 tools/pm.py roadmap --product example --format markdown
```

Use [the view templates](initiative-views.md) for JSON, CSV, or Markdown exports. Use [the approval procedure](initiative-approvals.md) for validated changes.

## Use the workflow skills

- [Manage the backlog](../.agents/skills/manage-backlog/SKILL.md) for intake, checkpoints, and reopening.
- [Run discovery](../.agents/skills/run-discovery/SKILL.md) for authorization, evidence, and findings.
- [Define an initiative](../.agents/skills/define-initiative/SKILL.md) for proposal review.
- [Prioritize the roadmap](../.agents/skills/prioritize-roadmap/SKILL.md) for planning and trade-offs.

## Worked example

A fictional checkout support case describes delays in refund approvals. The company objective is retention. The checkout overview links that objective to merchant satisfaction.

| Decision | What the PM records |
| --- | --- |
| Capture | Keep the support case on `product-context-0123456789ab/refund-delays`. The PM identifies one area, `product/checkout/area/refunds`. |
| Evaluate | Merchants report delays. Their frequency is unknown. The PM authorizes a timeboxed Discovery Brief to investigate. |
| Define | Discovery findings support a smaller approval queue. The Initiative Brief cites those findings. The PM sets a target against `refund-resolution-days`. |
| Test | The target opens `experiment.refund-resolution-days.draft.json`. The PM later approves the hypothesis and test plan. The result cites the experiment ID. |
| Select | Brief approval makes this initiative a candidate. The PM compares it with checkout alternatives and selects it within the cycle's capacity. |
| Learn | Delivery links the tracker to the same initiative. After verified release, the PM records observed resolution time against the original metric. |

Follow this initiative and its area's live views:

```sh
python3 tools/pm.py initiative show checkout product-context-0123456789ab/refund-delays
python3 tools/pm.py backlog --product checkout --area refunds --all-phases
python3 tools/pm.py roadmap --product checkout --area refunds --format markdown
```

## Review the backlog

Capture signals continuously. Search by product, audience, problem, and source. Review possible duplicates with the PM. The register rejects repeat sources and normalized duplicate titles or problem and audience pairs.

The default backlog shows uncommitted initiatives. Use `--all-phases` for the full register or `--phase` for one status.
Use `unplan` to release a reservation before delivery. The initiative returns to candidates with its reviewed brief.

Review active discovery weekly against its learning goals. Supply dates or event triggers for deferrals. Review dated items with `backlog --due`. Review event triggers when they occur.

The PM supplies open backlog limits, discovery limits, and capacity for each planning cycle. Review existing work when a limit is reached. Reopen eligible work when evidence or constraints change. Shipping starts the outcome review. Record measurements, then use `review-outcomes` to close it or schedule follow-up.

## Source frameworks

The supplied *Product Strategy Mindset* informs goal alignment, the four risks, experiments, and confidence. [Product strategy framework](framework.md).

The supplied *Product Backlog & Discovery Workflow* informs intake, review cadence, and proportionate exceptions. The supplied *Product Prioritization — PM Handbook* informs commercial evidence and constrained planning. The Initiative Brief gate follows the PM's stated workflow.
