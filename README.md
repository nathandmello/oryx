# PM Hub

A personal product management workspace with a shared system and a separate private data repository.

Read the [constitution](AGENTS.md) for purpose, ownership, writing rules, and agent conduct.

## Start

Clone the shared system, then open its root in Codex or Claude. Initialise a private workspace once:

```sh
python3 tools/pm.py init-workspace --owner "Your name" --delivery-system "Your delivery system"
```

The command creates `private/` with its own Git repository and starter guides. Configure a remote when you need one.

To restore existing work, clone its private repository into `private/`. Run the shared Hub on each machine before opening the restored data.

Read `private/settings.json` for the owner, delivery system, system version, workspace format, and confirmed remote URLs.

Read `private/README.md` for the current session checkpoint and next action. Keep that handoff current before ending a session.

For first-time setup, start with company context, then product context and strategy. Mixed sources can inform several records in one session.

For area work, read the product brief and its area-specific evidence. Maintain a separate [area brief](playbook/filing.md#product-area-context) when the work warrants it.

Use the [opportunity workflow](playbook/opportunities.md) for proposed investments. Standing initiative guidance stays in context. Briefs, experiments, and planning comparisons belong in the workspace.

Agents automatically use [ingest-context](.agents/skills/ingest-context/SKILL.md) for context capture. The agent prompts for a missing or unfinished [PM remit](playbook/context.md#pm-remit). A remit can cover whole products or several areas within them.

Ask the agent to ingest a meeting by initiative and meeting title, date range, source link, or transcript file. See [summarize-meeting](.agents/skills/summarize-meeting/SKILL.md).

The agent discovers available connectors and asks you to clarify uncertain source or filing choices before it proceeds.

## Placement

Keep only `README.md`, `AGENTS.md`, `CLAUDE.md`, and `.gitignore` as root files. The checker enforces these homes:

| Home | Purpose | Repository |
| --- | --- | --- |
| `private/context/` | Reference material organised by company, product, product area, initiative, or PM | Private |
| `private/context/initiatives/<initiative>/` | Initiative overview and dated meeting summaries that qualify as event history | Private |
| `private/context/pm/context.md` | PM profile, including responsibilities, goals, dependencies, and interests | Private |
| `private/workspace/` | Work in progress and completed PM artifacts, organised by type | Private |
| `private/workspace/backlogs/<product>/initiatives.json` | Signed initiative register used by the backlog and roadmap commands | Private |
| `private/workspace/initiatives/<product>/<initiative>/` | Discovery Brief and Initiative Brief for the same initiative ID | Private |
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

Artifact paths are relative to `private/`. For example, `context/company/overview.md` holds company facts. An experiment testing a product choice belongs in `workspace/experiments/`.

Use [the filing rules](playbook/filing.md) to decide when a section earns a separate file. Keep records in place as work advances; their state changes, and their location follows their subject.

Start reference material in the entity overview. Create a topic folder only for a recurring reader need under the filing rules.

## Work

- [Framework](playbook/framework.md): strategy, goals, evidence, and experiments.
- [Opportunity workflow](playbook/opportunities.md) covers intake, discovery, Initiative Brief approval, and roadmap selection.
- [Generated backlog and roadmap](playbook/initiative-views.md) use the signed register.
- [Templates](templates/README.md): company context, product context, and PM artifacts.
- [Context rules](playbook/context.md) cover routing, sources, parent links, dates, and gaps.
- [Working practices](playbook/working.md): checkpoints, thought-partner mode, and quiet mode.
- [Git rules](playbook/git.md): the correct repository for saves, updates, and contributions.

The Git command name `workspace` selects the entire private repository.

Use Git and Python 3.9 or later. Initiative approval and its tests also require OpenSSH. Follow [the approval procedure](playbook/initiative-approvals.md).

```sh
python3 tools/pm.py check
python3 tools/pm.py backlog
python3 tools/pm.py roadmap
python3 -m unittest discover -s tests -v
python3 tools/pm.py git workspace status
python3 tools/pm.py git system status
python3 tools/pm.py new company-context context/company/overview.md --title "Company context"
```

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

Shared CI runs `check --system-only` and tests against fictional workspaces. Follow [the engineering and quality gates](playbook/git.md#engineering-and-quality-review-before-publication) before publication. Local checks also inspect ignored private records explicitly.

## Hooks and checks

Both clients load context and opportunity guidance at session start, then check the Hub before a normal stop. Hooks work from nested workspace directories.

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
