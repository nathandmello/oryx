# Git and GitHub operations

The outer checkout is the shared system repository. `studio/` is an independent Git repository, ignored by the system.

Keep each repository's history, branches, staging area, and remotes separate. Open a [protected PM session](overrides.md) for workspace work. Run system updates from your terminal.

## Choose the repository

| Request | Target |
| --- | --- |
| Save, commit, sync, pull, or push my PM work | `workspace` |
| Update the toolkit, system, skills, or templates | `system` |
| Check for system updates | `system fetch`; review before a pull |

The command name `workspace` selects the whole private repository, including context.

Interpret an unqualified save, sync, or push as private repository work. If only system changes exist, report that and clarify the target.

For mixed changes, keep commits separate. Authorisation for one target does not authorise the other.

## Inspect and save

Run `python3 tools/pm.py git workspace status` and `python3 tools/pm.py git system status` before a save or synchronisation.

Read `studio/settings.json`. Verify the actual Git root, branch, changed files, staged changes, and fetch and push URLs.

Stage explicit paths with `git -C studio add -- <paths>` for PM work. Use the outer root for system changes.

Review the staged diff, then commit in that same repository. Preserve unrelated edits. Run the relevant checks before a commit.

An instruction to commit authorises that commit. A push or sync instruction authorises its stated remote operation; retain other session limits.

Report which repository was committed or synchronised and which changes remain local.

## Connect a remote

A fresh setup has no remotes. Obtain the intended owner, repository name, and visibility from the PM before external creation.

Use an authorised GitHub connection to create or inspect the repository. The PM workspace destination must be private.

Configure `origin` in the selected repository. Verify visibility and access before any private data push.

Record the confirmed URL under `remotes.system` or `remotes.workspace` in private settings. Keep credentials in the credential manager.

The destinations must differ. Match the remote URL to its confirmed setting before every network operation.

Pass an explicit owner and repository to GitHub tools and CLI commands. Derive them from the confirmed target, never the current directory.

Private PM work remains in its private repository.

## Pull and push

Use `python3 tools/pm.py git <system|workspace> <fetch|pull|push>` for normal network operations.

The wrapper verifies the repository, settings, origin, and tracking branch. Preserve local changes before synchronising.

Push sends the current branch to the same branch on the confirmed origin. It does not push tags or other branches.

Pull permits a fast-forward. Keep divergent histories for reconciliation. See [the two-machine upgrade procedure](updates.md#using-two-machines).

A system pull checks compatibility. The installed release handles the private data update. Save private changes in its repository when requested.

A workspace pull stops if incoming settings change the required system version or expected destinations. Review the matching system release or remote change.

Commit, merge, release, repository creation, publication, and changes to remotes remain subject to the PM's actual instruction.

Never infer permission for force pushes, mirrors, bulk pushes, deletion, or history rewrites. Review those requests separately.

## Boundaries and recovery

Keep PM data, personal settings, and real customer examples inside the private repository. Shared tests use fictional data.

The checker rejects tracked Studio directories and Git links in the system index, including [earlier repository roots](updates.md#what-runs). Ignore rules alone do not remove tracked files.

A system push checks the branch’s reachable history. A system pull checks both local and incoming histories. Earlier commits containing Studio files block either operation.

Use explicit private paths when the agent searches or checks PM work. Root Git commands omit ignored records.

Record system and workspace format versions together. Structural changes need a tested migration and a recovery point in the private repository.

Keep migrations small. Session-start alignment applies local upgrades after backup. Network operations require an authorised Git action.
