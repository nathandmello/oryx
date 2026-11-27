"""Step order and methods for discovery findings review."""

from ..method import Step


COMMAND = 'discovery findings review'
STEPS = (
    Step('inspect', '.agents/skills/run-discovery/investigate.md', 'Investigate and conclude',
         'Read the authorized timebox, outcomes, counterevidence and remaining gaps.', ('assess',)),
    Step('assess', 'playbook/brief-review.md', 'Match the test to the hypothesis',
         'Check the evidence against the pre-agreed decision criteria.', ('conclude',)),
    Step('conclude', 'playbook/initiative-approvals.md', 'Review gates',
         'Review uncertainty and obtain the owner’s next decision.', ('finish',)),
)
