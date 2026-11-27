"""Step order and methods for review decision coach."""

from ..method import Step


COMMAND = 'review decision coach'
STEPS = (
    Step('frame', 'playbook/conversation.md', 'Start with the choice',
         'Agree on the decision and its owner, constraints and urgency.', ('compare',)),
    Step('compare', 'playbook/conversation.md', 'Compare and review',
         'Surface alternatives, trade-offs, contrary evidence and uncertainty.', ('next',)),
    Step('next', 'playbook/conversation.md', 'Offer one next step',
         'Return the choice to its owner and agree on the next step.', ('finish',)),
)
