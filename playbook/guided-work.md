# Resume guided work across clients

Open a guided action with `oryx action`. The response identifies the current step, its trusted method, its stopping condition and the allowed transitions. The method names its owning guide and loads the selected section.

For a durable checkpoint, select your personal Workspace and review a scoped handoff. Keep its ID, revision and work scope. Start the workflow from the PM terminal. For example, use an approved handoff for the product’s roadmap.

```sh
oryx workflow start 'portfolio roadmap plan' --handoff "$HANDOFF" \
  --scope product/billing --revision "$HANDOFF_REVISION"
```

The response includes the workflow ID, its revision, the open question and the allowed next steps. Open the same Workspace in another client. Find the active workflow by its handoff name, or open its exact ID.

```sh
oryx handoff resume 'Review billing priorities' --scope product/billing
oryx workflow show "$WORKFLOW" --scope product/billing
```

At a stopping condition, inspect the evidence and choose an allowed next step. Record your choice from the PM terminal using the revision you reviewed.

```sh
oryx workflow advance "$WORKFLOW" --scope product/billing --to decide \
  --expect "$WORKFLOW_REVISION" --handoff-revision "$HANDOFF_REVISION"
```

The workflow rechecks the method, handoff, scope and attached evidence grants. Roadmap and initiative steps read the registered product. Launch review also checks its tasks and checklist. Onboarding reads the reviewed walkthrough.

If an owning operation changed, open the workflow again. After reviewing that result, pass its current digest with `--readback`. A changed method requires a fresh checkpoint. A revoked grant can prevent resume. Reconcile changed work with its owner before continuing.

Workflow progress records the selected step. Product decisions, document approvals and publication each use their owning operation. For a meeting summary, choosing `finish` after summarizing keeps the summary in chat. Choose `file` only to begin a separate capture review.

For a pending company, PM or product finding, read the owning onboarding status. Use its revision to open the exact destination and proposed wording in your local terminal.

```sh
oryx company-onboarding accept --revision 3
```

Type `save` to accept the displayed revision. For an open question use `resolve --revision R --question "Exact question?"` on the same onboarding command. Choosing `later` keeps the finding pending. If a first product area needs a new product brief, Oryx asks you to approve the new parent first. That brief is saved independently and remains available when you resume the area review.

The reported input size measures the data Core assembled for this response. A host can add its own instructions, references and tool output.
