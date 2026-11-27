"""Step order and methods for delivery outcome review."""

from ..method import Step


COMMAND = 'delivery outcome review'
STEPS = (
    Step('measure', 'playbook/outcome-evidence.md', 'Record a reading',
         'Check the applicable definition, window, source, population and guardrails.', ('correct',)),
    Step('correct', 'playbook/outcome-evidence.md', 'Correct the source or reading',
         'Surface restatements, qualifications and contrary signals.', ('decide',)),
    Step('decide', 'playbook/outcome-evidence.md', 'Approve the outcome review',
         'Ask the PM to review the evidence and the next decision.', ('finish',)),
)
