"""Step order and methods for context stakeholder show."""

from ..method import Step


COMMAND = 'context stakeholder show'
STEPS = (
    Step('lookup', 'playbook/stakeholders.md', 'Stakeholder context',
         'Answer the question from the confirmed stakeholder map with scope and qualifications.', ('finish',)),
)
