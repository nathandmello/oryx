# Backlog and roadmap views

Generate both views from the signed product register. Each row uses the same initiative ID. Run `initiative show PRODUCT ID` for its evidence, metrics, decisions, and delivery references.

## Read the views

The default backlog shows inbox, under consideration, in discovery, defining, and candidate initiatives. Use `--phase` for one status or `--all-phases` to search historical and committed work.
Use `--due` for dated reviews across phases. Review event-triggered deferrals when their named event occurs.

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
