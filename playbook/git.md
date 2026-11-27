# Git and GitHub operations

For archives, see [installed Core](installed-core.md). System Git operations require a checkout. Its private repository defaults to `studio/`.

Keep each repository's history, branches, staging area, and remotes separate. Open a [protected PM session](overrides.md) for workspace work. Run system updates from your terminal.

## Choose the repository

| Request | Target |
| --- | --- |
| Save, commit, sync, pull, or push my PM work | `workspace` |
| Update the toolkit, system, skills, or templates | `system` |
| Contribute a shared system improvement | `system`, on a contribution branch |
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

Shared pull requests use system contribution branches. Private PM work remains in its private repository.

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

## Existing workspaces at release

For each shipped change, state which existing records it affects and how a consumer can verify alignment.

| Effect | Release requirement |
| --- | --- |
| New work only | Explain why existing records remain valid. |
| Existing records need review | Define how to find candidates, inspect original evidence, resolve each finding, and verify the affected records. |
| Stored format changes | Supply a tested migration, compatibility requirements, a read-only preview, and a recovery procedure. |

Test direct shared Git pulls and released updaters on populated installations. Include supported skipped releases and same-format updates.

Check whether older supported clients can read newly written records. For incompatible changes, document how the previous updater reaches the migration.

For a cleanup, test an affected record, a legitimate exception, an interrupted run, and a second run after completion.

Ship each required cleanup's identifier, detection rule, and instructions inside the shared checkout. Track progress privately, separately from the installed system version.

Provide a read-only check after a system pull and at session start. Support direct Git updates, restored workspaces, and clients with hooks disabled.

Preview affected paths and reasons. Preserve local edits and untracked records in a recoverable snapshot before applying approved changes.

Explain the update's benefits and offer the user a choice before transforming existing artifacts.

Verify links, stable IDs, citations, and the intended outcome. Keep missing evidence or deferred work visible at the affected record.

Follow [the installed-workspace upgrade procedure](updates.md) for all existing private records, regardless of filename.

## Codex review before publication

Merging to the default branch makes changes available to consumers who pull it. Apply this process to every oryx release. Compare the candidate with the last published version and the PM requirements.

| Stage | Evidence required to advance |
| --- | --- |
| Implement | Contribution branch, dependency review, passing system check and full test suite. |
| Pull request | Open ready for review. Describe consumer impact, recovery and verification limits. |
| Code review | Codex reviews the current PR head. Address findings, test fixes and obtain a fresh review. |
| Security review | Codex Security reviews the same head. Require an explicit passing security result. |
| Merge | The agent may merge the exact reviewed SHA when both reviews and required CI pass. Respect repository protections. |
| Publication | An authorised merge starts publication. Verify the tested tree and publish the version in the merged commit. |

Require `check` and `review` before merging. Maintainers follow their checkout’s publication procedure.
