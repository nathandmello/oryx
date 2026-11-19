# Enforce the PM framework in skills

Nathan's [Product Strategy Mindset](sources/product-strategy-mindset.md) defines the method. The [framework guide](framework.md) maps it to Hub records. A command checks the record and selects the next step from saved state. The PM judges the evidence and owns the decision.

## What the research supports

BMAD Toolsmith gives each step an observable completion condition. It sequences dependent steps and loads the current step when needed. Its Build workflow reads existing status before choosing a route. Use these patterns for resumes and decision gates. [Toolsmith canon](https://github.com/bmad-code-org/BMAD-METHOD/blob/e435a22574fe55722841086e5566420178b98df3/skills/toolsmith/bmad-toolsmith/canon.md), [Build routing](https://github.com/bmad-code-org/BMAD-METHOD/blob/e435a22574fe55722841086e5566420178b98df3/skills/method/bmad-build/step-01-clarify-and-route.md)

BMAD renders skill instructions as Markdown based on project options. PM Hub's Python strategy command returns the next step and remaining gaps as JSON. The strategy skill uses that result to select the applicable instructions. [BMAD rendered-skill shape](https://github.com/bmad-code-org/BMAD-METHOD/blob/e435a22574fe55722841086e5566420178b98df3/skills/toolsmith/bmad-toolsmith/shapes/rendered-skill/shape.md)

Schemas can enforce shape and allowed values. Checks at the action boundary enforce business rules. Source accuracy, causal reasoning, and the PM's actual approval still need people or a trusted approval surface. [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs), [Guardrails and human review](https://developers.openai.com/api/docs/guides/agents/guardrails-approvals)

## Apply the framework at real decision points

The strategy command and context router enforce the strategy and capture checks below. The skills guide the other steps alongside existing signed workflows.

| Workflow | Required input or action | Judgment the PM workflow must preserve |
| --- | --- | --- |
| Context | Use `ingest-context` for private context routing and source coverage. Check labels, fact sources, dates, parent records, and review deadlines. | Verify source authority and assess which linked decisions a change affects. |
| Goals | Require the five outcome fields. Validate parent references and preserve an explicit baseline or direction gap. | Confirm the business contribution and agree on targets and guardrails. |
| Discovery | Require the four problem statement fields and a source for each Know entry. Keep Think and Curious distinct. | Judge research fit, sampling limits, contradictions, and the riskiest assumption. |
| Strategy | Check evidence links, the four leads, blockers, and sourced PM decisions. A validated value claim needs Product's assessment and a sourced test result. | Check the brief's reasoning and whether evidence of demand, observed impact, and the experiment confirms priority. |
| Experiment | Capture a dated criterion before testing. Preserve that revision. Compare results against the original and retain dated amendments. | Choose an appropriate test and interpret uncertainty or inconclusive results. |
| Roadmap | Check outcome and initiative links. Require a reason, uncertainty, and dependencies for the proposed order. | Resolve tradeoffs and confirm commitments with their owners. |
| Session | Read the saved mode, next action, and waiting dependency. Render the current action or wait. | Apply the PM's current instruction and identify whether a dependency has cleared. |
| Git | Use the existing wrapper for destination checks and repository boundaries. | Apply the PM's authorisation for the requested repository and operation. |

## Strategy implementation

Create new briefs in `private/workspace/strategies/`. The strategy command reports the first missing input. The workspace check and filing preview use the same contract. They check accepted decisions and claims of validated value in new drafts.

Older records remain readable and keep their prior checks. For a new review, update the same record to the current template. Carry forward its ID, evidence, and confirmed decisions.

Use the [filing workflow](updates.md#convert-existing-work) for moves and conversions. Preview and apply check the strategy contract before changing a record. The filing workflow retains original bytes for recovery.

Strategy review reports missing local links before review. Preserved originals in `sources/` or the upgrade ledger stay evidence. Active briefs supply filing destinations, parents, and record IDs.

The checker verifies cited source IDs and decision fields. The skill requires the agent to check that the sources support the claims. A passing check means the record satisfies measurable criteria. Actual approval comes from the PM. Project hooks run checks at supported points. Stronger access enforcement requires a write surface that the agent cannot bypass.

## Measure the result

Compare the previous skill and the revised skill on the same starting records and prompts. Inspect the tool trace, saved output, and checkpoint. Score premature completion, invented evidence, wrong owners, and unconfirmed decisions as failures.

Repeat with explicit skill invocation and plain requests. Hold out close alternatives such as reviewing a strategy versus revising one. Compare whether the PM can use each brief to make the decision. [PM Hub eval cases](../tests/skill-evals.md), [BMAD eval format](https://github.com/bmad-code-org/BMAD-METHOD/blob/e435a22574fe55722841086e5566420178b98df3/skills/toolsmith/bmad-eval/references/eval-format.md), [OpenAI skill evals](https://developers.openai.com/blog/eval-skills)
