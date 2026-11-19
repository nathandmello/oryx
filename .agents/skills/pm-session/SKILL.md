---
name: pm-session
description: Resume, checkpoint, or hand off PM Hub work. Use for session pauses and standalone mode changes such as quiet.
---

# Resume or hand off PM work

1. Follow [the session steps](../../../playbook/working.md#run-a-workflow). Read the work record, its checkpoint, and its linked decisions.
2. Apply the current request and any saved mode. Save an explicitly requested mode change in the current record.
3. For a resume, take the recorded next action when its dependency has cleared and it fits the current request.
4. If that action has its own PM Hub skill, read and follow it. Limit work to the current action.
5. For a pause or handoff, update the work record and `private/README.md`. Follow [the checkpoint steps](../../../playbook/working.md#checkpoint).
6. In quiet mode, complete the requested capture or acknowledge the pause. Surface a blocking limitation in one sentence.
