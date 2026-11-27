"""Step order and methods for context stakeholder-profile capture."""

from ..method import Step


COMMAND = 'context stakeholder-profile capture'
STEPS = (
    Step('identify', '.agents/skills/stakeholder-profiles/SKILL.md', 'Get to know a person',
         'Confirm which stakeholder the PM means and whether profile work is wanted.', ('qualify',)),
    Step('qualify', 'playbook/stakeholder-profiles.md', 'Choose where a finding belongs',
         'Confirm source coverage and whether the finding belongs to the map or profile.', ('review',)),
    Step('review', 'playbook/stakeholder-profiles.md', 'Review one change',
         'Review one permitted observation, its source and exact wording.', ('finish',)),
)
