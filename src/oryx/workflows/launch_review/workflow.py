"""Step order and methods for delivery launch review."""

from ..method import Step


COMMAND = 'delivery launch review'
STEPS = (
    Step('inspect', '.agents/skills/manage-initiative-work/SKILL.md', 'Plan and review tasks',
         'Confirm the registered initiative, task status and dependencies.', ('review',)),
    Step('review', '.agents/skills/manage-initiative-work/SKILL.md', 'Run a launch review',
         'Verify checkpoints, linked tasks and waivers before asking for the ship decision.', ('finish',)),
)
