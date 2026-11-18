# Company and product context

Company context explains the business. Product context explains the product's place within it. Strategy records choices through Nathan's Why, Who, What, and How.

Use [the templates](../templates/README.md) when context work starts. Aim for 400–600 words per brief. Link to detail.

## Ownership and relationships

Keep company context under `workspace/context/`. Add a business-unit brief only when the work needs one; link its parent company context.

Keep product context under `workspace/products/<product>/`. Link its relevant company context in Parent context. Reference shared facts; add product-specific facts and differences.

Link to authoritative goals, performance sources, research, and strategy. Keep each artifact in its existing home.

Keep PRDs, user stories, detailed flows, acceptance criteria, and engineering specifications in the configured delivery system. Context describes the current business and product.

## Claims and sources

Write each entry as a labelled bullet:

- `Fact:` an established claim with a source reference, such as `[S1]`.
- `Interpretation:` your reading of evidence. Cite its basis when available.
- `Assumption:` a belief that needs a test.
- `Unknown:` a gap or unresolved conflict. State its effect on the current question.

Keep one claim per entry. Indent continuation lines. Preserve conflicting sources and separate official direction from personal interpretation.

List each source once under Sources. Use unique IDs such as `S1`. Reference those IDs beside the claims they inform.

Record a link or a named person and discussion reference. Record the source date and the date you checked it.

Use `unknown` or `undated` when the source date is unavailable. A personal statement establishes its origin; it does not establish company approval.

## Reviews and partial work

Set the maintainer, review deadline, and change triggers before context leaves draft. Record Last reviewed only after an actual review.

Choose the review deadline for the decision and source volatility. A new file or text edit does not reset review dates.

Review parent-context changes for their effect on product context and linked work. Revisit goals, strategy, and other affected records when the change matters.

Use Unknown entries for unresolved gaps. Complete means usable for the stated scope; it does not mean every question has an answer.

Use [the existing checkpoints](working.md) across sessions. Context work can pause for evidence or another person's input.

## Checks and judgment

The checker validates sections, labels, source IDs, dates, parent links, review deadlines, and work state. Drafts can retain prompts and unset review dates.

An overdue review fails checks for active, waiting, or complete context. Review the record; preserve an honest gap if review remains blocked.

Agents assess source authority, claim accuracy, conflicts, and affected work. Checks cannot prove these judgments or detect external changes.

## Basis

Nathan approved these outlines after a comparison of established methods. This format adapts them for PM Hub:

- [Strategyzer Business Model Canvas](https://www.strategyzer.com/library/the-business-model-canvas): business model structure.
- [Product Talk Business Fundamentals](https://www.producttalk.org/business-fundamentals-course/): public questions about business context.
- [Roman Pichler Product Vision Board](https://www.romanpichler.com/tools/product-vision-board/): product, customers, needs, and business goals.
