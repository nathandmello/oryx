# Review a source for another workflow

Start with the PM's task, the authorized source and how they permit its use.
A meeting summary, article review or chat reply can finish without a profile update.
Use only the agreed passage. Keep the original with its owner.

## Describe the permitted read

Pass JSON on standard input to `python3 tools/pm.py ingestion assess`. A meeting reader might supply this packet.

```json
{
  "source": {
    "kind": "transcript",
    "source_id": "ops-28",
    "event_id": "review-28",
    "reference": "context/meetings/ops-review.txt",
    "scope": "context/meetings/ops-review.txt",
    "revision": "v3",
    "authorized": true,
    "coverage": "read",
    "retention": "review",
    "purposes": ["source-coverage", "stakeholder-profile"]
  },
  "moment": "busy",
  "mode": "thought-partner"
}
```

Use each original's stable ID. Link a recap to the same `event_id` only when the originating exchange is known.
Use `subject` for an agreed product, area or initiative. An unspecified subject remains unknown.

For remote reads, use the original text returned by an authorized tool available to the agent.
For chat, identify the specific message with an opaque `chat:` reference.
Use a Workspace-relative path to a regular Markdown or text file in a visible record directory.
Oryx reads the cited bytes from that file, including evidence in an initiative or a newly added domain.
Configuration, hidden files, private profiles, customizations and linked files cannot supply evidence.

Set `coverage` to `read`, `partial` or `unavailable`. For a partial read, include the exact text and its UTF-8 byte offset.
Supply the source revision for partial remote reads. An incomplete speaker turn needs clarification.
Keep the permitted excerpt within 128 KiB. For longer sources, supply bounded ranges within the approved scope.

Only name purposes the PM permits. Use `chat-only` when secondary review or pointer retention is outside that permission.
A summary-only restriction, an off-record conversation or an explicit exclusion takes precedence over optional suggestions.
Shared capture uses the same envelope through a source's `ingestion` options. Prepared claims alone cannot establish the original speaker.

To withdraw a local document, run `oryx ingestion revoke-document SOURCE_ID PATH`.
Personal search withholds that document and records citing it until you restore its use.
Oryx rechecks a local source when the PM accepts its reviewed onboarding finding.

## Choose an external tool

The agent discovers which tools are available in its session. Choose one that can complete the action with the PM’s permissions.
For reads, carry the source identity, revision, scope, coverage and permitted use into Oryx.

For an outward action, verify the destination and audience before PM review. Recheck both before disclosure.
Keep an external result pending when the available tool cannot confirm it. Report the missing capability.

## Inspect and review

The dispatcher parses the permitted passage once. Source coverage and stakeholder reviewers can consume it independently.
For a named speaker, it keeps the complete attributed statement, location, conditions and original wording.
Check attributed statements in articles and minutes. For email, verify the sender header. A PM's account stays attributed to the PM.

A transcript contains this exchange.

```text
[03:20] Jo Diaz: I do not want slides unless the customer asks.
```

The checked paraphrase is “At 03:20, Jo Diaz does not want slides unless the customer asks.”

For `status: review`, inspect the original privately. The response can include located passages.
When working from a proposed annotation, supply the exact person and excerpt in `observations.stakeholder-profile`.

Include the original locator when identical text occurs twice. Unsupported annotations yield no offer. Other supported observations remain eligible.
If the original is ambiguous, ask who said it and what qualified it. A fresh PM account has its own source.

Finish the PM's task. At a natural pause, the common selector can reserve one eligible offer.
Use `pm.py offer presented TOKEN` after delivery. A busy moment can retain an eligible source pointer for later.

Use `pm.py offer list` and `pm.py offer show TOKEN` for explicit discovery.
Pending references contain no quotes. Remote evidence requires a fresh authorized read of that exact passage.

## File one approved claim

Pass the offer's evidence, source, excerpt, topic, kind, scope, subject, observed date and attribution to `stakeholder-profile preview`.
Use the resolved person, stable profile ID and PM-confirmed role. Include the proposed `wording`.
A source-backed factual paraphrase must preserve the meaning, speaker and qualifications.
For a broader interpretation, choose `kind: hypothesis`, `attribution: PM`, and review the PM's exact words beside the original statement.

Show the PM the wording, evidence, private destination and any uncertainty. Preview edits again.
Pass the review and approved wording to `stakeholder-profile accept`. Both operations recheck the authorized original.

For remote sources, supply a current `source_read` from the authorized conversation or remote reader at each step.
A stored grant identifies the permitted range. It cannot prove continued external access.

Use `ingestion revoke SOURCE_ID` when permission ends. This removes pending review authority for that original.
An accepted profile claim keeps its exact historical bytes. Direct profile display and audience preparation
withhold the claim when its filing grant has ended or the authorized local revision changed.
After renewed permission, use `ingestion restore SOURCE_ID` and assess a fresh read.
Changed sources, unavailable originals and expired grants need a new review before filing.

Scoped task context can include `work_evidence` from indexed private artifacts. Resolve exact record IDs,
current paths and known aliases. Cite the returned revision, section and work state. Read the owning workflow
for an exact JSON record pointer. A changed revision requires a fresh record review. A pending or completed
ownership transfer requires current permission from its authoritative owner.
