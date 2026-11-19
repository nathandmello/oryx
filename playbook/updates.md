# Updating an installed Hub

Open the updated Hub to verify compatibility.

Releases 0.3.1 through 0.8.0 use private format 2.

| Release | Change |
| --- | --- |
| 0.8.0 | Adds launch evidence history, decision conflict reviews, guardrail readings, and measurement corrections. |
| 0.6.0 | Opens [roadmaps, PM tasks, and launch checklists](local-ui.md) in a local browser. The app reads and updates existing private records. |
| 0.5.0 | Adds [Hub commands](commands.md) and optional [reply preferences](working.md#reply-preferences). Existing profiles use Hub defaults. |
| 0.4.2 | Automates [publication](publication.md). |

Release 0.4.1 adds [initiative tasks and launch checklists](initiative-work.md) on demand.

Release 0.4.0 adds task context, a [metric registry](metrics.md), and optional artifact conversion.

Release 0.3.5 adds [context section leads](filing.md#when-a-section-earns-its-place). Release 0.3.4 adds [initiative meeting transcripts](../.agents/skills/summarize-meeting/SKILL.md).

`playbook/release.json` reports format 1 for older updaters. The private format is in `playbook/workspace-format.json`.

Check [signed prototype compatibility](initiative-approvals.md#existing-private-work).

Update every client before sharing new records. Older clients reject new transaction types. Existing format-2 signatures remain readable.
Verify historical readiness and thresholds against dated sources.
For an active discovery approved before source binding, review the plan and sources together. Sign a fresh `start-discovery` before concluding.

## What runs

1. The trusted session-start hook calls `python3 tools/pm.py align`. With hooks disabled, the agent follows AGENTS.md.
2. The Hub locates the private Git repository. Conflicting repository locations require inspection.
3. It verifies a full local backup before changing the private layout. Git history and remotes travel with the repository.
4. It moves reference records to `private/context/` and work to `private/workspace/`. Record IDs remain stable.
5. It converts valid legacy remit data to the PM’s Markdown profile. It retains conflicts for review.
6. The agent reports ambiguous ownership, missing evidence, and occupied destinations.

`align --status` previews the upgrade. Older installations move from `workspace/` to `private/`.

## Review artifact changes with the user

Use [the upgrade review skill](../.agents/skills/review-hub-upgrade/SKILL.md). Explain benefits and run `align --status`. Ask before conversion. Alignment backs up older formats and preserves artifact contents.

## Using two machines

Save and push the verified private migration from one machine when authorised. On the second, update the shared Hub, then pull private work before committing its local migration. The pull can accept an identical migration from the same history. It checks staged work and preserves working files.

If changes differ, restore the remote private repository in a separate checkout. Reconcile both copies, including staged and untracked files.

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

Before the first migration write, the Hub snapshots the entire local installation. It includes both Git repositories, uncommitted work, ignored files, attachments, and empty directories.

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

Use the reported `installation_backup` path. Layout migration receipts use `.git/pm-hub-backup-<version>-layout-2.json`. Other release backups use `.git/pm-hub-backup-<version>.json`.

Verify `SHA256SUMS` in the archive directory. Extract into a new empty private directory with a tool that preserves permissions and extended attributes.

On macOS, run these commands from the archive directory. Use the private directory name recorded in the archive.

```sh
shasum -a 256 -c SHA256SUMS
mkdir -m 700 /path/to/new-recovery-directory
tar -xpzf hub.tar.gz -C /path/to/new-recovery-directory
git -C /path/to/new-recovery-directory fsck --full
# Use workspace for an archive of the older layout.
private_name=private
git -C "/path/to/new-recovery-directory/$private_name" fsck --full
```

For GNU tar on Linux, use `--xattrs --xattrs-include='*'` when restoring extended attributes.

Compare the recovered working files before switching installations.

Keep a private off-device recovery copy. The archive can contain credentials from ignored files. It stays local during Git operations.

Before conversion, the tool verifies a ZIP with the exact bytes of each existing affected file, including untracked files. It stores the plan alongside those originals.

The private path is `.hub-history/<id>.zip`. Each original member is named `original/<old-path>`. Extract to a separate location before comparing or restoring any file.

Preserve the archive and ledger with private work. A pending journal resumes interrupted work. Changed inputs stop the transaction for inspection. Never force an overwrite after a conflict.

A saved version of each displaced file remains under private Git metadata at `.git/pm-hub-recovery/filing/<id>/`. This also preserves edits from an open editor during conversion.

An older Hub requires its matching private recovery point. Preserve newer work before restoring either repository.
