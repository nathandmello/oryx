# Install Core and select a Workspace

A signed Core archive runs separately from the Workspace that holds PM work. Follow these steps for the archive candidate.

## Verify and install Core

Obtain the trusted bootstrap and publisher public key through a separately authenticated channel. Obtain the archive and its detached signature from your distributor.

Use a private installation directory under an existing parent. Keep this directory outside the Workspace.
Run the bootstrap with Python 3.9 or later on a supported POSIX system with OpenSSL.

```sh
python3 "$TRUSTED_BOOTSTRAP" install --store "$INSTALL_STORE" \
  --archive "$ARCHIVE" --signature "$SIGNATURE" --public-key "$PUBLISHER_PUBLIC_KEY"
```

The installer prints the active Core directory. Resolve it again when opening a terminal after an update.

```sh
ORYX_CORE=$(python3 "$TRUSTED_BOOTSTRAP" current --store "$INSTALL_STORE")
export PATH="$ORYX_CORE/bin:$PATH"
export ORYX_WORKSPACE=/absolute/path/to/my-workspace
"$ORYX_CORE/bin/oryx" check --system-only
```

Choose an absolute Workspace path outside Core and other Git repositories. Create its parent directory first.
For an existing Workspace, select its original identity and location. Keep older unrecognized repositories intact during review.

## Start or resume work

Run `oryx valet setup` in your foreground terminal to choose local storage, connect an existing private GitHub repository or create one. Setup can restore a committed Workspace in a private directory with its original identity.

Creating a repository, making the local commit and first sharing its history on GitHub are separate decisions. Review the verified destination, branch, audience and files in every reachable commit before approving the first push. Review drafts and search caches stay local. See [Git and remotes](git.md) and [protected host startup](external-review.md).

For local setup, you can also supply the owner directly.

```sh
"$ORYX_CORE/bin/oryx" init-workspace --owner "Your name"
"$ORYX_CORE/bin/oryx" action --catalog
```

Workspace paths start at the selected Git root. Follow the [placement map](../README.md#placement) for fresh work. Onboarding and handoff checkpoints live in `.oryx/state/`. Search indexes in `.oryx/cache/` rebuild from permitted records.

Source examples using `studio/context/` mean the selected Workspace’s `context/`. Older Workspaces keep work in `workspace/` and personal rules in `customizations/`. Use their recorded paths when resuming or restoring work.

Core resources such as `playbook/`, `templates/` and host skills stay in Core. From any directory, use the printed launcher path for commands.

## Update and recover

Install another verified archive with the same bootstrap and install store. A failed verification preserves the active Core.
To restore the previous archive, use the independently provisioned trusted key.

```sh
python3 "$TRUSTED_BOOTSTRAP" rollback --store "$INSTALL_STORE" --public-key "$PUBLISHER_PUBLIC_KEY"
```

For a configured release channel, use `oryx release update` and `oryx release status`.
Use `oryx release rollback` when an update also recorded Workspace version changes.
The update command records the Core and Workspace recovery outcomes. It reports the status of any queued issue separately.

A restored portable Workspace can retain an earlier supported version. Run the verified channel update with that Workspace selected. If the Core is already current, the local receipt marks the update `workspace_only`. To reverse that change, keep the same Workspace selected and use `oryx release rollback --workspace-only INCIDENT --store STORE --public-key KEY` with its update incident. The active Core and later unrelated PM edits stay in place.

Read the active Core path after a rollback. Use Workspace Git commands only for authorized private repository actions.
For a local Workspace recovery inventory, run the following command on the machine that holds the work.

```sh
"$ORYX_CORE/bin/oryx" recovery inventory "$ORYX_WORKSPACE"
```

Keep the inventory private. Review its omissions and keep the digest independently.
Use `recovery backup --help` and `recovery restore --help` to create and verify a separate local copy.
Core rollback and Workspace recovery have separate outcomes. Preserve subsequent PM edits and reconcile uncertain external deliveries before resuming them.

## Open a Core reference

New external Workspaces store Core links as `oryx://core/` references. The stored path stays valid when the active release changes. Workspace records link to each other by relative path.

Run `oryx resource 'oryx://core/playbook/filing.md#when-a-section-earns-its-place'` from an installation. The command returns JSON with the current file path and optional heading anchor. A missing file or heading reports an error.

For an existing format-2 Workspace, follow [the adoption and portable recovery instructions](record-adoption.md).

Use [local review](external-review.md) for staged wording and [guided work](guided-work.md) to continue a reviewed checkpoint.
