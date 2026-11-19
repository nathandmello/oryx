---
name: manage-initiative-work
description: Use for initiative PM tasks, delivery coordination, launch checklists, readiness evidence, and post-launch follow-through.
---

# Manage initiative work

Read [initiative work](../../../playbook/initiative-work.md). Resolve the exact product and initiative before making a change.
Use `pm.py task-context --product PRODUCT --initiative INITIATIVE "TASK"` to find applicable context.

## Plan and review tasks

1. Read the initiative's scope, current task list, and relevant decisions.
2. Turn a confirmed action into a task with a concrete outcome and completion criteria.
3. Keep the stated owner, date, and priority. Leave unknown values empty.
4. Link dependencies and source decisions. Link delivery tickets to coordinate work with Engineering.
5. Review blocked and overdue work first. Name the next action and who must take it.
6. Close work using the reported result. Record cancellation with the reason.

## Run a launch review

Use the [conversation guide](../../../playbook/conversation.md) at a consequential launch decision. Keep routine checklist maintenance direct.

1. Read the launch scope and current checklist. Preview the starter when the initiative needs its first checklist.
2. Tailor upstream, launch, and downstream checks to the release audience and risks.
3. Link supporting tasks. Ask the responsible person for evidence when verification is missing.
4. Record evidence, verifier, and date for a confirmed check. Record any waiver with the approver and rationale.
5. Show open readiness checks before the go or no-go decision. Keep follow-through visible after launch.

Use `pm.py task` or `pm.py launch-checklist` to list and preview edits. Apply the reviewed edits when authorised.
Keep scope decisions and commitments with the PM. Check confirmed changes through the generated view.
