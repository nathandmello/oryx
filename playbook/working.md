# Work across sessions

PM work can span weeks. Each session advances the current question or step. Skills must support partial progress and explicit wait points.

## Modes

Thought-partner mode is the default. Help frame the problem, compare alternatives, and challenge material gaps. Ask questions that change a decision.

Quiet mode starts when the PM says "quiet", "just capture", "shut up", or an equivalent instruction. Stop unsolicited critique, suggestions, and questions.

Complete only the requested work. If no task remains, acknowledge briefly and wait. State a blocking limitation in one short sentence.

Keep the mode for the current work until the PM changes it. Save it in the work record for later sessions.

A direct request overrides a saved mode. A requested red-team review permits that review; it does not change the mode for later work.

Both modes retain source checks, ownership boundaries, and existing permissions.

## Run a workflow

1. Open the outer Hub. Read the [constitution](../AGENTS.md), `private/settings.json`, and the private handoff.
2. Use the PM's current request, the handoff, and the record to identify the next action and active mode.
3. Reuse the authoritative record. Apply [the filing rules](filing.md) and the matching [template](../templates/README.md) before creating a record.
4. Create new records with `python3 tools/pm.py new <kind> <path>` from the system root. Pass a path relative to `private/`.
5. Fill what the session establishes. Keep gaps and unapproved choices visible. Follow the requested scope for any edits.

When work relies on context, check parent commitments, data boundaries, and closed decisions. Follow [the context review rules](context.md#review-existing-context) for flagged briefs.

Use [context ingestion](../.agents/skills/ingest-context/SKILL.md) for requested context changes. Keep evidence with its owner and link it from the work record.

When a record action depends on an unavailable private workspace, report the missing workspace. Honour requests for discussion or a draft preview.

## Resume

Read the record in `private/workspace/`, its checkpoint, and linked context. Use headings and section leads to find context that applies to the work.
Read the relevant entries and applicable parent rules before acting. Check the sources behind accepted decisions. Report only changes or gaps that matter now.

Resolve context for each workspace task, including drafts and replies. Repeat the lookup when scope or evidence changes.
Run `pm.py task-context "TASK"` if hooks are unavailable. Use `--product`, `--area`, or `--initiative` when scope is known.
Use [the numerical evidence procedure](numbers.md) before relying on material figures from any source.

At startup, ask once about any `remit_prompt` from `pm.py align` when questions are welcome. Respect quiet mode and deferrals. Capture agreed responsibilities in the [PM profile](context.md#pm-remit).

For area work, use `pm.py area-context PRODUCT AREA` to locate the product overview, area brief, and inline evidence.

Take the recorded next action or follow the PM's current request. Recheck a source when it changed or its age affects the decision.

Keep observations, assumptions, and unknowns distinct. Preserve earlier evidence and its date when a conclusion changes.

## Checkpoint

Update the current record after useful progress and before a wait or handoff:

- Last checkpoint: date, result, and relevant evidence or decision references.
- Next action: one concrete step; identify its owner when another person must act.
- Waiting on: the evidence, event, or person needed; use `none` when clear.
- Resume when: a specific event or review date; use `none` when clear.
- Mode: `thought-partner` or `quiet`.

Record the current state:

| State | Meaning |
| --- | --- |
| draft | Incomplete work; placeholders are allowed. |
| active | Work can advance; the next action is concrete. |
| waiting | A dependency prevents the next step; the wait and resume trigger are explicit. |
| complete | This artifact is complete for its stated purpose. This state does not establish product success. |

Keep a wait visible. Do not invent evidence, advance to the next activity, or complete a discovery process to finish a session.

Update `private/README.md` when handing off active work. Point to the current record and name its next action.

Resume on The PM's request. Dates and events guide review; they do not create background jobs or permission for external actions.

## Templates and review

Use the [template index](../templates/README.md) to create a working artifact. Fill only what the current step establishes.

Use [the framework](framework.md) as the method reference. Use [opportunity decisions](opportunities.md) to resume from the current phase. Keep detailed engineering artifacts in the configured delivery system.

Use `red-team` when the PM asks for an independent review of a PM artifact, a product decision, or its evidence.

> Red-team this experiment before launch. Challenge whether it can answer the rollout decision.

Supply the artifact, its maturity, the decision at stake, and relevant sources. Choose a method, ask for a fresh reviewer, or ask for options before the review.

Keep critique separate from edits. Apply an accepted finding to the authoritative record, then update its checkpoint and affected links.
