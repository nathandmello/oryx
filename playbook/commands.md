# oryx command convention

## Use the menu

In Claude Code, enter `/pm`. In Codex CLI or the IDE, select `pm` from `/skills` or type `$pm`.
In the ChatGPT desktop app, select the `pm` skill from the slash menu when available.

Use `/pm DOMAIN SUBJECT VERB [arguments]`. Use the same arguments after the skill name in each client.
Enter a domain to see its subjects. Enter a domain and subject to see the available actions.
Add `--help` to a complete command to see its purpose, example, and options.

From the oryx checkout root, use `python3 tools/pm.py action` in place of `/pm`.
Use `action --catalog` for the machine-readable catalog.
Use `action --describe DOMAIN SUBJECT VERB` for one action's route and effect.

## Choose the domain

Choose the domain by the record, view, or decision the action serves.
Use the subject to name the record or workflow within that domain.
Use the verb to describe what the PM gets.

| Domain | When to use it | Example |
| --- | --- | --- |
| `context` | Maintain standing reference material or preserve source evidence. | `/pm context meeting summarize` |
| `strategy` | Work on goals, outcomes, or product strategy. | `/pm strategy brief draft` |
| `discovery` | Validate a customer problem or test an assumption. | `/pm discovery experiment draft` |
| `initiative` | Capture, inspect, or define one proposed investment. | `/pm initiative record show` |
| `portfolio` | Compare or view work across initiatives and cycles. | `/pm portfolio roadmap show` |
| `delivery` | Review handoff, launch, enablement, or shipped outcomes. | `/pm delivery outcome review` |
| `review` | Apply independent critique across multiple kinds of work. | `/pm review artifact critique` |
| `workspace` | Manage personal settings, repository state, or oryx health. | `/pm workspace preferences show` |

Onboarding starts in conversation. For a direct entry point, use `/pm context company capture` or `/pm context pm capture`.
Use `/pm context company show` for company review progress, `/pm context pm show` for your profile, and `/pm context stakeholder show` for relationships.

For meeting evidence about a potential initiative, use context capture to preserve the source.
Use initiative intake when the PM wants to assess a distinct investment or attach a signal to one.
Use the owning domain for a required review stage. Use `review` for independent critique that applies across subjects.
