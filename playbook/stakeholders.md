# Stakeholder context

The stakeholder map lives at `studio/context/stakeholders/overview.md`. Use it to understand who is involved in a specific team's work or decision.

During [PM onboarding](pm-context.md), offer to map the people the PM already mentioned. A role or team name can be enough.
Ask one question where an answer would help. “Who else weighs in on Billing priorities?” can follow a discussion of that decision.

| Topic | What to capture |
| --- | --- |
| `people` | The person's role or team and their stated remit. |
| `reporting` | Who reports to whom and where that relationship applies. |
| `authority` | Who recommends, decides, approves, or advises on the named decision. |
| `collaboration` | Who works together and on what. Include informal influence when the PM can describe it. |

Keep reporting, collaboration, and decision authority distinct. A job title alone leaves decision authority open.
Preserve relevant limits, timing, and exceptions. Use roles, the PM’s words, and permitted source references. Leave personal speculation out.

Show one suggested entry with its source and destination. Save the wording the PM accepts through the [PM walkthrough](pm-context.md).
For subsequent updates use [context capture](context.md) with scope `stakeholder`. Update this map when an agreed reporting line, responsibility, or decision role changes.
Older PM profiles can hold stakeholder notes. Review relevant entries with the PM before carrying them forward.

Use `/pm context stakeholder show` to look up a relationship. During setup, read the relevant map section and its source.
After setup, `pm.py task-context "Show the stakeholder map"` retrieves accepted entries with citations.
“Who approves Billing renewals?” also retrieves Billing evidence when the product is known.
Use entries that cover the decision. Leave authority open where the sources only establish reporting or collaboration.

Use a [stakeholder profile](stakeholder-profiles.md) for approved observations about working with a person. The map remains the source for scoped relationships.

## Sharing a Studio across versions

Update each client before sharing a Studio that contains this map. Version 0.11.0 can still read and edit the PM profile.
Its workspace check reports an unknown artifact type for the map. Its capture tool cannot update stakeholder records.
Keep the current Studio backup. Restore a compatible Core to use its map again after a rollback.
