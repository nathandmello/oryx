"""Step order and methods for context meeting summarize."""

from ..method import Step


COMMAND = 'context meeting summarize'
STEPS = (
    Step('select', '.agents/skills/summarize-meeting/SKILL.md', 'Identify the initiative and meetings',
         'Confirm the initiative, meeting and occurrence.', ('retrieve',)),
    Step('retrieve', '.agents/skills/summarize-meeting/SKILL.md', 'Retrieve transcripts',
         'Read only permitted transcripts and report incomplete coverage.', ('summarize',)),
    Step('summarize', '.agents/skills/summarize-meeting/SKILL.md', 'Summarize each meeting',
         'Give the cited summary and ask whether it should remain in chat.', ('file', 'finish')),
    Step('file', '.agents/skills/summarize-meeting/SKILL.md', 'File initiative context',
         'Review a separate capture if the PM chooses to file the summary.', ('finish',)),
)
