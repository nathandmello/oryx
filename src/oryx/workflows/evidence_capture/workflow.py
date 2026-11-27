"""Step order and methods for context evidence capture."""

from ..method import Step


COMMAND = 'context evidence capture'
STEPS = (
    Step('inspect', '.agents/skills/ingest-context/SKILL.md', 'Inspect',
         'Determine the source, permitted use, coverage and evidence gaps.', ('route',)),
    Step('route', '.agents/skills/ingest-context/SKILL.md', 'Route',
         'Resolve the owning record and distinguish standing context from work.', ('review',)),
    Step('review', '.agents/skills/ingest-context/SKILL.md', 'Apply',
         'Show the exact proposed wording and wait for its owner to review.', ('finish',)),
)
