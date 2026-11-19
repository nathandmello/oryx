---
name: pm-git
description: Inspect, commit, or synchronise PM Hub Git repositories. Use for saving PM work, updating the system, or connecting a remote.
---

# Use the correct PM Hub repository

1. Read [the Git rules](../../../playbook/git.md) before repository operations. Work from the outer PM Hub root.
2. Select `workspace` for PM work. Select `system` for toolkit changes. Use the Git rules for ambiguous or mixed requests.
3. Before save or sync, run both repository status commands. Read `private/settings.json` and verify the selected branch and destinations.
4. For a commit, stage the named paths in the selected repository. Review the staged diff and run relevant checks.
5. Use `python3 tools/pm.py git <system|workspace> <fetch|pull|push>` for authorised network operations.
6. For remote setup, verify the intended owner, repository, and visibility. Use the confirmed repository explicitly in GitHub tools.
7. Stop if the destination is ambiguous, differs from settings, or mixes repositories. Preserve existing authorisation limits.
8. Report the repository, operation, and outstanding local changes.
