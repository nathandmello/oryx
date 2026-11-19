# Artifact templates

Create only the artifact needed for the current work. Templates guide thought; they do not require a complete process in one session.

## Available templates

| Template | Purpose | Home |
| --- | --- | --- |
| [Company context](company-context.md) | Organisation, business model, direction, operations, and constraints | `context/` |
| [Product context](product-context.md) | Product purpose, users, vocabulary, constraints, and accepted decisions | `products/<product>/` |
| [Initiative context](initiative-context.md) | Outcome, affected workflow, dependencies, and decisions for recurring initiative work | `products/<product>/initiatives/<initiative>/` |
| [Context note](context-note.md) | Supporting detail that passes [the filing test](../playbook/filing.md) | The owning entity’s `records/` folder or its artifact subfolder |
| [Goal](goal.md) | The five outcome components and their alignment | Its owning company, product, or initiative home |
| [Problem](problem.md) | Customer problem, evidence, knowledge audit, and research | Its owning company, product, or initiative home |
| [Strategy](strategy.md) | Why, Who, What, and How | Its owning company, product, or initiative home |
| [Experiment](experiment.md) | Hypothesis, test, measure, criterion, and result | Its owning company, product, or initiative home |
| [Roadmap](roadmap.md) | Ordered outcomes and their rationale | Its owning company, product, or initiative home |

## Create a draft

Create an artifact from the system root. Destination paths are relative to `workspace/`:

```sh
python3 tools/pm.py new problem products/example/problem.md --title "Example problem"
```

Use the context templates when the PM starts that work:

```sh
python3 tools/pm.py new company-context context/company.md --title "Company context"
python3 tools/pm.py new product-context products/example/context.md --title "Product context"
python3 tools/pm.py new initiative-context products/example/initiatives/renewals/context.md --title "Renewals context"
```

The command creates a draft with a stable ID and a work-state block. It refuses an existing destination.

`{{placeholders}}` are intentional gaps. Drafts can keep them. Active work needs a checkpoint and next action; waiting work also needs a dependency and resume trigger.

Mark an artifact complete after its placeholders are resolved. Use `not applicable: reason` where a field does not apply. State unknowns explicitly.

The checker verifies structure and declared work state. It does not establish evidence quality, approval, or product success.

Context records follow [the context rules](../playbook/context.md). Remove unused content sections. Keep the context controls, sources, and work state.

Keep sources and related artifacts as links. The command resolves internal links from the new file's location.

Use [the working practices](../playbook/working.md) for checkpoints and modes. Follow [the framework](../playbook/framework.md) for the method.

Add another artifact type only when the PM requests it.
