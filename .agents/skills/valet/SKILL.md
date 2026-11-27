---
name: valet
description: Help the PM set up Oryx, find pending reviews and manage their selected Workspace.
---

# Valet

Run `oryx valet status` with the installed executable. Read the selected Workspace, owner, setup stage and next action.

For a new installation, ask the PM which personal directory and owner to use. Run `oryx valet setup --owner NAME` in the PM terminal.

Use `oryx valet reviews` to find pending decisions. The PM reviews the exact changes on the local review surface.
Use `oryx valet reviews --scope NAME` for an enrolled customer scope. Add `--github` for that scope’s GitHub pull requests.

Use `oryx valet git status` before synchronization. Confirm the repository and the requested remote operation with the PM. Use the same Workspace Git checks as the terminal.

Follow the [command catalog](../../../playbook/commands.md) for shared actions and the [installation guide](../../../playbook/installed-core.md) for recovery.
