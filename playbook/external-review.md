# Review changes in a personal Workspace

Select the personal Workspace with `ORYX_WORKSPACE`. Run these commands from the PM’s local terminal. Use `oryx review init` once to create the managed `notes/` directory. Initialization preserves an existing unmanaged directory and reports that it needs reconciliation.

A task, launch-checklist, handoff-save or customization write can return `state: staged` and an ID. The current official record stays available while the proposal is pending. Run `oryx review show ID` to inspect the current wording, proposed wording, destination and effect. Run `oryx review decide ID` and type `save`, `discard` or `later` in the foreground terminal.

Saving rechecks the reviewed revision. If the draft, destination or supporting evidence changed, stage a fresh proposal against the current state. Repeating a completed decision returns the existing receipt.

Use `oryx valet reviews` or `oryx review status` to list proposals. Use `oryx review read` to read a coherent generation of managed notes. For a human-authored note, run `oryx review edit notes/launch.md` with your usual `VISUAL` or `EDITOR`. A saved edit records local PM-editor provenance.

## Stage a note

Supply the group on standard input to `oryx review stage`. A new note has a null base. For an existing note, use the revision returned by `oryx review read`. A null text requests removal. Every path in one note group publishes together.

```json
{
  "current_behavior": "The launch owner uses the previous checkpoint.",
  "reason": "The PM reviewed the handoff timing.",
  "effect": "The launch note will name the new checkpoint.",
  "changes": [
    {
      "path": "notes/launch.md",
      "base": null,
      "text": "Check the release report on Thursday.\n"
    }
  ]
}
```

To designate a note as governing text, add a `decisions` array to its change. Each item supplies `start`, `end`, literal `before` and `after`, `summary`, `conditions`, `exceptions` and `consequences`. Offsets count Unicode characters in the previous wording. The listed edits must reconstruct the entire proposed text. Future edits to that path retain the decision requirement.

## Recover an interrupted save

On the original machine and filesystem, reopen the same proposal with `oryx review decide ID`. A task, checklist or customization interrupted before publication can be reviewed again. If publication finished, Oryx verifies the two file states and completes the existing receipt.

An independently restored copy gets new filesystem identities. Select the untouched copy before running these commands.

```sh
oryx review recover-copy --archive "$LOCAL_BACKUP" --expect INVENTORY_SHA256
oryx review decide ID
```

Use the full local backup and the inventory digest retained separately when the backup was made. Oryx verifies the archive, compares the complete restored tree and matches both sides of every pending file transaction before binding the restored files. A changed copy or inconsistent transaction is held for inspection. Preserve such a copy and restore a separate untouched copy if needed.

## Supported environment

Protected publication requires a personal PM-owned Workspace on Linux. The local filesystem must support atomic rename exchange, exclusive creation, file locks and directory synchronization. External Codex and Claude sessions require an installed Core and an OS-isolated native process. Shell markers alone cannot isolate programs running as the same user.

Saving an external roadmap cycle publishes its comparison, register, approval receipt and affected experiment drafts as one group. Reopen the roadmap after an interruption. Oryx completes the approved group or holds a conflict for reconciliation. Keep the recovery history and later edits when resolving a conflict.

Use `oryx workspace publication REVISION` to reopen the approved group. Its immutable local Git tree contains the approval receipt and the exact reviewed files. The response supplies the Git directory and tree for `git show`.

A full same-machine backup preserves private drafts and recovery history. Keep those internal files out of ordinary Git synchronization.


## Launch a native client

Run `oryx agent codex --check-host` or `oryx agent claude --check-host` to exercise the actual native binary. The check verifies Linux namespaces, read-only files, private staging and absence of a controlling PM terminal. The default profile is offline and uses temporary account storage.

Choose `--note notes/launch.md` for each note the agent may read or propose changing. Each invocation handles one request. Type it at the prompt or supply it on standard input. The client receives its selected note copies and Core tools. Saving a proposed change still requires the PM’s separate review decision.

For hosted inference, select a dedicated absolute account directory with `--client-home`. Start with an empty, PM-owned directory. The first successful check provisions its client identity. Use the native client’s normal sign-in and tool configuration with that directory as its home. Keep the PM's personal account, credentials and browser profile separate.

```sh
oryx agent codex --check-host --client-home /private/native-codex
HOME=/private/native-codex codex login
oryx agent codex --client-home /private/native-codex --note notes/launch.md
```

The account profile requires rootless Bubblewrap, slirp4netns and Linux packet filtering. It permits DNS and public IPv4 TLS, and blocks host addresses, private networks and inbound connections. An unavailable kernel or client dependency holds startup. Installed native or connector capabilities depend on that dedicated account. A successful startup check verifies the local boundary. Model responses and connector permissions require their own qualification.
