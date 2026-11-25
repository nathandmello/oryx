# oryx

**A personal workspace for PMs and founders who manage their own products with Codex or Claude Code.**

A customer asks for better reporting. You remember passing on it last quarter. What changed? With oryx, you can put today's interview beside the original decision and see whether the case is any stronger. Your evidence and decisions live in a private Git repository on your machine. Either client can pick up the thread next time.

I chose the oryx for its resilience and endurance in harsh environments. I’m building this to help PMs keep product craft alive as AI changes how we work. Knowing which question to ask, whose experience to trust, and when to change your mind still matters.

You own the product decisions and the words you share. Oryx can gather the evidence, work through trade-offs with you, and help write what you mean.
When time is tight, ask for expedite mode. Oryx takes on more legwork and keeps each evidence check and decision with its owner.

[Quick start](#quick-start) · [Make it yours](#make-it-yours) · [Browse the workflows](playbook/commands.md)

## What a day with oryx looks like

| When | What you might ask | What you get |
| --- | --- | --- |
| After an interview | “Here’s the interview. Capture why they export every Friday and what we still need to ask.” | A sourced meeting note that separates what the customer said from your interpretation. |
| Before roadmap review | “Reporting is back on the table. Compare these interviews with what we knew when we deferred it.” | The earlier rationale, the new evidence, and the assumptions you still need to test. |
| When capacity changes | “We can fit one of these two initiatives. Show me what we give up with each choice.” | A planning comparison you can discuss. You approve changes to the roadmap. |
| After launch | “We expected fewer support tickets. Compare the result with our forecast. What should we revisit?” | A review that keeps the original prediction alongside what happened. |

The local browser app lets you present the roadmap, review priorities, and work through launch checks. It reads the same records you use in the terminal. [Browser guide](playbook/local-ui.md)

![The oryx roadmap for fictional Atlas Workspace, with guided setup in Now, weekly digests in Next, and report exports in Later.](playbook/images/roadmap.png)

## Quick start

Install Git, Python 3.9 or later, and either Codex CLI or Claude Code. On Linux or WSL2, protected sessions need bubblewrap with working user namespaces. On macOS, they use `sandbox-exec`.

1. Clone this repository using GitHub’s **Code** button and open a terminal in the checkout.
2. Create your private workspace with your name. If you use a delivery tool, you can add `--delivery-system "Tool name"`.

   ```sh
   python3 tools/pm.py init-workspace --owner "Your name"
   ```

3. Start a protected session with your preferred client.

   | Client | Run from the checkout |
   | --- | --- |
   | Codex CLI | `python3 tools/pm.py agent codex` |
   | Claude Code | `python3 tools/pm.py agent claude` |

4. Trust the project hooks in your client. Tell oryx what you want to work on.

Your first request starts a walkthrough with oryx. You can share a source or explain the business in your own words.
Together you review customers, economics, the product portfolio, growth, and strategic trade-offs. You can leave questions open or say a topic does not apply.
If you’re a founder starting with an idea, your own account is enough to begin. Bring back what you learn and review what it changes.

Next, oryx asks about your role, day-to-day responsibilities, expectations and aspirations. You can review one point at a time or leave it open.
You can also map who you work with and how decisions happen. Oryx keeps the stakeholder map separate from your profile. [PM walkthrough](playbook/pm-context.md)

Step 3 covers the product as it works today. If you own a plugin, you still start with its parent product. Once you’ve reviewed the six topics, you can use the hub with questions open.

If you own part of that product, oryx offers an optional step 4 for your area. You can review it now, come back later, or skip it. Its findings go in a separate brief. [Product walkthrough](playbook/product-context.md)

## Make it yours

“Going forward, start each weekly review with decisions you need from me.” Say it once and oryx saves the rule in your private workspace. The rule takes priority for that part of the review. You can also change a brief template, add a confidence column to your roadmap, or keep a different view for leadership. [Workflow rules](playbook/overrides.md) · [Templates, fields, and views](playbook/customization.md)

## Placement

**Core** is the shared software. **Studio** is your own Git repository inside `studio/`. A protected session gives your agent write access to Studio and read access to core. Core updates and your work have separate Git histories.

| Location | What lives there |
| --- | --- |
| `studio/context/` | Company, PM, stakeholder and product context, sources, and meeting notes |
| `studio/workspace/` | Discovery briefs, experiments, planning comparisons, and launch work |
| `studio/customizations/` | Your standing rules, templates, fields, and views |
| `studio/README.md` · `studio/settings.json` | Your session handoff and local configuration |
| `playbook/` · `templates/` | Shared methods and starting points |
| `tools/` · `tests/` | Commands, browser app, workspace setup, and checks |
| `.agents/` · `.claude/` · `.codex/` · `.github/` | Agent skills, client configuration, and CI |

To resume on another machine, restore your private repository into `studio/`. You choose where to sync it. [Filing guide](playbook/filing.md) · [Git and remotes](playbook/git.md) · [Updates and recovery](playbook/updates.md)

For a walkthrough from a customer signal to a roadmap decision, start with the [worked example](playbook/opportunities.md#worked-example). For the rules that guide both agents, read the [project constitution](AGENTS.md).

## License

oryx was created by Nathan D’Mello and was previously named PM Hub. See the [proprietary license](LICENSE.md).
