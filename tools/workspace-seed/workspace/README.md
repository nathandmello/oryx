# PM work

Keep work here by type. Examples include backlogs, roadmaps, initiatives, and experiments. Create a folder when the PM has work to save there.

Use the [artifact templates](../../../templates/README.md) for supported work types. Link to [context](../context/README.md) for the applicable rules or evidence.

For working Markdown, use Scope, Evidence, and Next action in that order. State the evidence gap while work is incomplete.

For registered initiatives, use these paths relative to the private repository:

| Work | Location |
| --- | --- |
| Product initiative register | `workspace/backlogs/<product>/initiatives.json` |
| Discovery and Initiative Briefs | `workspace/initiatives/<product>/<initiative>/` |
| PM tasks and launch checkpoints | `tasks.json` and `launch-checklist.json` beside the initiative briefs |
| Metric-linked experiment drafts | `workspace/experiments/<product>/<initiative>/experiment.<metric-id>.draft.json` |
| Planning comparison for one cycle | `workspace/roadmaps/<product>/<cycle>.md` |

Run `python3 tools/pm.py backlog --product PRODUCT` or `python3 tools/pm.py roadmap --product PRODUCT` from the oryx root.
Add `--area AREA` for work explicitly linked to that product area. Follow the [opportunity workflow](../../../playbook/opportunities.md) for stage decisions.

Use the [initiative work commands](../../../playbook/initiative-work.md) to manage tasks and review launch readiness.

Keep a completed artifact with its work history. If a result changes standing guidance, record that finding in the relevant overview with its source.
