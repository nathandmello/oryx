---
name: extend-hub
description: Use automatically when changing shared oryx code or guidance, including fixes, instructions, playbooks, skills, templates, tools, and tests. Routine private PM record edits use their own workflow.
---

# Extend oryx

Read `AGENTS.md` and the existing work relevant to the request. Complete the dependency review for every shared change.

## Add or change a capability

1. Define the immediate need and observable completion condition. Reuse an existing capability when it fits.
2. Find the authoritative sources and artifact owners. Preserve the boundary with the configured delivery system.
3. Choose the smallest complete change. Keep unrelated features outside its scope.
4. Define the record format, source references, relationships, checkpoints, and review triggers that the work needs.
5. Put judgment and method guidance in the skill. Put deterministic checks in scripts.
6. Identify the questions an activity must answer. Specify which [scoped evidence](../../../playbook/context-search.md) it retrieves and which gaps need PM input.
7. Add meaningful tests for new enforcement. Check a valid case and a rejected case.
8. Keep instructions portable. Author shared skills under `.agents/skills/`.

For PM-facing work, identify what oryx can prepare, what the PM decides, and where they review the wording.
Verify the same craft steps and evidence checks under deadline pressure.
Test the activity from an ordinary PM request with relevant evidence, a material gap, and a plausible unrelated match.

For every shared slash command change, follow the [command convention](../../../playbook/commands.md).
Register its path and target in the shared catalog. Preserve published paths with aliases when needed.
Check discovery and execution through `pm.py action`. Compare with the base commit for an existing command change.

## Dependency review

1. Identify the changed behaviour, command, path, field, or term. Trace what defines it and what relies on it.
2. Search for old and new names, including hidden project directories. Follow callers, links, examples, and tests.
3. Compare those uses with the intended behaviour. Read related guidance even when it describes the behaviour in different words.
4. Check the README, playbooks, skills, templates, workspace seeds, tools, hooks, CI, and tests wherever the change reaches them.
5. Fix stale dependants in the same change. Check existing records and fresh workspace setup when a format or default changes.
6. Review staged and unstaged changes, including new, renamed, and deleted files. Run `python3 tools/pm.py sync-skills` after skill changes.
7. Run affected tests. Exercise changed instructions and examples through their normal entry points.
8. Run `python3 tools/pm.py check`. In a system-only checkout, use `--system-only` and verify affected private workflows in a disposable workspace.
9. Report what you traced and corrected. Name the checks you ran and any remaining gaps.

## Review browser impact

For changes to roadmap, task, or launch checklist workflows, trace both the terminal and browser entry points.
Use the same records, workflow handlers, and validation in both interfaces.
Update affected browser views or controls in the same change. Check existing records when fields or rules change.

Add or update a [Playwright scenario](../../../playbook/local-ui.md#browser-tests) when the browser behavior changes.
Use the required [Browser impact section](../../../playbook/local-ui.md#review-workflow-changes).
Check the review gate's path list when moving a workflow entry point.

## Prepare a release

Test existing installations with arbitrary filenames, untracked records, missing evidence, and a second run when filing changes. Verify that original bytes remain recoverable.

For each change, record its effect on installed workspaces in the release or pull request description. Follow [the release process](../../../playbook/git.md#existing-workspaces-at-release).

Use [review-hub-upgrade](../review-hub-upgrade/SKILL.md) for user handoff. Explain benefits, audit existing records, and offer a choice before conversion.

Verify direct shared Git pulls and released wrappers against the actual release version and private format.

Follow [the prepublication gates](../../../playbook/git.md#codex-review-before-publication). Open ready for Codex code and security review. Merge the verified head after both reviews and required CI pass. Retest fixes and state verification limits.

The PM's request authorises work within its scope. Ask only for a missing decision or an action outside that authority.

Use the placement map in `README.md`. Create templates only for requested artifact types; a future activity alone is insufficient.

For repository operations, read [the Git rules](../../../playbook/git.md). Keep private settings and PM records inside `studio/`.
