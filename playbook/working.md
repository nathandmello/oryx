# Work across sessions

PM work can span weeks. Each session advances the current question or step. Skills must support partial progress and explicit wait points.

## Modes

Thought-partner mode is the default. Help frame the problem, compare alternatives, and challenge material gaps. Ask questions that change a decision.

Quiet mode starts when the PM says "quiet", "just capture", "shut up", or an equivalent instruction. Stop unsolicited critique, suggestions, and questions.

Complete only the requested work. If no task remains, acknowledge briefly and wait. State a blocking limitation in one short sentence.

Keep the mode for the current work until the PM changes it. Save it in the work record for later sessions.

A direct request overrides a saved mode. A requested red-team review permits that review; it does not change the mode for later work.

Both modes retain source checks, ownership boundaries, and existing permissions. Show known risks that affect the requested work.

## Reply preferences

Use [Hub commands](commands.md) to find the preference actions.

| In Claude Code | Result |
| --- | --- |
| `/pm workspace preferences show` | Show effective reply preferences. |
| `/pm workspace preferences preview --detail concise --layout bullets` | Try changes on a sample reply. |
| `/pm workspace preferences set --detail concise --layout bullets` | Save the supplied preferences. |
| `/pm workspace preferences set --layout prose` | Change the layout. |
| `/pm workspace preferences reset layout` | Restore the Hub default layout. |
| `/pm workspace preferences reset all` | Restore all Hub defaults. |

In a terminal at the outer Hub, replace `/pm` with `python3 tools/pm.py action`.
The shorter terminal form is `python3 tools/pm.py preferences` followed by the action and options.

Select concise or detailed replies. Select bullets or prose where the content fits.
Review a sample with `preview`, then save when ready. You can also ask for changes in plain language.
Each save affects only the supplied fields. A failed save keeps the previous settings.

The PM's profile stores the choices. With trusted hooks, each new turn uses the latest valid settings in the open checkout.
If the hooks are disabled, invoke the `pm` skill and use `preferences show` to load the current choices.

Hub rules and required artifact content govern all work. For a single task, the PM can override a saved presentation choice.
An invalid saved block uses defaults and produces a check error. Use `preferences reset all` to restore a valid block with complete markers.

## Resume

Read the record in `private/workspace/`, its checkpoint, and linked context. Use headings and section leads to find context that applies to the work.
Read the relevant entries and applicable parent rules before acting. Check the sources behind accepted decisions. Report only changes or gaps that matter now.

Resolve context for each workspace task, including drafts and replies. Repeat the lookup when scope or evidence changes.
Run `pm.py task-context "TASK"` if hooks are unavailable. Use `--product`, `--area`, or `--initiative` when scope is known.
Use [the numerical evidence procedure](numbers.md) before relying on material figures from any source.

At startup, ask once about any `remit_prompt` from `pm.py align` when questions are welcome. Respect quiet mode and deferrals. Capture agreed responsibilities in the [PM profile](context.md#pm-remit).

For area work, use `pm.py area-context PRODUCT AREA` to locate the product overview, area brief, and inline evidence.

Take the recorded next action or follow the PM's current request. Recheck a source when it changed or its age affects the decision.

Keep observations, assumptions, and unknowns distinct.
Record material changes and risks beside the affected work. Keep the original evidence, source, date, and scope.
Record who decided, their reason, and any outstanding risk or follow-up. Link later corrections to the original decision.

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

Use `red-team` when the PM asks for an independent review of a PM artifact, a product decision, or its evidence.

> Red-team this experiment before launch. Challenge whether it can answer the rollout decision.

Supply the artifact, its maturity, the decision at stake, and relevant sources. Choose a method, ask for a fresh reviewer, or ask for options before the review.

Keep critique separate from edits. Apply an accepted finding to the authoritative record, then update its checkpoint and affected links.
