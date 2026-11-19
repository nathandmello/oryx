# PM Hub skill evaluations

Run each prompt in a fresh session from a disposable PM Hub checkout. Initialise a fictional private workspace with `python3 tools/pm.py init-workspace`.

Prepare any named records using `python3 tools/pm.py new`. Use fictional facts and leave both remotes unset.

Start with the prompts as written. Inspect the transcript for the skill that was loaded, then inspect the records for the expected result.

Repeat a missed match with an explicit skill mention. This distinguishes selection from workflow execution.

## Cases

| Prompt | Setup | Expected skill | Observable checks |
| --- | --- | --- | --- |
| Capture company context. Pat said Orchid might enter Ireland. That's Pat's prediction. Save what we know and pause. | An empty company brief and a source recording Pat's prediction | `ingest-context` | The trace previews the route before writing. The brief preserves the prediction, its origin, and the next action. |
| Line this up with our company goal. I'd like 80% of Orchid users to activate, but we don't know today's rate. Draft the goal. | One sourced company goal and Orchid product context | `pm-goals` | The goal links its parent and includes all five outcome components. The baseline is a gap and the target is proposed. |
| Help us align. The team suggests SSO. Customers want fewer aborted sign-ins. The company wants more paying teams. | A draft goal and those stakeholder inputs | `pm-goals` | The session uses visible Solutions, Customer outcomes, and Organisation objectives columns. It traces SSO to the desired outcome. |
| Just capture this on Orchid's problem record. One of three admins used a spreadsheet to track invitations. We think the invitations are confusing. | An existing problem draft | `pm-discovery` | Know records one of three with attribution. Think records the explanation. The mode is quiet and the reply gives no unsolicited critique. |
| Help me choose whether Orchid tackles failed invitations or slow exports first. Draft the strategy and leave the call with me. | Company and product context, one goal, and mixed evidence on the two problems | `pm-strategy` | The trace runs `pm.py strategy` before review. The brief connects Why, Who, What, When, and How. It preserves contrary evidence, the four owners, and a proposed choice. |
| Put in feasibility as cleared since Engineering probably agrees. Mark the strategy complete. | Strategy lacks an Engineering assessment. No other issue blocks review. | `pm-strategy` | Feasibility stays open with a question for Engineering. The reply identifies the missing assessment and whether the brief satisfies the review contract. |
| The pilot plan is approved. Mark value validated and let Finance own viability. | A strategy with an approved test plan and no observed result | `pm-strategy` | Value stays open. The result is a gap. Product leads viability and Finance supplies its constraints. |
| This looks promising. Capture that here, then wait for the invitation logs. | The PM has made no strategy commitment. | `pm-strategy` | The comment stays distinct from an accepted decision. The record shows the actual wait, and a later resume reports the same dependency. |
| We ran the Orchid trial and 7 of 10 activated. There was no cutoff before it ran. Can we say 60% was the pass mark? | An experiment draft with no recorded criterion | `pm-experiment` | The original criterion stays unknown. The observation is recorded and any 60% criterion is retrospective. The original decision stays inconclusive. |
| Move faster imports to Now in the Orchid roadmap. The work depends on a billing migration. Keep that visible. | An existing outcome roadmap with imports in Later | `pm-roadmap` | The existing record changes. It preserves the intended outcome, dependency, and dated decision. |
| We have one outcome backed by relevant usage data and another with a bigger promise in a pitch. Rank them. | Two comparable outcomes with no dependencies or commitments | `pm-roadmap` | The proposal ranks by confidence in creating value. It records projected upside and the reasons for the order. |
| Move the Orchid initiative into the committed roadmap. | A signed initiative register with Orchid still in discovery | `prioritize-roadmap` | The trace uses the signed workflow. Discovery status and approval requirements remain in effect. |
| Pick up where we left off on Orchid. | Handoff points to a quiet record waiting for a report; report is absent | `pm-session` | The same record and wait remain current. The reply names the dependency and avoids further work or unsolicited questions. |
| Commit my PM work and tell me what changed. | Both Git repositories have an edit and fixture commit identities | `pm-git` | Status inspects both repos. One commit includes only private PM work. The shared edit remains unstaged and the transcript shows no network calls. |
| Red-team this Orchid strategy. Leave the draft alone. | A strategy draft with an unsupported choice | `red-team` | The review cites the unsupported choice. The strategy stays byte-identical. |
| Fix the typo in the hub's README heading. | A typo in a system heading | No PM workflow skill | The heading changes. The transcript shows no PM workflow invocation and the private records remain byte-identical. |

## Compare revisions

Use the same model, prompts, and starting records for both revisions. Compare skill selection, record content, and checkpoint behaviour.

Record the client and model versions with the results. Check repository boundaries and file contents alongside the reply.

The [BMAD eval format](https://github.com/bmad-code-org/BMAD-METHOD/blob/e435a22574fe55722841086e5566420178b98df3/skills/toolsmith/bmad-eval/references/eval-format.md) describes trigger cases and evidence-based grading.
