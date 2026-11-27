"""Step order and methods for context pm capture."""

from ..method import Step


COMMAND = 'context pm capture'
STEPS = (
    Step('listen', 'playbook/pm-context.md', 'Listen for five things',
         'Identify the PM remit, priorities, expectations, stakeholders and gaps.', ('scope',)),
    Step('scope', 'playbook/pm-context.md', 'Agree how to capture it',
         'Confirm the destination of each proposed finding.', ('review',)),
    Step('review', 'playbook/pm-context.md', 'Review one point at a time',
         'Return exact wording to the PM and preserve their decision.', ('pause',)),
    Step('pause', 'playbook/pm-context.md', 'Pause or move on',
         'Record the next eligible walkthrough or agreed stopping point.', ('finish',)),
)
