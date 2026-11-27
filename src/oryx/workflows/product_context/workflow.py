"""Step order and methods for context product capture."""

from ..method import Step


COMMAND = 'context product capture'
STEPS = (
    Step('parent', 'playbook/product-context.md', 'Step 3. Review the parent product',
         'Confirm the parent product and gather the PM’s current account.', ('review',)),
    Step('review', 'playbook/product-context.md', 'Review and save findings',
         'Review material findings before any official write.', ('area', 'finish')),
    Step('area', 'playbook/product-context.md', 'Step 4. Offer an area walkthrough',
         'Offer the area walkthrough only for a confirmed area and willing PM.', ('finish',)),
)
