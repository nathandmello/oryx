"""Step order and methods for context company capture."""

from ..method import Step


COMMAND = 'context company capture'
STEPS = (
    Step('frame', 'playbook/company-context.md', 'Start where the PM is',
         'Agree on the company scope and the most useful unknown.', ('assess',)),
    Step('assess', 'playbook/company-context.md', 'Decide what to capture',
         'Distinguish an eligible source from an unverified claim.', ('review',)),
    Step('review', 'playbook/company-context.md', 'Review and resume',
         'Review each proposed finding with its source and destination.', ('finish',)),
)
