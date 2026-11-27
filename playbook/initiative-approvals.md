# Approve initiative transactions

Prepare proposals in a [protected agent session](overrides.md#start-a-pm-session). The PM approves them in their own terminal or, for roadmap changes, the [local browser app](local-ui.md).

## Register the product

Create the linked company and product context records. Set limits for open initiatives and concurrent discovery. Zero discovery slots means none are available.

```json
[
  {
    "type": "setup",
    "company": "context/company/overview.md",
    "product_context": "context/products/example/overview.md",
    "max_open": 20,
    "max_discovery": 2
  }
]
```

Replace the example limits with the PM’s values.

## Propose and approve

Run `python3 tools/pm.py initiative schema` for accepted fields and transitions. Use the IDs from `initiative show`. Submit linked transactions in one JSON array.

```sh
python3 tools/pm.py initiative propose example < changes.json > proposal.json
```

Open the proposal in your terminal.

```sh
python3 tools/pm.py initiative apply example < proposal.json
```

Read the proposed changes, [decision rationale](decision-forecasts.md), and cited evidence. Type `approve` at the prompt to record that revision.
If evidence is missing, leave the proposal open. Changed transactions, register history, or reviewed documents require a fresh preview.

For a PM-run script, pass `--approve REVISION` with the complete `revision` you reviewed.
Supply that value independently of the proposal file.
Inspect the decision with `initiative show example INITIATIVE_ID`.

Use the registered product context ID and a stable initiative slug.

```json
[
  {
    "type": "capture",
    "initiative": "product-context-0123456789ab/renewals",
    "title": "Renewal delays",
    "areas": ["product/example/area/renewals"],
    "source": "Support ticket 12, initial report",
    "observed_on": "2026-01-08",
    "summary": "An administrator reported missing the renewal date."
  }
]
```

Omit `areas` for product-wide work. Use `set-areas` to replace confirmed area links or `[]` to clear them.

After the first capture, review the [possible matches](initiative-views.md#review-an-incoming-idea). To authorize a separate initiative, add `--confirm-distinct NEW_ID` to `initiative apply`.

## Experiment drafts

`initiative show` lists the editable draft and its missing fields.
A ready plan needs a linked hypothesis, method, decision criterion, planned date, and source.
Describe the method and criterion separately.

```json
[{"type": "approve-experiment", "initiative": "product-context-0123456789ab/renewals", "metric": "renewal-rate"}]
```

Review the experiment under `reviewed_transactions` before approval. Schedule the test for the approval date or later.

Recover missing experiment drafts with `initiative sync-drafts example`.

## Review gates

- Record the problem, audience, and outcome before discovery or proposal work advances.
- Authorize a reviewed discovery plan with `start-discovery`. Give it a review date and record the hypotheses it addresses.
- Assess each decision-critical hypothesis from 0 to 10 in the current timebox. Complete the findings before `prepare-brief`.
- Apply [the brief-review checks](brief-review.md) before proposing a candidate.
- Use `approve-initiative` with a complete Initiative Brief and a linked success target. This creates a roadmap candidate.
- List each approved candidate in the comparison table once. Submit the same IDs in `cycle.options`. Describe existing commitments in prose.
- Use `plan` with a reviewed cycle, unique rank, horizon, effort, and trade-off. Stay within approved cycle capacity.
- Compare a candidate again after the PM approves a revised Initiative Brief.
- Use `start-delivery` with the delivery URL. Propose `ship` with [reviewed readiness](initiative-work.md#ship-decision) and a review date. Ask the PM to approve [the outcome review](outcome-evidence.md).
- Use `defer` with a review date or event. Decline obsolete deferred work directly. Reopen work for material changes.
- Use `expedite` only for verified urgent work. Provide the owner, obligation, deadline, scope, delivery link, and review date.

Approval records the exact reviewed briefs and planning comparison. Keep later notes separately. A discovery timebox covers its plan and Sources. Update Findings as evidence arrives. Renew older timeboxes with `start-discovery` before concluding.

## Existing private work

Oryx rechecks the Initiative Brief at selection and delivery start. Reopen weak briefs for review.

Update all clients before the first new approval. Sync and back up the register with its receipt at `.oryx-approvals/<product>.json` under the selected Workspace root.
After an interrupted save, retry the approved proposal. If it is unavailable, run `python3 tools/pm.py initiative recover PRODUCT` in your terminal.
Recovery applies the recorded approval only when the register matches its expected revision. [Updates and recovery](updates.md)

An older register may carry a PM SSH signature. Keep its existing trusted public allowed-signers file outside the checkout.
Set `PM_HUB_ALLOWED_SIGNERS` to its absolute path. Oryx uses OpenSSH to verify the register.

The first approved change retains the old signature, revision, and event count. Subsequent reviews use the recorded history.
Keep the public file and backup for independent verification. New approvals need no signing key.

Published format-1 installations follow the normal upgrade. An unreleased prototype stored signed registers under the earlier layout.
Alignment pauses on that prototype. Use its original checkout at `02a62b6`. If those files already moved, consult the verified installation backup.

## Two local POSIX accounts

For a separate agent account in a source checkout, set `PM_HUB_SHARED_GROUP` to the dedicated group in both accounts. New files otherwise allow only owner access.
Use a local filesystem that supports exclusive locks on read-only descriptors.

| Existing location | PM provisions | Access for the group |
| --- | --- | --- |
| `studio/workspace/backlogs/<product>/` | PM owner, shared group, mode `2750` | Read and traverse |
| `studio/workspace/experiments/<product>/<initiative>/` | Shared group, mode `2770` | Create and edit drafts |
| `studio/.oryx-approvals/` | PM owner, shared group, mode `2750` | Read and traverse |
| Initiative register and receipt | Shared group, mode `0640` | Read |
| Named experiment drafts | Shared group, mode `0660` | Read and write |
| `.git/pm-hub-writer.lock` and `studio/.git/pm-hub-writer.lock` | PM owner, shared group, mode `0640` | Read and lock |

Provision both locks and existing files before sharing. Keep both locks in place.
Provision the experiment draft directory before its first target. Setgid directories preserve the group during atomic publication.

Give the group read access to context, settings, upgrade records, and Git metadata.
Protect Git metadata and the ancestors of registers and receipts against agent writes. Check inherited ACLs. Trust only verified repository paths in Git.

Test `initiative show` and `initiative draft-experiment` as the agent. Check draft write access and read-only access to registers and receipts.

If the shared-write test skips, rerun with `TMPDIR` on a filesystem that preserves setgid.
