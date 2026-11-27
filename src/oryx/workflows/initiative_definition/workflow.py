"""Step order and methods for initiative brief draft."""

from ..method import Step


COMMAND = 'initiative brief draft'
STEPS = (
    Step('frame', '.agents/skills/define-initiative/SKILL.md', 'Define an initiative',
         'Confirm the registered initiative, problem, audience, scope and alternative.', ('review',)),
    Step('review', 'playbook/brief-review.md', 'Check what each sentence commits to',
         'Resolve claims, trade-offs, exclusions, evidence and material gaps.', ('approve',)),
    Step('approve', 'playbook/initiative-approvals.md', 'Propose and approve',
         'Return the exact reviewed brief and proposal to the PM for the lifecycle decision.', ('finish',)),
)
