# Backlog and roadmap views

Generate both views from the signed product register. Each row uses the same initiative ID. Run `initiative show PRODUCT ID` for its evidence, metrics, decisions, and delivery references.

## Read the views

The default backlog shows inbox, under consideration, in discovery, defining, and candidate initiatives. Use `--phase` for one status or `--all-phases` to search historical and committed work.

Use `--due` for dated reviews across phases. Release measurements leave the reminder active until the PM signs an outcome review.
A dated follow-up sets the next reminder. Closure clears it. Review event-triggered deferrals when their named event occurs.

After closure, the first newly recorded measurement makes the review due on its observation date.
Corrections, guardrail breaches and material changes to measured outcomes bring review forward, including during a scheduled follow-up.
The next closure cites the measurements that reopened the review.

For an area view, use `--product PRODUCT --area AREA`. Both views read the area's qualified subject from the initiative.
An initiative can appear in several area views. Product-wide initiatives appear in the unfiltered product view.

The roadmap shows signed selections by planning cycle, horizon, and rank. Its comparison lives at `workspace/roadmaps/<product>/<cycle>.md` inside the private repository. The cycle dates bound the planning period. An initiative's delivery record supplies its implementation reference.
Use the linked comparison to see the alternatives, obligations, and capacity constraints behind each selection.

```sh
python3 tools/pm.py backlog --product example --format csv
python3 tools/pm.py backlog --product example --all-phases
python3 tools/pm.py backlog --product example --area renewals
python3 tools/pm.py backlog --product example --due --format markdown
python3 tools/pm.py roadmap --product example --cycle quarter-two --format json
```

CSV is a spreadsheet export. Regenerate exports after approved changes. Submit proposed edits as initiative transactions.

## Review an incoming idea

Search `backlog --product PRODUCT --all-phases` before proposing a new ID. Include deferred, declined, and shipped work.
Compare the affected users and their problem. A new source can describe an existing problem in different words.

The proposal shows up to five matches from the product history. A paraphrase can fall outside that list.
Inspect plausible initiatives with `initiative show PRODUCT ID`.
If the underlying problem matches, propose a `signal` on that ID. If ownership is unclear, keep the proposal open.
For a distinct problem, the PM confirms the new ID when signing.

## Review new evidence

A signal recorded after approval puts the initiative in `backlog --due` for triage. The roadmap shows the review.
Read `signal_reviews` in the preview or initiative trace for the source and signed approval.

Submit `review-signal` with the exact `signal` source locator and the affected `claim`. Inspect `initiative schema` for the fields.
Mark a routine signal with `assess`. Link material or uncertain evidence to an approved claim and state `residual_risk`.

Use `retain`, `follow-up`, `revise`, or `reopen` to record the PM's decision.
A dated follow-up schedules the next check.
Revising leaves the review open. Reopening returns work to consideration for a new approval.

## Close a release review

Read `initiative show PRODUCT ID` for the evidence trail. Follow [the guardrail and correction procedure](outcome-evidence.md) when preparing the PM's assessment.
In this example, the signed measurement `release-cohort` records the share of new administrators who finished their first import.

```json
[{
  "type": "decision",
  "initiative": "product-context-0123456789ab/guided-first-import",
  "action": "review-outcomes",
  "on": "2026-11-18",
  "reason": "The first release cohort reached the activation target.",
  "source": "November cohort review, decision 4",
  "outcomes": {
    "first-import-24h": {
      "status": "met",
      "measurements": ["release-cohort"],
      "assessment": "64 of 100 eligible administrators completed an import against a target of 60."
    }
  },
  "follow_up": null
}]
```

If evidence is pending, give `follow_up` an `on` date and an `action`. The due view uses that date.

## Where the fields come from

| Source pattern | Fields or behavior in PM Hub | Primary source |
| --- | --- | --- |
| Names, workflow stages, relative priority, and effort estimates | `title`, `phase`, `rank`, `effort`, `unit` | [Atlassian Jira product backlog template](https://www.atlassian.com/software/jira/templates/product-backlog-template) |
| An evolving product backlog refined as evidence changes | One product register supports intake, ongoing review, and ordering | [2020 Scrum Guide, Product Backlog](https://scrumguides.org/scrum-guide) |
| Each iteration has an objective and a way to measure progress | `outcome`, `success_metrics`, `period_start`, `period_end` | [UK Government Service Manual, roadmap principles](https://www.gov.uk/service-manual/agile-delivery/developing-a-roadmap) |
| Now, Next, and Later group ideas by horizon | `horizon` | [Atlassian Jira product roadmap template](https://www.atlassian.com/software/jira/templates/product-roadmap) |
| A period groups ordered work, estimates, status, and links | `cycle`, `rank`, `effort`, `unit`, `phase`, `delivery` | [Atlassian Confluence product roadmap template](https://www.atlassian.com/software/confluence/templates/product-roadmap/) |

The supplied *Product Backlog & Discovery Workflow*, sections 1 and 7, informs problem, audience, source, and revisit fields. The [backlog template](../templates/views/backlog.json) reserves rank for signed selections.
The supplied *Product Strategy Mindset*, section 7, frames the roadmap around outcomes and horizons. The *Product Prioritization — PM Handbook*, section 4, informs trade-offs and capacity decisions.
The [roadmap template](../templates/views/roadmap.json) links each selection to its planning record and metric IDs.

The skills borrow BMAD’s practice of routing by intent and naming the next workflow. [BMAD Product Manager skill at the reviewed revision](https://github.com/bmad-code-org/BMAD-METHOD/blob/e435a22574fe55722841086e5566420178b98df3/skills/method/bmad-agent-pm/SKILL.md).
