"""Step order and methods for context stakeholder-profile coach."""

from ..method import Step


COMMAND = 'context stakeholder-profile coach'
STEPS = (
    Step('select', 'playbook/stakeholder-profiles.md', 'Apply one observation',
         'Select an applicable confirmed observation and identify its limitations.', ('rehearse',)),
    Step('rehearse', '.agents/skills/stakeholder-profiles/SKILL.md', 'Rehearse a conversation',
         'Rehearse with the PM and preserve uncertainty about the person’s actual response.', ('finish',)),
)
