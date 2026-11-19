# Review evidence that changes a decision

When the PM supplies evidence, check it against applicable commitments. Report a material risk in quiet mode with a short factual warning.

Use the existing evidence capture, meeting summary, initiative intake, backlog, and roadmap actions. Plain-language tasks use the same records.

## Compare the claims

Read the actual statements, decision owners, scopes, dates, exceptions, and citations. A narrower decision needs the policy owner's authority for an exception.

The Hub compares overlapping decision scopes and flags potential conflicts. It also recognizes some restrictions in prose. People assess meaning, credibility, and impact.

For a customer update, qualify a promised launch that still requires Legal sign-off. A PM can retain a plan while clearance remains outstanding.

## Save a risk with evidence

Preview `pm.py route-context`. Review `risk_preview`. An authorized `--write PATH` stores the source claim and review events together in that record.

Use an entry's optional `risk` to record material concerns, including concerns expressed indirectly:

```json
{
  "reason": "The clearance requirement could exclude the current pilot cohort.",
  "authority": "Legal liaison reporting a provisional ruling",
  "targets": ["product-context-0123456789ab/export-pilot"]
}
```

Omit unconfirmed targets. Use one record for a source affecting several initiatives. Keep a source locator and its actual coverage.

For an inaccessible original, use a question and `risk.source` with the supplied source index. Report the evidence gap and its consequence.

A partial source can open an unassessed review. A meeting summary alone authorizes a reply. File the evidence when the PM requests capture.

Signed initiative signals and context captures retain their own authority. Keep pending evidence in authorized context when a stale brief prevents a register change.

## Respond or retrieve

`task-context --product PRODUCT --history` shows the history in scope. `task-context "Show RISK_ID"` retrieves a saved context review.

A hook or CLI lookup can detect a conflict in older records. It preserves their bytes. An authorized response records the original finding and disposition.

Submit a context response through the existing capture command:

```json
{
  "sources": [],
  "entries": [],
  "responses": [{
    "record": "context/products/example/overview.md",
    "id": "risk-0123456789abcdef0123",
    "state": "follow-up",
    "reason": "The PM requested confirmation before promising the customer a date.",
    "source": "PM launch review, item 3",
    "review_on": "2027-01-12"
  }]
}
```

Use the reported owner path and ID. Use `follow-up` for a dated check. Use `retain` to acknowledge an outstanding risk.

Use `dismiss` or `resolve` with the PM's reason and source. A changed claim or source coverage can raise another review.

A PM disposition cannot grant a policy exception. Record the decision owner's evidence through the existing context workflow.

A signed ship decision preserves the active advisories and source claims the PM reviewed.
Use [launch review](initiative-work.md#ship-decision) when those advisories change before signing.

## Existing workspaces

Older context remains readable. Existing decision pairs can surface on lookup. A material legacy note can be reviewed through authorized evidence capture.

Update each client before recording new review history or signing a review transaction. Preserve workspace history and use [the installed-workspace procedure](updates.md).
