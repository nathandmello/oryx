# Resume a task in either client

“Resume the billing launch review” looks up current private work by name. “Where did we leave off?” finds open tasks.
Oryx asks which task you mean when several match. The PM chooses whether to continue, defer, or finish.

## Keep the main task open

Keep the PM’s current task moving. A pause between steps of a longer task is a good time for one brief offer. Use the offer reserved for that pause.
Ask one short question. For example, “Jo asked for examples in this review. Would you like to review that detail for her profile?”

If the PM wants to discuss it now, check the source together. Return to the original question afterwards.
For a longer discussion, offer a separate terminal session. The PM chooses the client and when to open it.

Use `pm.py offer list` on request to find pending, deferred, or possibly delivered suggestions.
Use `offer show TOKEN` to check the reference and its current permissions. For a remote source, add `--reread` and supply the freshly authorized source as JSON.
The PM can respond immediately to an offer found by request.
Use `offer decline TOKEN` to dismiss it or `offer defer TOKEN` to keep it available for lookup.

Each client reserves delivery before showing a prompt. If delivery is interrupted, an explicit lookup can recover it.
Use `offer presented TOKEN` after delivery.

Quiet mode, expedite mode, and busy work suppress optional prompts. A source can authorize holding an exact reference for later review.
The queue retains accepted references and delivery receipts. The source owner keeps the original passage.

For “stop profile suggestions,” apply `pm.py override profile-suggestions off` immediately.
Use `override context-advice off` for client tips and `override optional-suggestions off` for all optional prompts.
Add `--source transcript` for a source-specific rule. Follow the [workspace feedback settings](overrides.md) if the PM welcomes feedback.

## Save a private task

Ask which task, open issue, and next step the PM wants to save. Show the exact wording and any parent link.
`pm.py handoff resume NAME` finds an open work record or previously approved handoff. It returns its scope and current revision.
For a side discussion, include the parent's ID or record and revision in the child. Keep its scope.

Send this example to `pm.py handoff preview` on standard input. Add the reviewed parent reference if applicable.

```json
{
  "name": "Jo’s launch review",
  "scope": "product/billing",
  "objective": "Prepare the launch review with Jo.",
  "open_question": "Which support evidence would help with the launch decision?",
  "next_step": "Review Jo’s question with the PM."
}
```

Show the preview to the PM. Pass the entire preview as `review` and their confirmation as `approved: true` to `pm.py handoff save`.
In an installed Workspace, approve the [staged change](external-review.md) in the PM terminal.

Fresh Workspaces keep handoffs in `.oryx/state/handoffs/index.json`. Older Workspaces use `workspace/handoffs/index.json`. Revisions protect concurrent edits.

For an update, include the current `id` and `base_revision` in the preview. The PM approves the new text.

Start the real client from another terminal with `python3 tools/pm.py agent codex` or `python3 tools/pm.py agent claude`.
Ask it to resume the named task. Review the original question, current evidence, and next step together.
When the PM confirms the return, use `handoff return ID` with `revision`, `scope`, and `approved: true` on standard input.
A changed parent requires a fresh review and updated link. `handoff finish ID` closes work without a parent.

## Review source permissions

Keep transcript text, private guesses, and draft claims out of checkpoint fields. Save only wording approved for this task.
For a context citation, obtain separate permission to retain its record, SHA-256 revision, source ID, and work scope.
Supply those fields as `record`, `revision`, `source_id`, and `scope` with `approved: true` to `pm.py handoff grant`.

Include the returned grant in the task’s `evidence` list. Use `handoff revoke GRANT` to withdraw it.
Changed citations and revoked grants prevent a dependent handoff from surfacing.

For a permitted conversation reference, use `pm.py journal reference --client CLIENT --session SESSION --scope SCOPE`.
Use the task’s `journal_scope` from its resume result. Include the event ID in `journal` and that scope in `journal_reference_scope`.

Resuming reads later exchanges only within that session and the exact task, parent, or owner. A shared product scope permits metadata lookup.

Missing conversation history leaves a gap beside independently approved task wording.
Set `journal_required` to true when the task wording itself depends on permission to use the exchange.
