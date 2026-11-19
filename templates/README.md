# Artifact templates

Create only the artifact needed for the current work. Templates guide thought; they do not require a complete process in one session.

## Available templates

| Template | Purpose | Home |
| --- | --- | --- |
| [Company context](company-context.md) | Organisation, business model, direction, operations, and constraints | `context/company/overview.md` |
| [Product context](product-context.md) | Product purpose, users, vocabulary, constraints, and accepted decisions | `context/products/<product>/overview.md` |
| [Product area context](product-area-context.md) | Standing area boundaries, users, rules, goals, and decisions | `context/products/<product>/areas/<area>/overview.md` |
| [Initiative context](initiative-context.md) | Outcome, affected workflow, dependencies, and decisions for recurring initiative work | `context/initiatives/<initiative>/overview.md` |
| [Context note](context-note.md) | Supporting detail that passes [the filing test](../playbook/filing.md) | One topic level under the owning context entity, when the filing rule permits it |
| [Goal](goal.md) | The five outcome components and their alignment | `workspace/goals/` |
| [Problem](problem.md) | Customer problem, evidence, knowledge audit, and research | `workspace/problems/` |
| [Strategy](strategy.md) | Why, Who, What, and How | `workspace/strategies/` |
| [Experiment](experiment.md) | Hypothesis, test, measure, criterion, and result | `workspace/experiments/` |
| [Roadmap](roadmap.md) | Ordered outcomes and their rationale | `workspace/roadmaps/` |

Create a [PM profile](../playbook/context.md#pm-remit) with `new pm-context context/pm/context.md`. Add background and preferences directly in Markdown.

Backlogs in `workspace/backlogs/<subject>.md` and plans in `workspace/initiatives/<initiative>/plan.md` use ordinary Markdown. Cite the applicable entity context.

## Create a draft

Create an artifact from the system root. Destination paths are relative to `private/`.

```sh
python3 tools/pm.py new problem workspace/problems/example-onboarding.md --title "Example problem"
```

Use the context templates when the PM starts that work:

```sh
python3 tools/pm.py new company-context context/company/overview.md --title "Company context"
python3 tools/pm.py new product-context context/products/example/overview.md --title "Product context"
python3 tools/pm.py new initiative-context context/initiatives/renewals/overview.md --parent context/products/example/overview.md --title "Renewals context"
```

For a separately maintained [product area](../playbook/filing.md#product-area-context), record the reader need and review trigger:

```sh
python3 tools/pm.py new product-area-context context/products/example/areas/refunds/overview.md \
  --title "Refunds context" --reason "Support uses refund eligibility rules each week." \
  --trigger "Finance changes the refund policy."
```

The command creates a draft with a stable ID and a work-state block. It refuses an existing destination.

`{{placeholders}}` are intentional gaps. Drafts can keep them. Active work needs a checkpoint and next action; waiting work also needs a dependency and resume trigger.

Mark an artifact complete after its placeholders are resolved. Use `not applicable: reason` where a field does not apply. State unknowns explicitly.

The checker verifies structure and declared work state. It does not establish evidence quality, approval, or product success.

Context records follow [the context rules](../playbook/context.md). Remove unused content sections. Keep the context controls, sources, and work state.

Keep sources and related artifacts as links. The command resolves internal links from the new file's location.

Use [the working practices](../playbook/working.md) for checkpoints and modes. Follow [the framework](../playbook/framework.md) for the method.

Add another artifact type only when the PM requests it.
