# Updating oryx

Private format 2 applies.

| Release | Change |
| --- | --- |
| 0.12.0 | Adds the [company walkthrough](company-context.md) for all Studios. Existing records supply evidence for review. Product work waits for the forthcoming PM and product walkthroughs. |
| 0.11.1 | Updates [conversation guidance](conversation.md) to ground agreement in evidence. Capture and coaching keep omissions open and preserve confirmed limits. |
| 0.11.0 | Adds [workspace overrides](overrides.md) and [template and roadmap customization](customization.md). Existing records retain their contents. |
| 0.10.0 | Adds [decision coaching](conversation.md), [weekly review](decision-review.md), and [forecasts](decision-forecasts.md). |
| 0.8.1 | Keeps [dated backlog reviews](initiative-views.md#read-the-views) visible when an approval is stale. |
| 0.8.0 | Adds launch evidence history, decision conflict reviews, guardrail readings, and measurement corrections. |
| 0.6.1 | Requires [browser impact evidence](local-ui.md#review-workflow-changes) for changes to roadmap, task, and launch checklist workflows. |
| 0.6.0 | Opens [roadmaps, PM tasks, and launch checklists](local-ui.md) in a local browser. The app reads and updates existing private records. |
| 0.5.0 | Adds [oryx commands](commands.md) and optional [reply preferences](working.md#reply-preferences). Existing profiles use oryx defaults. |
| 0.4.2 | Automates [publication](publication.md). |

Release 0.4.1 adds [initiative tasks and launch checklists](initiative-work.md) on demand.

Release 0.4.0 adds task context, a [metric registry](metrics.md), and optional artifact conversion.

Release 0.3.5 adds [context section leads](filing.md#when-a-section-earns-its-place). Release 0.3.4 adds [initiative meeting transcripts](../.agents/skills/summarize-meeting/SKILL.md).

`playbook/release.json` reports format 1 for older updaters. The private format is in `playbook/workspace-format.json`.

Check [signed prototype compatibility](initiative-approvals.md#existing-private-work).

Update all clients before sharing new transactions or discovery approvals with custom sections. Existing format-2 signatures remain readable.
Verify historical readiness and thresholds against dated sources.
For an active discovery approved before source binding, review the plan and sources together. Sign a fresh `start-discovery` before concluding.

## What runs

1. The trusted session-start hook calls `python3 tools/pm.py align`. With hooks disabled, the agent follows AGENTS.md.
2. oryx locates the private Git repository. Conflicting repository locations require inspection.
3. It verifies a full local backup before changing the private layout. Git history and remotes travel with the repository.
4. It moves reference records to `studio/context/` and work to `studio/workspace/`. Record IDs remain stable.
5. It converts valid legacy remit data to the PM’s Markdown profile. It retains conflicts for review.
6. The agent reports ambiguous ownership, missing evidence, and occupied destinations.

`align --status` previews these repository moves. Inspect `studio_moves` for customization files. Update external bookmarks and scripts that use the previous path.

| Earlier repository root | Current repository root |
| --- | --- |
| `private/` | `studio/` |
| `workspace/` | `studio/` |

## Review artifact changes with the user

Use [the upgrade review skill](../.agents/skills/review-hub-upgrade/SKILL.md). Explain benefits and run `align --status`. Ask before conversion. Alignment backs up older formats and preserves artifact contents.

## Using two machines

When authorised, push one machine’s verified Studio migration. Update core and align the second machine before pulling Studio.

Format 2 can adopt an identical migration, then receive later commits.
The index must match its old commit. Git-visible working files must match the migration commit, including deletions.

For staged changes, extra untracked work, or mismatches, keep the checkout intact.
Clone the confirmed Studio branch into `studio/` in a separate matching oryx checkout. Check and reconcile both copies before switching.

## Convert existing work

Apply [the filing test](filing.md) and retain original evidence.

Compare claims with inspected originals. Check actors, exclusions, scope, conditions, numbers, dates, and certainty. Separate decisions from proposals and source coverage from assumptions.

Restore supported clauses, route mixed subjects, and retain unknowns beside affected claims. Use its current template.

Preview the selected records with `align --preview-plan`. Apply the approved plan with `align --apply-plan`.

| Plan field | Meaning |
| --- | --- |
| `id`, `reason` | Stable transaction name and evidence-based reason for the change |
| `changes[]` | One row per affected record or referring document |
| `path`, `before`, `text` | Retained output, current SHA-256, and complete resulting Markdown. Use `absent` only for a new destination receiving an existing record. |
| `path`, `before`, `into` | Fold a derivative into the specified retained destination. Account for its substantive lines and update incoming references. |
| `replacements[]` | For each superseded line, supply `line`, unchanged local primary `source`, its `digest`, the exact complete source line as `quote`, and its retained `destination`. |

Keep original reports, cited passages, links, and anchors. Record the evidence reviewed or the specific blocker.

```sh
python3 tools/pm.py align --record PATH --digest CURRENT_DIGEST --outcome reviewed --note "Verified the exclusion against the approved board minutes, section 3."
```

For a retained original, use `--outcome source`. It remains protected from later conversion.

Supply an unchanged Markdown or text source for a replacement. PDF evidence also accepts a checked `page` when `pdftotext` is available.

For an external original, use a permitted local extract with its citation and locator. Record missing access as waiting.

For redundant navigation, supply its `line` and `disposition: navigation`. The tool checks its visible wording before archiving it.

For a verbatim line routed elsewhere, give its `line` and retained `destination`. Preserve the meaning of headings and verify changed links and anchors.

Use `waiting` for specific blockers. Recheck them with `align --status`.

Run `python3 tools/pm.py check` after conversion. Compare the result with the original sources. Report completed changes, retained records, and unresolved evidence separately.

## Whole-installation backup

Before the first migration write, oryx snapshots the entire local installation. It includes both Git repositories, uncommitted work, ignored files, attachments, and empty directories.

Links are stored as links. The archive omits its own backup directory. Special files, external Git object stores, or verification failures stop migration.

The archive records POSIX modes and extended attributes exposed by Python. On macOS, use a native backup for Finder tags, resource forks, or ACLs.

| Update path | Backup timing |
| --- | --- |
| Current wrapper or the released 0.2.0 wrapper | A version-changing system pull verifies a backup before merging the shared update. Startup verifies the layout backup before private conversion. |
| Direct shared Git pull | Startup backs up the updated toolkit and the original private layout. |
| Released 0.1.0 wrapper | The wrapper can set the private version to the incoming release first. The layout backup includes that setting. |

The receipt identifies `.git/pm-hub-backups/<id>/hub.tar.gz` and its SHA-256.

Retries reuse the verified snapshot.

## Recovery

Use `installation_backup`. Layout migration receipts use `.git/pm-hub-backup-<version>-layout-2.json`. Studio customization moves use `.git/pm-hub-backup-<version>-studio.json`. Other release backups use `.git/pm-hub-backup-<version>.json`.

Verify `SHA256SUMS` in the archive directory. Extract into a new empty private directory with a tool that preserves permissions and extended attributes.

On macOS, start in the archive directory. Check both recovered repositories.

```sh
shasum -a 256 -c SHA256SUMS
mkdir -m 700 /path/to/new-recovery-directory
tar -xpzf hub.tar.gz -C /path/to/new-recovery-directory
cd /path/to/new-recovery-directory
git fsck --full
git --git-dir */.git fsck --full
```

For GNU tar on Linux, use `--xattrs --xattrs-include='*'` when restoring extended attributes.

Compare the recovered working files before switching installations.

Keep a private off-device recovery copy. The archive can contain credentials from ignored files. It stays local during Git operations.

Before conversion, the tool verifies a ZIP containing each affected file, including untracked files. It stores the plan alongside those originals.

The private path is `.hub-history/<id>.zip`. Each original member is named `original/<old-path>`. Extract to a separate location before comparing or restoring any file.

Preserve the archive and ledger with private work. A pending journal resumes interrupted work. Changed inputs stop the transaction for inspection. Never force an overwrite after a conflict.

A saved version of each displaced file remains under private Git metadata at `.git/pm-hub-recovery/filing/<id>/`. This also preserves edits from an open editor during conversion.

An older oryx release requires its matching private recovery point. Preserve newer work before restoring either repository.
