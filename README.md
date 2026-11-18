# PM Hub

A personal product management workspace with a shared system and a separate private data repository.

Read the [constitution](AGENTS.md) for purpose, ownership, writing rules, and agent conduct.

## Start

Clone the shared system, then open its root in Codex or Claude. Initialise a private workspace once:

```sh
python3 tools/pm.py init-workspace --owner "Your name" --delivery-system "Your delivery system"
```

The command creates `workspace/` with its own Git repository and empty starter files. It creates no remote, commit, or push.

To restore existing work, clone its private repository into `workspace/` instead. A new machine needs both repositories.

Read `workspace/settings.json` for the owner, delivery system, system version, workspace format, and confirmed remote URLs.

Company context, product context, and strategy start empty. Capture them in separate sessions, in that order.

## Placement

Keep only `README.md`, `AGENTS.md`, `CLAUDE.md`, and `.gitignore` as root files. The checker enforces these homes:

| Home | Purpose | Repository |
| --- | --- | --- |
| `workspace/context/` | Organisation and business context | Private workspace |
| `workspace/products/<product>/` | Product context and active PM work | Private workspace |
| `workspace/settings.json` | Personal settings and expected remotes | Private workspace |
| `playbook/` | Methods, working practices, Git rules, and release metadata | Shared system |
| `templates/` | Starters for requested artifact types | Shared system |
| `tools/` and `tests/` | Commands, empty workspace seeds, and checks | Shared system |
| `.agents/skills/` | Canonical shared skills | Shared system |
| `.claude/`, `.codex/`, `.github/` | Native client and CI configuration | Shared system |

Paths such as `context/` in artifact commands are relative to `workspace/`. Keep shared product goals and research at product level.

Group initiative records when needed. Keep records in place as work advances; their state changes, and their location follows their subject.

A new home needs a current purpose and updated checks. Add templates for requested artifact types.

## Work

- [Framework](playbook/framework.md): strategy, goals, evidence, and experiments.
- [Templates](templates/README.md): company context, product context, and PM artifacts.
- [Context rules](playbook/context.md): sources, parent links, dates, and gaps.
- [Working practices](playbook/working.md): checkpoints, thought-partner mode, and quiet mode.
- [Git rules](playbook/git.md): the correct repository for saves, updates, and contributions.

Use Git and Python 3.9 or later. The tools use the Python standard library.

```sh
python3 tools/pm.py check
python3 -m unittest discover -s tests -v
python3 tools/pm.py git workspace status
python3 tools/pm.py git system status
python3 tools/pm.py new company-context context/company.md --title "Company context"
```

Use `extend-hub` to add capabilities and `red-team` for requested critique. Say "quiet" or "just capture" to stop unsolicited critique.

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

Pulls require clean files and a fast-forward update. Format changes stop for migration review. System updates record the accepted version in private settings.

Shared CI runs `check --system-only` and tests against fictional workspaces. Local checks also inspect ignored private records explicitly.

## Hooks and checks

Both clients check the hub at session start and before a normal stop. Hook commands locate the system from nested workspace directories.

In Codex, review and trust the project hooks through `/hooks`. In Claude, accept project trust and inspect `/hooks`.

Managed settings can disable hooks. A failed stop requests one correction, then permits a handoff with the unresolved failure visible.

Checks cover repository boundaries, agent entry points, skill copies, links, writing limits, artifact contracts, source dates, and review deadlines.

Semantic review covers clarity, accuracy, source authority, and decision quality. External change detection arrives when needed.

Connect GitHub remotes after their destinations are known. Require the CI `check` job through branch protection when appropriate.

## Client references

Initial client wiring was checked on 2026-11-18 with Codex CLI 0.170.0 and Claude Code 2.1.327.

- [Codex hooks](https://learn.chatgpt.com/docs/hooks)
- [Codex skills](https://learn.chatgpt.com/docs/build-skills)
- [Claude hooks](https://code.claude.com/docs/en/hooks)
- [Claude instructions](https://code.claude.com/docs/en/memory)
