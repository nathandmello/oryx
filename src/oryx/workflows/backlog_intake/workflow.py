"""Step order and methods for initiative intake capture."""

from ..method import Step


COMMAND = 'initiative intake capture'
STEPS = (
    Step('intake', '.agents/skills/manage-backlog/SKILL.md', 'Capture and evaluate',
         'Confirm whether the signal belongs to existing work or a distinct problem.', ('qualify',)),
    Step('qualify', 'playbook/opportunities.md', 'Evaluate incoming evidence',
         'Inspect the signal and counterevidence for the proposed problem.', ('reassess',)),
    Step('reassess', '.agents/skills/manage-backlog/SKILL.md', 'Reassess',
         'Return the decision, rationale and revisit condition to its owner.', ('finish',)),
)
