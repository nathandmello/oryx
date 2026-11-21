# oryx command convention

## Where the rules live

[AGENTS.md](../AGENTS.md) requires this convention for shared slash command changes.
This playbook defines the naming and compatibility rules.
[commands.json](commands.json) defines the paths, aliases, and routes that the menu and checker use.
The [extend-hub skill](../.agents/skills/extend-hub/SKILL.md) directs contributors here for each change.

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

## Name and register an action

1. Reuse a domain and subject where the new action serves the same work.
2. Use a lowercase noun for a new subject. Separate words with hyphens.
3. Reuse a verb from the catalog. Add a verb when an existing one cannot express the result.
4. Use an existing command's argument names and defaults. Pass product IDs, paths, and dates as arguments.
5. Register one canonical path under `commands` in [commands.json](commands.json). Give it a short summary for the menu.

For new interfaces, make required record identifiers positional. Use lowercase, hyphenated flags for filters and options.
Use `--format` for an existing choice of output formats.

Choose a new domain only for a durable area that oryx owns.
Define its boundary against the existing domains in the same change.
Keep published paths stable. If a subject or action must move, map its old path to the current one as a compatibility alias.
Use one canonical path per action in help and examples.

Use the shared catalog for all new slash actions. Put reusable agent workflows in canonical skills.

## Connect and check the action

For a deterministic action, declare its effect, fixed `pm.py` target, and example arguments.
Use `read` for inspection and previews. Use `local-write` for authorised private changes.
The slash route uses the target's existing options, validation, and state changes.
Choose a fixed operation when a terminal command serves several purposes.
If its argument order differs, expose a named terminal entry point that calls the same handler.

For a guided action, name the canonical skill or playbook. Describe the requested task in the summary.
The router returns the guide and arguments. The agent follows the guide and verifies scope before acting.

The backlog entry calls the existing terminal operation.

```json
"portfolio backlog show": {
  "summary": "Show the signed backlog and report review issues in the due view.",
  "effect": "read",
  "cli": ["backlog"],
  "example": ["--product", "checkout", "--due"]
}
```

Use the established approval procedure for signed decisions, external actions, and repository changes.
The catalog describes what an action does. Authority comes from the PM and the existing workflow.

Run `pm.py check --system-only` to validate names, unique CLI targets, aliases, guides, and CLI examples.
The checker rejects standalone command files in `.claude/commands/` and `.codex/prompts/`.
Test the public path with its normal arguments and a rejected input.
Keep both clients on the shared menu skill. Extend the catalog when an action fits these conventions.

Set `BASE_SHA` to the full commit SHA of the target branch before comparing a command change.

```sh
python3 tools/pm.py check --system-only --command-base "$BASE_SHA"
```

GitHub CI compares the proposed merge tree with the pull request base.
Published paths and aliases must resolve with the same effect. Published CLI examples must still parse.
Use a new path for a different effect. Keep the existing path available with its published behavior.
