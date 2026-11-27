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
export ORYX_WORKSPACE=/absolute/path/to/my-workspace
"$ORYX_CORE/bin/oryx" check --system-only
```

Choose an absolute Workspace path outside Core and other Git repositories. Create its parent directory first.
For an existing Workspace, select its original identity and location. Keep older unrecognized repositories intact during review.

## Start or resume work

Use the local CLI for this candidate. Protected Codex and Claude sessions require a qualified review writer for external Workspaces.
Initialize a fresh Workspace explicitly.

```sh
"$ORYX_CORE/bin/oryx" init-workspace --owner "Your name"
"$ORYX_CORE/bin/oryx" action --catalog
```

Workspace paths in the playbooks start at your selected private Git root. A checkout example using `studio/context/` means its `context/`.
Core resources such as `playbook/`, `templates/` and host skills stay in Core. From any directory, use the printed launcher path for commands.

## Update and recover

Install another verified archive with the same bootstrap and install store. A failed verification preserves the active Core.
To restore the previous archive, use the independently provisioned trusted key.

```sh
python3 "$TRUSTED_BOOTSTRAP" rollback --store "$INSTALL_STORE" --public-key "$PUBLISHER_PUBLIC_KEY"
```

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

Run `bin/oryx resource 'oryx://core/playbook/filing.md#when-a-section-earns-its-place'` from an installation. The command returns JSON with the current file path and optional heading anchor. A missing file or heading reports an error.
