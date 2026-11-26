# Tagged releases

Each authorised merge into `main` publishes the version from that commit. Consumers can pull the shared system immediately after merge.

## Enable publication

Inspect GitHub Releases, remote tags, Actions permissions and rulesets before the first merge. Start with the next available version.

Require pull requests and the GitHub Actions checks `check` and `review`. Require current branches and dismiss stale approvals.
Publication stops while GitHub reports an unprotected default branch. Grant the merging agent access through the authorised maintainer account. Apply the rules to administrators. Disable direct pushes, force pushes and branch deletion.

Run the checks on the setup PR before selecting their names in branch protection. Protect `v*` tags against updates and deletion.
Permit the publisher to create new tags and Releases. Use a disposable GitHub repository to rehearse before enabling publication.

Record thirty days of Actions usage by operating system, merged PR count, full suite runs, and actual charges.
Repeat after thirty days. Compare macOS minutes per merge, full runs per tested revision, and billed spend.

At the November 19, 2026 baseline, the preceding thirty days included 32 runs and 10 merged PRs.
Completed job timestamps cover 83.7 macOS minutes, 3.6 Ubuntu minutes and 0.9 Windows minutes.
One macOS job and four self-hosted jobs lacked complete timestamps. The suite ran 28 times across 23 distinct run head SHAs.
Standard hosted jobs are free for this public repository. Account billing totals require billing access.

## Prepare the pull request

Increase `system_version` in `playbook/release.json`. Use patch for fixes, documentation and CI, minor for features, and major for breaking changes.
Update upgrade guidance when installation steps change. Describe the effect on existing workspaces in the PR. Keep private format metadata compatible with released updaters.

Linux tests the proposed merge tree. Native-sensitive changes also exercise macOS relocation, upgrade and restore.
Update the path selector when introducing a new platform dependency. Drafts defer tests until ready. Description edits refresh review evidence.

For stakeholder or continuity changes, attach the [signed study receipt](stakeholder-qualification.md).

Open the PR ready for review. Codex runs code and security reviews on the PR head.
After a fix, request fresh reviews for that head if the integration has not started them automatically.
The agent monitors the Codex summary and checks. It reruns the lightweight review job when both results arrive.

Resolve code findings. Require an explicit clean security result or a successful Codex security check for the same commit.

When security findings are private, Codex can confirm both reviews with its documented thumbs-up after the current summary.
Older reactions expire. An unknown outcome holds the merge.
The agent merges with the verified head SHA after both reviews and required CI pass. Refresh stale branches before merging.

## Verify and recover

The publisher checks the merged PR, both workflow runs, and the tested tree. It creates an annotated tag at the merged commit.
The Release includes the change, PR, consumer impact, recovery and verification limits. Latest identifies the highest published stable version.

Inspect the publication run summary for the tag, merge SHA and release link. Compare the tag target with the PR merge.

Merging starts the hosted publisher automatically. Temporary GitHub failures retry twice inside that job.
Agents monitor the run and handle authorised recovery. After fixing a failed gate, retry the existing run for that merge.
For targeted recovery, dispatch **Publish oryx** on `main` with the original PR number.

Older manual verification prompts expire when their candidate leaves the default branch tip. Automatic publication starts with the pipeline release.
Retries verify existing tags and reuse completed releases. Inspect conflicting tags or missing review evidence before retrying.

Rehearse two successive merges and a retry after tag creation. Verify one release per merge and confirm Latest after retrying the older release.
For defective code, submit a corrective PR with a new version. Follow [installed workspace recovery](updates.md#recovery) when private records require restoration.
