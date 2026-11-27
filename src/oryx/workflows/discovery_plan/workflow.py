"""Step order and methods for discovery brief draft."""

from ..method import Step


COMMAND = 'discovery brief draft'
STEPS = (
    Step('frame', '.agents/skills/run-discovery/plan.md', 'Plan the investigation',
         'Identify the registered initiative and its decision-critical uncertainty.', ('test',)),
    Step('test', 'playbook/brief-review.md', 'Match the test to the hypothesis',
         'Agree on signal, counterevidence, timebox, stop and decision.', ('review',)),
    Step('review', 'playbook/initiative-approvals.md', 'Propose and approve',
         'Send the proposed investigation to the authorized decision owner.', ('finish',)),
)
