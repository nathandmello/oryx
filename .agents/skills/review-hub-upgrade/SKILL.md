---
name: review-hub-upgrade
description: Explain Hub updates, audit installed artifacts, and give the user a choice before transforming existing work.
---

# Review a Hub update

Use [the installed-workspace procedure](../../../playbook/updates.md). Keep the compatibility alignment and the user's artifact decisions distinct.

## Explain and audit

1. Describe what changed and what the user gains. Give examples relevant to their current work.
2. Run `python3 tools/pm.py align --status`. Review the affected records and available sources.
3. Summarize concrete findings by path. Explain which changes would improve readability, context retrieval, or the evidence behind a decision.
4. Flag uncertain claims and historical decisions. Review metric comparability and preserve the recorded basis of signed results.

With this update, briefs have a predictable structure. Workspace tasks can use scoped context. The metric registry gives analyses a consistent starting point and supports company definitions.

## Offer a choice

Offer to keep the existing artifacts or preview changes to selected records. Offer a complete preview when several records warrant review. The user may defer or approve a subset.

Ask before transforming existing artifacts. Treat an update request or a request for a preview as permission to inspect.

When the user requests a preview, describe each change, unresolved gap, and expected benefit. Use a read-only filing plan. Obtain explicit approval for the stated paths and changes before applying it.

Preserve IDs, meaningful links, sources, and signed history. Back up the original files. Verify the approved changes with `pm.py check`. If the user defers, preserve the existing records and respect their choice.
Use the initiative review workflow for signed briefs and planning comparisons.

Read the session checkpoint before repeating an offer. Resume from the user's recorded decision when it still applies.

When the audit finds no proposed transformation, report that result. Offer to revisit it if the user identifies an artifact.
