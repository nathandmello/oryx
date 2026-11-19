# Updating an installed Hub

Pull and open the shared Hub. The agent handles private updates.

Release 0.3.0 accepts private layout 1 from 0.1.0 and 0.2.0.

Legacy responsibilities count as confirmed. Empty or follow-only remits prompt for ownership.

Update each machine to 0.3.0 before sharing area briefs, product-area keys, or an explicit remit status. See [PM remit](context.md#pm-remit).

Existing briefs stay in place. [Area filing rules](filing.md#product-area-context).

## What runs

1. The trusted session-start hook runs `python3 tools/pm.py align`. With hooks disabled, AGENTS.md directs the agent to run it first.
2. Alignment inventories tracked and untracked Markdown visible to private Git. It skips ignored files, hidden paths, secrets, and symlinks.
3. It preserves original starter guidance before updating exact installed paragraphs. Local additions remain available for review.
4. It records candidates in `.hub-upgrades.json` under `record-filing-0.2`. Paths and explicit record types supply hints.
5. The agent reads every pending record, its sources, and incoming links. It executes supported corrections during the session.
6. The stop hook flags pending reviews. A specific unresolved dependency can stay waiting while the PM continues other work.

Each checkout finds local records missing from the private ledger, at any depth. Determine ownership and redundancy from contents.

## Convert existing work

Apply [the filing test](filing.md) to each record. Retain original evidence and purposeful records. Preserve stable IDs when moving records.

Compare claims with inspected originals. Check actors, exclusions, scope, conditions, numbers, dates, and certainty. Separate decisions from proposals and source coverage from assumptions.

Restore supported clauses, route mixed subjects, and retain unknowns beside affected claims. Use the matching template to bring an older brief into the current format.

The agent submits JSON on standard input to `align --preview-plan`, then `align --apply-plan`. The PM has no command to run.

| Plan field | Meaning |
| --- | --- |
| `id`, `reason` | Stable transaction name and evidence-based reason for the change |
| `changes[]` | One row per affected record or referring document |
| `path`, `before`, `text` | Retained output, current SHA-256, and complete resulting Markdown. Use `absent` only for a new destination receiving an existing record. |
| `path`, `before`, `into` | Fold a derivative into the specified retained destination. Account for its substantive lines and update incoming references. |
| `replacements[]` | For each superseded line, supply `line`, unchanged local primary `source`, its `digest`, the exact complete source line as `quote`, and its retained `destination`. |

Keep original reports and registered evidence in place. Update links and preserve cited passages and anchors.

An unchanged record needs a reviewed disposition with the evidence inspected. For a blocked correction, keep the existing record and identify the missing source or decision.

```sh
python3 tools/pm.py align --record PATH --digest CURRENT_DIGEST --outcome reviewed --note "Verified the exclusion against the approved board minutes, section 3."
```

For a retained original, use `--outcome source`. It remains protected from later conversion.

Supply an unchanged Markdown or text source for a replacement. PDF evidence also accepts a checked `page` when `pdftotext` is available.

For an external original, use a permitted local extract with its citation and locator. Record missing access as waiting.

For redundant navigation, supply its `line` and `disposition: navigation`. The tool checks its visible wording before archiving it.

For a verbatim line routed elsewhere, give its `line` and retained `destination`. Preserve the meaning of headings and verify changed links and anchors.

Use `waiting` for a specific blocker. Read-only `align --status` shows outstanding items and digests. Revisit them when evidence arrives.

Run `python3 tools/pm.py check` after conversion. Compare the result with the original sources. Report completed changes, retained records, and unresolved evidence separately.

## Whole-installation backup

Before the first migration write, the Hub snapshots the entire local installation. It includes both Git repositories, uncommitted work, ignored files, attachments, and empty directories.

Links are stored as links. The archive omits its own backup directory. Special files, external Git object stores, or verification failures stop migration.

The archive records POSIX modes and extended attributes exposed by Python. Platform-specific metadata outside those APIs needs a native backup when required.

The current updater snapshots before merging a version change.

A plain shared Git pull updates the toolkit first. Session startup then captures the untouched private workspace.

The old 0.1.0 updater can update private version metadata before the new code runs. Its snapshot reflects that setting and the updated shared checkout.

The local archive is `.git/pm-hub-backups/<id>/hub.tar.gz`. Its release receipt records the ID and SHA-256.

The tool verifies the archive against live files. Retries reuse the snapshot.

## Recovery

For a full restore, locate the release receipt under `workspace/.git/pm-hub-backup-<version>.json`. Use its ID to locate the archive.

Verify `SHA256SUMS` in the archive directory. Extract into a new empty private directory with a tool that preserves permissions and extended attributes.

On Linux, run GNU tar from the backup directory.

```sh
sha256sum -c SHA256SUMS
mkdir -m 700 /path/to/new-recovery-directory
tar --xattrs --xattrs-include='*' -xpzf hub.tar.gz -C /path/to/new-recovery-directory
git -C /path/to/new-recovery-directory fsck --full
git -C /path/to/new-recovery-directory/workspace fsck --full
```

Compare the recovered working files before switching installations.

Keep a private off-device copy for recovery after disk loss. The archive can contain credentials from ignored files. It stays local during Git operations.

Before conversion, the tool verifies a ZIP with the exact bytes of each existing affected file, including untracked files. It stores the plan alongside those originals.

The private path is `.hub-history/<id>.zip`. Each original member is named `original/<old-path>`. Extract to a separate location before comparing or restoring any file.

Preserve the archive and ledger with private work. A pending journal resumes interrupted work. Changed inputs stop the transaction for inspection. Never force an overwrite after a conflict.

A saved version of each displaced file remains under private Git metadata at `.git/pm-hub-recovery/filing/<id>/`. This also preserves edits from an open editor during conversion.

An older Hub requires its matching private recovery point. Preserve newer work before restoring either repository.
