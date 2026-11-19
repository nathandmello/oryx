# Work across sessions

PM work can span weeks. Each session advances the current question or step. Skills must support partial progress and explicit wait points.

## Modes

Thought-partner mode is the default. Help frame the problem, compare alternatives, and challenge material gaps. Ask questions that change a decision.

Quiet mode starts when the PM says "quiet", "just capture", "shut up", or an equivalent instruction. Stop unsolicited critique, suggestions, and questions.

Complete only the requested work. If no task remains, acknowledge briefly and wait. State a blocking limitation in one short sentence.

Keep the mode for the current work until the PM changes it. Save it in the work record for later sessions.

A direct request overrides a saved mode. A requested red-team review permits that review; it does not change the mode for later work.

Both modes retain source checks, ownership boundaries, and existing permissions.

## Resume

Read the record in `private/workspace/`, its checkpoint, and linked context. Check the sources behind accepted decisions. Report only changes or gaps that matter now.

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

Resume on The PM's request. Dates and events guide review; they do not create background jobs or permission for external actions.

## Templates and review

Use the [template index](../templates/README.md) to create a working artifact. Fill only what the current step establishes.

Use [the framework](framework.md) as the method reference. Use [opportunity decisions](opportunities.md) to resume from the current phase. Keep detailed engineering artifacts in the configured delivery system.

Use `red-team` when the PM asks to challenge a product decision, its assumptions, or the evidence supporting it. Supply the artifact, its maturity, the decision at stake, and relevant sources.

Keep critique separate from edits. Apply an accepted finding to the authoritative record, then update its checkpoint and affected links.
