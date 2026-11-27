# Use oryx in a browser

Open oryx on the computer that holds your workspace.
Use the [shared command menu](commands.md) to start the app:

```text
/pm workspace browser open
```

An incomplete Studio shows the current [onboarding](company-context.md) stage. Continue the walkthrough in your oryx conversation.
The conversation guides company, PM and [parent product](product-context.md) setup. The optional area walkthrough leaves the requested view available.
Use **Check progress** to reopen the requested view after onboarding.

Once ready, the app opens to Roadmap by default. Add `--screen tasks` or `--screen launch-checklists` to start there.
From a terminal, run the same action:

```sh
python3 tools/pm.py action workspace browser open
```

For roadmap approval, run the terminal command above yourself with a Python installation that supports Tk.
A protected agent session can preview roadmap edits. Review the changes again in the app you opened yourself.
On an older Studio, follow the [existing-register instructions](initiative-approvals.md#existing-private-work).

The app opens a browser tab on the same computer. Keep the launch session active during use.
Share the browser tab for a meeting. Keep the launch URL private.

## Roadmap

Choose a product and planning cycle. Filter by area or select **Present** to enlarge the roadmap.

Each affected card shows the same [evidence reviews](evidence-reviews.md) as the terminal roadmap.

Use **Edit priorities** on an open cycle. Drag a card or use **Move** to change its position or horizon.
Return a planned card to the candidates to release its capacity. Cards stay fixed after delivery starts.

Choose **New planning cycle** to compare approved candidates. Enter dates, capacity, constraints, assessments, trade-offs, and sources.
Choose a horizon, rank, and effort for each selection. Use **Compare only** to leave an option available.

Save the comparison and review the proposal. The comparison uses the same Markdown record as the terminal workflow.
You can load an existing draft comparison by its cycle ID.

Choose **Approve on this computer** and review the exact changes in the desktop window.
Select **Approve and apply** to record them. Cancel to leave the proposal open.
If the register or comparison changes, review a fresh proposal.
If the app closes during an approved save, use [initiative recovery](initiative-approvals.md#existing-private-work).

## Tasks and launch checklists

Open **Tasks** or **Launch checklists**, then choose a product and initiative.
Add or edit items. Preview changes and save them to the same lists the terminal commands use.

Start a launch checklist from the [workspace starter](customization.md). Record evidence to verify a check.
A task edit preview names launch checks affected by withdrawn evidence. The checklist shows each outstanding reason and the earlier verification.

Choose independent evidence or specify verification task IDs when a check uses only some supporting tasks.
Record the approver and reason for a waiver. Review readiness before the launch decision.
If the list changes, inspect the current record and review your edits again.

See the [terminal workflow](initiative-work.md) for the list fields and [roadmap approvals](initiative-approvals.md) for the decision gates.
