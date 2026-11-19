# Approve initiative transactions

Use a trusted Hub and OpenSSH with `ssh-keygen -Y sign` and `ssh-keygen -Y verify`.

Keep the PM signing key and trusted allowed-signers file outside both repositories. List `pm-hub-pm` and its public key on one line. Set `PM_HUB_ALLOWED_SIGNERS` to the file's absolute path.

Keep signing access with the PM. Protect verified Hub code and signer configuration against agent writes. Give agents writable drafts and read-only access to registers and their parent directories.

Signatures detect changes to signed data. Filesystem permissions protect registers from deletion and rollback.

### Two local POSIX accounts

Set `PM_HUB_SHARED_GROUP` to the dedicated group in both accounts. Fresh files default to owner-only access.
Use a local filesystem that supports exclusive locks on read-only descriptors.

| Existing location | PM provisions | Access for the group |
| --- | --- | --- |
| `private/workspace/backlogs/<product>/` | PM owner, shared group, mode `2750` | Read and traverse |
| `private/workspace/experiments/<product>/<initiative>/` | Shared group, mode `2770` | Create and edit drafts |
| Signed register | Shared group, mode `0640` | Read |
| Named experiment drafts | Shared group, mode `0660` | Read and write |
| `.git/pm-hub-writer.lock` and `private/.git/pm-hub-writer.lock` | PM owner, shared group, mode `0640` | Read and lock |

Before enabling sharing, provision both locks and existing files as shown. Keep both locks in place.
Provision the experiment draft directory before its first target. Setgid directories preserve the group during atomic publication.

Give the group read access to context, settings, upgrade records, Git metadata, and public signers.
Protect Git metadata and register ancestors against agent writes. Check inherited ACLs. Trust only verified repository paths in Git.

Test `initiative show` and `initiative draft-experiment` as the agent after a signed revision.
Verify write access to drafts and read-only access to registers and their parents. Tests check file modes and locking under one account.

If the shared-write test skips, rerun with `TMPDIR` on a filesystem that preserves setgid.

## Register the product

Create the company and product context records first. Check their parent link. Choose a maximum for open initiatives and concurrent discovery work. Use zero for discovery when no capacity is available.

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

Replace these fictional limits with PM-confirmed values.

## Propose and approve

Run `python3 tools/pm.py initiative schema` for accepted fields and transitions. Use the exact identifier returned by `initiative show`. Submit one or more linked transactions in one JSON array.

```sh
python3 tools/pm.py initiative propose example < changes.json > proposal.json
```

Review each transaction and document. Verify evidence at its source. Stop when a gate requires missing facts.

From the trusted PM account, apply the reviewed proposal. Use the PM signing key's absolute path.

```sh
python3 tools/pm.py initiative apply example --key "$PM_SIGNING_KEY" < proposal.json
```

Changes to a proposal, register, or reviewed document require a fresh preview.

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
New proposals need visible answers. Give the method and criterion distinct content.

```json
[{"type": "approve-experiment", "initiative": "product-context-0123456789ab/renewals", "metric": "renewal-rate"}]
```

Review the experiment under `reviewed_transactions` before signing. Schedule the test for the signing date or later.
Run the approved test and submit its results in a later proposal.

After an interrupted file update, run `python3 tools/pm.py initiative sync-drafts example`. This also creates drafts for eligible existing targets.

## Review gates

- Record the problem, audience, and outcome before discovery or proposal work advances.
- Authorize a reviewed discovery plan with `start-discovery`. Give it a review date and record the hypotheses it addresses.
- Assess each decision-critical hypothesis from 0 to 10 in the current timebox. Complete the findings before `prepare-brief`.
- Apply [the brief-review checks](brief-review.md) before proposing a candidate.
- Use `approve-initiative` with a complete Initiative Brief and a linked success target. This creates a roadmap candidate.
- List each approved candidate in the comparison table once. Submit the same IDs in `cycle.options`. Describe existing commitments in prose.
- Use `plan` with a reviewed cycle, unique rank, horizon, effort, and trade-off. Stay within signed cycle capacity.
- Compare a candidate again after the PM approves a revised Initiative Brief.
- Use `start-delivery` with the delivery URL. Use `ship` after verification with a review date. Use `review-outcomes` after [reviewing outcomes](conversation.md).
- Use `defer` with a review date or event. Decline obsolete deferred work directly. Reopen work for material changes.
- Use `expedite` only for verified urgent work. Provide the owner, obligation, deadline, scope, delivery link, and review date.

An approved Initiative Brief, completed discovery brief, and planning comparison are bound to their reviewed bytes. Keep notes outside those files after approval. A new discovery timebox binds its plan and Sources. Findings can evolve. Renew older timeboxes with `start-discovery` before concluding.

## Existing private work

New reviews need distinct, visible answers. A short answer or named source can suffice.
Prior signed hypotheses and experiments remain readable.

Describe the discovery method in the brief. The signed `review_on` sets its next checkpoint.
At selection and delivery start, the Hub checks the approved Initiative Brief again. Reopen weak briefs for revision and approval.

For existing work, cite the original analysis. Registered initiatives use the generated roadmap.

Use [installed Hub updates](updates.md) for private format alignment.

Published format-1 installations follow the normal upgrade. An unreleased prototype stored signed registers under the earlier layout.
If alignment detects that prototype, it pauses before moving the data or changing signed references. Use its original format-1 checkout at `02a62b6`. If a previous upgrade already moved those files, consult the verified installation backup.
