"""Step order and methods for workspace workflow open."""

from ..method import Step


COMMAND = 'workspace workflow open'
STEPS = (
    Step('choose', 'playbook/overrides.md', 'Add a workflow',
         'Identify the named private procedure and its requested outcome.', ('apply',)),
    Step('apply', 'playbook/overrides.md', 'Save and use a rule',
         'Use the applicable reviewed procedure and return its result.', ('finish',)),
)
