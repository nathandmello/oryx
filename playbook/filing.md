# Filing PM work

Start with the question a reader will return to answer. Find the subject, accountable owner, and existing record before creating a path.

| If the material is… | Its home |
| --- | --- |
| A standing company fact, commitment, or exclusion | A short section in `context/company.md` |
| A product rule, buyer need, or approved product decision | The owning `products/<product>/context.md` |
| A rule for one area of a product | Label the area in its product brief. Initiative-specific details stay in the initiative brief. |
| A recurring initiative's outcome, scope, or workflow | `products/<product>/initiatives/<initiative>/context.md` |
| Evidence, an unknown, or a decision for existing PM work | Its section in the existing goal, problem, strategy, experiment, or roadmap |
| An original report, announcement, or external deliverable | Its source of record. Cite the location and date beside the relevant claim. |
| An update with no standing effect or follow-up | Its existing source, or a short dated entry when the PM wants it retained |
| Capture diagnostics, a source checklist, or drafting scratch | The reply. Use the brief's Sources section for citations. |

Keep the core brief broad. Give each applicable topic enough space to explain what a reader needs for routine decisions. Name material unknowns in place.

## When a file earns its place

1. Identify the reader, the question, and the accountable entity.
2. Search existing briefs, typed artifacts, and their supporting records. Update the one that already answers that question.
3. Create a primary artifact when its purpose, owner, and completion condition identify separate work.
4. For supporting detail, require a distinct subject, an independent reader need, and one of the three bases below.
5. Identify the parent record and a concrete review or closure trigger. Use the subject for the filename.
6. Link a useful child from the parent's relevant section. Keep source citations beside statements.

| Basis | Test | Example |
| --- | --- | --- |
| `event-history` | A consequential event has its own dated evidence, decisions, or follow-up that people will revisit. | An acquisition has regulatory milestones, integration decisions, and a closure date. |
| `maintained-reference` | A reader uses this reference independently. A named owner or event controls updates on a different cadence. | Finance revises regional rates each quarter. |
| `independent-deliverable` | A named consumer uses a distinct output with its own completion condition. | A support lead uses the migration briefing when the price change takes effect. |

File a supporting record under `<entity>/records/<subject>.md`. For a specific artifact, use `<entity>/records/<artifact-stem>/<subject>.md`. Use the owning brief or artifact as its parent.

A simple price announcement fits in one dated paragraph. A financial statement stays at its source. Cite the figures that change a decision.

A quarter, a new source, a writing limit, or an available template alone cannot justify a file. Retain meaningful exclusions and their operational consequences together.

For mixed sources, route each claim by subject and authority. A PM's remit controls relevance. It does not transfer ownership.

## Over time

Keep a single active home per subject. Merge overlapping records when their evidence and links can be preserved. Retain a dated history when readers still need it.

Read the primary brief first. Follow links for the task at hand. Promote a section only when it meets the same filing test.

The filing test adapts guidance about reader needs and consequential decisions. [Diátaxis compass](https://diataxis.fr/compass/) and [Documenting Architecture Decisions](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions).
