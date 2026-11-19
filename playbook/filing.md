# Filing PM work

Choose the purpose first. File information used for reference in `context/`. File work the PM plans, prioritises, executes, or measures in `workspace/`. Both paths start at the private repository root.

| Reader need | Home |
| --- | --- |
| Company-wide facts, commitments, or exclusions | `context/company/overview.md` |
| Standing product guidance | `context/products/<product>/overview.md` |
| Standing guidance for one product area | A labelled entry in the product overview, or its maintained area overview |
| Reusable initiative guidance | `context/initiatives/<initiative>/overview.md`, linked to the owning product |
| PM background, preferences, responsibilities, or interests | `context/pm/context.md` |
| Priorities, plans, progress, or tests | The applicable work type under `workspace/`, such as `workspace/experiments/` |
| Proposed investments, sources, and lifecycle decisions | Signed `workspace/backlogs/<product>/initiatives.json` |
| Formal discovery or proposed investment | `discovery-brief.md` or `initiative-brief.md` under `workspace/initiatives/<product>/<initiative>/` |
| Test for an initiative metric | `workspace/experiments/<product>/<initiative>/experiment.<metric-id>.draft.json` during drafting |
| Investment comparison for a planning cycle | `workspace/roadmaps/<product>/<cycle>.md` |
| Current backlog or selected roadmap | Generate either view from the register with `pm.py backlog` or `pm.py roadmap` |
| Original reports, announcements, or external deliverables | Their source of record. Cite the location, date, and relevant passage. |
| Capture diagnostics, audit results, or drafting scratch | The reply. Record citations in the brief’s Sources section. |

Route each mixed-source claim by purpose and accountable entity. Use the PM remit to determine relevance. A price announcement belongs in company context. An authorised rollout plan belongs in the workspace.

## When a file earns its place

Start with the entity overview. Keep it broad and put unknowns beside the affected claims. Update an existing entry that answers the reader's question.

A separate reference note needs a distinct subject, an independent reader need, and a review or closure trigger. Record its parent and one of these bases.

| Basis | Qualifying use |
| --- | --- |
| `event-history` | People return to the dated evidence, decisions, or milestones of a consequential event. |
| `maintained-reference` | A reader consults the reference independently. An identified owner or event governs updates. |
| `independent-deliverable` | A named reader uses a separate reference output with its own completion condition. |

Put the first qualifying note directly beside its overview. For example, `context/company/acme-acquisition.md` can hold integration milestones and their sources. Link it from the overview during authorised maintenance. A new source or writing limit alone cannot justify another file.

## When a topic earns a folder

1. Search this entity's notes and existing topic questions. Reuse the closest topic that answers the same question.
2. Identify two distinct subjects that already meet the separate-file test. One must be an existing flat note under this entity.
3. State the recurring question that brings readers to both subjects. Name the folder with a short, stable subject term.
4. Supply the existing note and question when creating the second note in the new folder.
5. Leave the original note in place. Use a reviewed filing plan to move it if readers need both together.

A folder can group acquisition histories, financial measures, or another subject supported by the evidence. Use one topic level and at most six topic folders per entity. At the limit, reuse a suitable folder or keep a qualified note flat. Dates, source names, and catch-alls such as `misc` or `records` make poor topic names.

For example, Finance reviews regional refund rules after policy changes. If two independently useful policies already meet the test, a `refund-policies/` folder can answer “Which refunds need Finance approval?”

With `pm.py new context-note`, add `--topic-question` and `--topic-peer` for the first note in a new topic. With `route-context`, supply `record.topic_question` and `record.topic_peer`. Keep the parent, basis, reader need, and trigger for each note.

## Product area context

An area is a lasting part of one product. Keep product-wide rules in its overview. Keep initiative plans and delivery progress in the workspace.

One area fact fits inline. Create `context/products/<product>/areas/<area>/overview.md` when readers independently need recurring area guidance and a specific change triggers review.

An initiative can concern zero, one, or several product areas. Record confirmed area subjects once on the registered initiative.
For example, `product/checkout/area/refunds` identifies the refunds area of checkout.
A remit, folder name, or sibling area alone provides insufficient evidence for that assignment.

For area work, run `python3 tools/pm.py area-context <product> <area>`. Read the product overview, the area overview, and relevant inline entries. Each source ID belongs to its original record. Inspect older unlabelled text before assigning an area.

Answer questions in their original homes. Cite a completed experiment when its finding becomes standing guidance. Keep its result and work history in the experiment.

This filing test draws on guidance about reader needs and consequential decisions. [Diátaxis compass](https://diataxis.fr/compass/) and [Documenting Architecture Decisions](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions).
