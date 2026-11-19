# PM Hub

A personal product management workspace with a shared system and a separate private data repository.

Read the [constitution](AGENTS.md) for purpose, ownership, writing rules, and agent conduct.

## Start

Clone the shared system, then open its root in Codex or Claude. Initialise a private workspace once:

```sh
python3 tools/pm.py init-workspace --owner "Your name" --delivery-system "Your delivery system"
```

The command creates `private/` with its own Git repository and guides.

To restore existing work, clone its private repository into `private/`. Run the shared Hub on each machine before opening the restored data.

Read `private/settings.json` for the owner, delivery system, system version, workspace format, and confirmed remote URLs.

Read `private/README.md` for the current session checkpoint and next action. Keep that handoff current before ending a session.

Start with company context, product context, and strategy.

For area work, consult the product brief and [area guidance](playbook/filing.md#product-area-context).

Use the [opportunity workflow](playbook/opportunities.md) for proposed investments. Standing initiative guidance stays in context. Briefs, experiments, and planning comparisons belong in the workspace.

Agents automatically use [ingest-context](.agents/skills/ingest-context/SKILL.md) for context capture. The agent prompts for a missing or unfinished [PM remit](playbook/context.md#pm-remit). A remit can cover whole products or several areas within them.

For [meeting capture](.agents/skills/summarize-meeting/SKILL.md), give the initiative and a title, date range, link, or transcript file.

## Placement

Keep only `README.md`, `AGENTS.md`, `CLAUDE.md`, and `.gitignore` as root files. The checker enforces these homes:

| Home | Purpose | Repository |
| --- | --- | --- |
| `private/context/` | Reference material organised by company, product, product area, initiative, or PM | Private |
| `private/context/products/<product>/initiatives/<initiative>/` | New initiative overviews and dated meeting notes | Private |
| `private/context/pm/context.md` | PM profile, including responsibilities, goals, dependencies, and interests | Private |
| `private/workspace/` | Work in progress and completed PM artifacts, organised by type | Private |
| `private/workspace/backlogs/<product>/initiatives.json` | Signed initiative register used by the backlog and roadmap commands | Private |
| `private/workspace/initiatives/<product>/<initiative>/` | Discovery Brief and Initiative Brief for the same initiative ID | Private |
| `private/workspace/initiatives/<product>/<initiative>/{tasks,launch-checklist}.json` | PM tasks and launch checkpoints | Private |
| `private/workspace/experiments/<product>/<initiative>/` | Editable metric-linked experiment drafts | Private |
| `private/workspace/roadmaps/<product>/<cycle>.md` | Comparison of candidates for the planning cycle | Private |
| `private/settings.json` | Installation settings and expected remotes | Private |
| `private/.hub-history/` | Recovery copies for reviewed filing conversions | Private |
| `private/.hub-upgrades.json` | Private progress on release-specific reviews | Private |
| `playbook/` | Methods, working practices, Git rules, and release metadata | Shared system |
| `templates/` | Starters for requested artifact types | Shared system |
| `tools/` and `tests/` | Commands, empty workspace seeds, and checks | Shared system |
| `.agents/skills/` | Canonical shared skills | Shared system |
| `.claude/`, `.codex/`, `.github/` | Native client and CI configuration | Shared system |

Artifact paths are relative to `private/`.

Use [the filing rules](playbook/filing.md) to decide when a section earns a separate file. Keep records in place as work advances; their state changes, and their location follows their subject.

Start reference material in the entity overview. Create a topic folder only for a recurring reader need under the filing rules.

## Work

- [Product Strategy Mindset](playbook/sources/product-strategy-mindset.md) defines the method. The [framework index](playbook/framework.md) links source sections, skills, and templates.
- [Opportunity workflow](playbook/opportunities.md) covers intake, discovery, Initiative Brief approval, and roadmap selection.
- [Generated backlog and roadmap](playbook/initiative-views.md) use the signed register.
- [Initiative work](playbook/initiative-work.md) covers PM tasks and launch readiness.
- [Templates](templates/README.md): company context, product context, and PM artifacts.
- [Context rules](playbook/context.md) cover routing, sources, parent links, dates, and gaps.
- [Hub commands](playbook/commands.md) and [working practices](playbook/working.md) cover actions, preferences, and checkpoints.
- [Git rules](playbook/git.md): the correct repository for saves, updates, and contributions.

The Git command name `workspace` selects the entire private repository.

Use Git and Python 3.9 or later. Initiative approval and its tests also require OpenSSH. Follow [the approval procedure](playbook/initiative-approvals.md).

```sh
python3 tools/pm.py check
python3 tools/pm.py action strategy brief check workspace/strategies/example.md
python3 tools/pm.py backlog
python3 tools/pm.py roadmap
python3 -m unittest discover -s tests -v
python3 tools/pm.py git workspace status
python3 tools/pm.py git system status
python3 tools/pm.py new company-context context/company/overview.md --title "Company context"
```

Run the [context evaluations](tests/context-evals/README.md) to test artifact structure, context use, and fresh tasks after capture.
Use `pm.py catalog` to find records. Use `pm.py task-context` to read task-specific guidance.
Apply [the numerical evidence checks](playbook/numbers.md) to material numbers in any task.
Find SaaS defaults and PM-approved definitions in the [metric registry](playbook/metrics.md).

Shared Hub changes automatically use [extend-hub](.agents/skills/extend-hub/SKILL.md) to trace dependencies and correct stale guidance. Use `red-team` when you want a product decision challenged against its evidence.

Say "quiet" or "just capture" to stop unsolicited critique.

Run the [red-team quality benchmark](tests/red-team-evals/README.md) to compare review quality with BMAD after skill or model changes.

## GitHub and updates

Each repository has its own `origin`. Confirm each destination, configure its remote, and record its URL in private settings.

The Git commands require an explicit repository and verify its root, expected remote, branch, and destination separation.

```sh
python3 tools/pm.py git workspace pull
python3 tools/pm.py git workspace push
python3 tools/pm.py git system fetch
python3 tools/pm.py git system pull
python3 tools/pm.py git system push
```

These commands act when invoked; they do not grant permission. Read the Git rules before use.

The Git wrapper checks the target and requires a fast-forward update. Session startup aligns supported private layouts.

After pulling, open the Hub and work as usual. The agent handles [existing-workspace alignment](playbook/updates.md) and raises decisions that need you.

Shared CI runs `check --system-only` and tests against fictional workspaces. Follow [the Codex review gates](playbook/git.md#codex-review-before-publication) before publication. Local checks also inspect ignored private records explicitly.

## Hooks and checks

Hooks load guidance at startup, refresh reply preferences each turn, and check the Hub before stopping.
They work from nested directories.

The edit hook enforces filing rules for supported native edits. Use the shared commands to start typed records. Keep original sources identifiable.

In Codex, review and trust the project hooks through `/hooks`. In Claude, accept project trust and inspect `/hooks`.

Managed settings can disable hooks. A failed stop requests one correction, then permits a handoff with the unresolved failure visible.

The router checks one write target per call. Hooks cover configured native tools. Shell and external editor writes depend on the workspace rules.

Checks cover repository boundaries, agent entry points, skill copies, links, writing limits, artifact contracts, source dates, and review deadlines.

The checker compares the template index and the playbook's routing topics with the commands that use them.

Semantic review covers clarity, accuracy, source authority, and decision quality. External change detection arrives when needed.

Connect GitHub remotes after their destinations are known. Require `check` and `review` on the shared default branch. See [release setup and recovery](playbook/publication.md).

## Client references

Initial client wiring was checked on 2026-11-18 with Codex CLI 0.170.0 and Claude Code 2.1.327.

- [Codex hooks](https://learn.chatgpt.com/docs/hooks)
- [Codex skills](https://learn.chatgpt.com/docs/build-skills)
- [Claude hooks](https://code.claude.com/docs/en/hooks)
- [Claude instructions](https://code.claude.com/docs/en/memory)
