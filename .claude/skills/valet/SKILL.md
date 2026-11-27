---
name: valet
description: Help the PM set up Oryx, find pending reviews and manage their selected Workspace.
---

# Valet

Run `oryx valet status` with the installed executable. Read the selected Workspace, owner, setup stage and next action.

For a new installation, ask the PM which personal directory and owner to use. Run `oryx valet setup` in the PM terminal for storage and GitHub choices. Use `oryx valet setup --owner NAME` for local storage.

Use `oryx valet reviews` to find pending decisions. The PM reviews the exact changes on the local review surface.
Use `oryx valet reviews --scope NAME` for an enrolled customer scope. Add `--github` for that scope’s GitHub pull requests.

Use `oryx valet git status` before synchronization. Confirm the repository and the requested remote operation with the PM. Use the same Workspace Git checks as the terminal.

Use `oryx valet scope create company` for a local company identity. Pass its ID with `valet scope create team --parent ID`. Run `valet scope list` to find local scopes and saved connections. Use `valet scope show ID --local` to inspect a local scope.

Use `valet scope show SCOPE` to inspect a customer-enrolled scope. Add `--github` to inspect the signed-in user’s GitHub access. Use `valet scope connect SCOPE` to remember the verified destination. To use GitHub for this connection, include `--github` in each command.

Run `valet scope sync SCOPE` to update the customer peer replica and its authorized live publications. With `--github`, sync checks registered official records against one branch head. It switches a read-only copy in the PM’s private cache outside the Workspace and installation. A scope supports up to 256 registered records and a one MiB encoded copy. The default location is under `~/.cache/oryx/github-replicas/`. Set `XDG_CACHE_HOME` before the first sync to choose another private location.

Use `valet github record` with the ordinary governance JSON input to read a record. Oryx checks the active account, repository, official branch, permission and registered bytes before displaying a cached result. A failed verification clears the active copy. The cache stays outside personal Git history and reviewed portable exports.

Connecting a scope enables a sync when the PM opens the local browser or starts a verified native agent session. Checks repeat every five minutes while the session is open. The peer can refresh previously authorized live publications during these checks.

Run `valet scope list` to see the last verified revision and whether the next check is due, pending or current. An offline check keeps its last successful revision and retries on the next cycle or eligible session. Run `valet scope disconnect SCOPE` to stop future checks for that provider.

Follow the [command catalog](../../../playbook/commands.md) for shared actions and the [installation guide](../../../playbook/installed-core.md) for recovery.
