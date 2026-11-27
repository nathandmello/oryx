"""Step order and methods for portfolio roadmap plan."""

from ..method import Step


COMMAND = 'portfolio roadmap plan'
STEPS = (
    Step('compare', '.agents/skills/prioritize-roadmap/SKILL.md', 'Compare investments',
         'Compare the baseline and candidate, capacity, uncertainty and displaced work.', ('decide',)),
    Step('decide', '.agents/skills/prioritize-roadmap/SKILL.md', 'Record the decision',
         'Show the changes and let the PM choose what proceeds.', ('finish',)),
)
