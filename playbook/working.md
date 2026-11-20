# Work across sessions

Support partial progress and explicit wait points across sessions.

## Modes

Thought-partner mode is the default. Help frame the problem, compare alternatives, and challenge material gaps. Ask questions that change a decision.

Quiet mode starts when the PM says "quiet", "just capture", "shut up", or an equivalent instruction. Stop unsolicited critique, suggestions, and questions.

Complete only the requested work. If no task remains, acknowledge briefly and wait. State a blocking limitation in one short sentence.

Keep the mode for the current work until the PM changes it. Save it in the work record for later sessions.

A direct request overrides a saved mode. A requested red-team review permits that review; it does not change the mode for later work.

Both modes retain source checks, ownership boundaries, and existing permissions. Report known [evidence risks](evidence-reviews.md) that affect the requested work, including in quiet mode.

## Reply preferences

Use [oryx commands](commands.md) to find the preference actions.

| In Claude Code | Result |
| --- | --- |
| `/pm workspace preferences show` | Show effective reply preferences. |
| `/pm workspace preferences preview --detail concise --layout bullets` | Try changes on a sample reply. |
| `/pm workspace preferences set --detail concise --layout bullets` | Save the supplied preferences. |
| `/pm workspace preferences set --layout prose` | Change the layout. |
| `/pm workspace preferences reset layout` | Restore the default reply layout. |
| `/pm workspace preferences reset all` | Restore all reply preferences. |

From the checkout root, replace `/pm` with `python3 tools/pm.py action`.
The shorter terminal form is `python3 tools/pm.py preferences` followed by the action and options.

Select concise or detailed replies. Select bullets or prose where the content fits.
Review a sample with `preview`, then save when ready. You can also ask for changes in plain language.
Each save affects only the supplied fields. A failed save keeps the previous settings.

The PM's profile stores the choices. With trusted hooks, each new turn uses the latest valid settings in the open checkout.

Follow oryx rules and preserve required artifact content. For a single task, the PM can override a saved presentation choice.
An invalid saved block uses defaults and produces a check error. Use `preferences reset all` to restore a valid block with complete markers.

## Resume

Read the owning record, its checkpoint, and applicable parent rules. Check sources behind accepted decisions. Report material changes and gaps.

Use [local semantic search](context-search.md) for each task and material scope or evidence change.
Run `pm.py task-context "TASK"` if hooks are unavailable. Use `--product`, `--area`, or `--initiative` when scope is known.
Add `--work-record workspace/problems/export.md` to read the checkpoint and effective mode. Use the resolved reply preferences.
Use [the numerical evidence procedure](numbers.md) before relying on material figures from any source.

Start an empty Studio with [company setup](company-context.md). Use `pm.py company-onboarding status` to resume progress.
Follow the current request and respect quiet mode. Raise an agreed follow-up when its cue occurs.
Ask about remit when ownership matters. Capture confirmed responsibilities in the [PM profile](context.md#pm-remit).

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

### Save a reviewed checkpoint

Use `pm.py conversation checkpoint show RECORD` to read the owning Work state.
Use `preview RECORD` with JSON updates on stdin. Review the result. Use `apply RECORD` with that receipt to save.

Set the permitted fields the PM confirmed. A pause might use:

```json
{
  "state": "waiting",
  "last_checkpoint": "2026-11-19: Confirmed the export issue in two support cases.",
  "next_action": "Compare access failure and format failure.",
  "waiting_on": "Support case transcripts",
  "resume_when": "Support provides the case references."
}
```

An explicit deferral can save `deferral` with the offered workflow, scope, source, evidence revision, and `review_on`.
Use an ISO date or null to revisit on changed evidence. Copy the chosen entry into `clear_deferral` when the PM asks.

Keep the open question, agreed facts, and sources beside the work. Use an editable owner when a signature binds the current file.
A stale preview needs a new review. A permission error leaves the checkpoint unsaved.

## Templates and review

Use the [template index](../templates/README.md) to create a working artifact. Fill only what the current step establishes.

Use [the framework](framework.md) as the method reference. Use [opportunity decisions](opportunities.md) to resume from the current phase. Keep detailed engineering artifacts in the configured delivery system.

Use `red-team` when the PM asks for an independent review of a PM artifact, a product decision, or its evidence.

> Red-team this experiment before launch. Challenge whether it can answer the rollout decision.

Supply the artifact, its maturity, the decision at stake, and relevant sources. Choose a method, ask for a fresh reviewer, or ask for options before the review.

Keep critique separate from edits. Apply an accepted finding to the authoritative record, then update its checkpoint and affected links.
