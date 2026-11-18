---
name: extend-hub
description: Add a requested workflow, tool, integration, or record format to PM Hub. Excludes routine content edits.
---

# Extend PM Hub

Read `AGENTS.md` and the existing work relevant to the request.

1. Define the immediate need and observable completion condition. Reuse an existing capability when it fits.
2. Find the authoritative sources and artifact owners. Preserve the boundary with the configured delivery system.
3. Choose the smallest complete change. Keep unrelated features outside its scope.
4. Define the record format, source references, relationships, checkpoints, and review triggers that the work needs.
5. Put judgment and method guidance in the skill. Put deterministic checks in scripts.
6. Support partial progress and explicit wait points. Enforce required information before the action that depends on it.
7. Add meaningful tests for new enforcement. Check a valid case and a rejected case.
8. Keep instructions portable. Author skills under `.agents/skills/`, then run `python3 tools/pm.py sync-skills`.
9. Update the entry points that the new work needs. Run `python3 tools/pm.py check` and affected tests.
10. Report the capability, its checks, and its limits. Keep the response concise.

The PM's request authorises work within its scope. Ask only for a missing decision or an action outside that authority.

Use the placement map in `README.md`. Create templates only for requested artifact types; a future activity alone is insufficient.

For repository operations, read [the Git rules](../../../playbook/git.md). Keep private settings and PM records inside `workspace/`.
