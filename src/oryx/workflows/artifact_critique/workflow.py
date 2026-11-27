"""Step order and methods for review artifact critique."""

from ..method import Step


COMMAND = 'review artifact critique'
STEPS = (
    Step('frame', '.agents/skills/red-team/SKILL.md', 'Frame the review',
         'Agree on the artifact, revision, permitted evidence and review question.', ('isolate',)),
    Step('isolate', '.agents/skills/red-team/SKILL.md', 'Give reviewers a fresh read',
         'Provide independent reviewers only the approved material.', ('critique',)),
    Step('critique', '.agents/skills/red-team/SKILL.md', 'Run the review',
         'Inspect credible failure modes and counterevidence.', ('report',)),
    Step('report', '.agents/skills/red-team/SKILL.md', 'Return the findings',
         'Return supported issues or report that no material issue was found.', ('finish',)),
)
