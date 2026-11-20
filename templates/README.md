# Artifact templates

Create only the artifact needed for the current work. Templates guide thought; they do not require a complete process in one session.

## Available templates

| Template | Purpose | Home |
| --- | --- | --- |
| [Company context](company-context.md) | Customer value, economics, portfolio, growth, competitive advantage, and strategic trade-offs | `context/company/overview.md` |
| [Product context](product-context.md) | Product purpose, users, vocabulary, constraints, and accepted decisions | `context/products/<product>/overview.md` |
| [Product area context](product-area-context.md) | Standing area boundaries, users, rules, goals, and decisions | `context/products/<product>/areas/<area>/overview.md` |
| [Initiative context](initiative-context.md) | Outcome, affected workflow, dependencies, and decisions for recurring initiative work | `context/products/<product>/initiatives/<initiative>/overview.md` |
| [Context note](context-note.md) | Supporting detail that passes [the filing test](../playbook/filing.md) | One topic level under the owning context entity, when the filing rule permits it |
| [Goal](goal.md) | The five outcome components and their alignment | `workspace/goals/` |
| [Problem](problem.md) | Customer problem, evidence, knowledge audit, and research | `workspace/problems/` |
| [Strategy](strategy.md) | Why, Who, What, When, and How | `workspace/strategies/` |
| [Experiment](experiment.md) | Hypothesis, test, measure, criterion, and result | `workspace/experiments/` |
| [Discovery Brief](discovery-brief.md) | Timebox, learning goals, evidence, and conclusion | `workspace/initiatives/<product>/<initiative>/discovery-brief.md` |
| [Initiative Brief](initiative-brief.md) | Investment case, scope, launch, and success measures | `workspace/initiatives/<product>/<initiative>/initiative-brief.md` |
| [Launch checklist](launch-checklist.json) | Starter checkpoints for launch readiness and follow-through | `workspace/initiatives/<product>/<initiative>/launch-checklist.json` |
| [Prioritization](prioritization.md) | Comparison of approved candidates for a planning cycle | `workspace/roadmaps/<product>/<cycle>.md` |
| [Roadmap](roadmap.md) | Narrative roadmap for work outside the signed initiative register | `workspace/roadmaps/` |

Create a [PM profile](../playbook/context.md#pm-remit) with `new pm-context context/pm/context.md`. Add background and preferences directly in Markdown.

Use the [context section rules](../playbook/filing.md#when-a-section-earns-its-place) to choose headings. Give each substantive section a lead that explains when it applies.

Registered initiatives share one signed product register. Generate their live backlog and roadmap with the [view templates](../playbook/initiative-views.md).
For other working plans, use Scope, Evidence, and Next action in that order. State specific evidence gaps. Link applicable context.

## Create a draft

Run `pm.py new` from the oryx root. Destination paths are relative to `studio/`. New drafts include applicable [Studio and product template changes](../playbook/customization.md).

```sh
python3 tools/pm.py new problem workspace/problems/example-onboarding.md --title "Example problem"
```

Use the context templates when the PM starts that work:

```sh
python3 tools/pm.py new company-context context/company/overview.md --title "Company context"
python3 tools/pm.py new product-context context/products/example/overview.md --title "Product context"
python3 tools/pm.py new initiative-context context/products/example/initiatives/renewals/overview.md --parent context/products/example/overview.md --title "Renewals context"
```

For a separately maintained [product area](../playbook/filing.md#product-area-context), record the reader need and review trigger:

```sh
python3 tools/pm.py new product-area-context context/products/example/areas/refunds/overview.md \
  --title "Refunds context" --reason "Support uses refund eligibility rules each week." \
  --trigger "Finance changes the refund policy."
```

Create registered briefs after capture. The command fills the Parent initiative section from the signed register. For the fictional product `checkout` and initiative `refund-delays`, run:

```sh
python3 tools/pm.py new discovery-brief workspace/initiatives/checkout/refund-delays/discovery-brief.md
python3 tools/pm.py new initiative-brief workspace/initiatives/checkout/refund-delays/initiative-brief.md
python3 tools/pm.py new prioritization workspace/roadmaps/checkout/quarter-two.md
```

Follow [the initiative workflow](../playbook/opportunities.md) for the applicable decision gates.

For registered initiative metrics, use the [named experiment draft](../playbook/opportunities.md#start-an-experiment-draft). The register supplies the metric definition.

Use [initiative work commands](../playbook/initiative-work.md) to start the launch checklist and manage PM tasks.

The Markdown command creates a draft with a stable ID and a work-state block. It refuses an existing destination.

`{{placeholders}}` are intentional gaps. Drafts can keep them. Active work needs a checkpoint and next action; waiting work also needs a dependency and resume trigger.

Mark an artifact complete after its placeholders are resolved. Use `not applicable: reason` where a field does not apply. State unknowns explicitly.

The checker verifies structure and declared work state. It does not establish evidence quality, approval, or product success.

Context records follow [the context rules](../playbook/context.md). Remove unused content sections. Keep the context controls, sources, and work state.

Keep sources and related artifacts as links. The command resolves internal links from the new file's location.

Use [the working practices](../playbook/working.md) for checkpoints and modes. Follow [the framework](../playbook/framework.md) for the method.
Use [the brief-review checks](../playbook/brief-review.md) to review a strategy, initiative, or test.

Add another artifact type only when the PM requests it.
