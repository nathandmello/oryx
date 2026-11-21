# Get to know the PM

After the company walkthrough, help the PM describe their role as they practise it today. Start with what they already shared.

> Let’s set up your profile. What’s your role here?

If the PM already introduced themselves, pick up that thread. Ask one question, listen, and let their answer shape the next turn.

## Listen for five things

| Walkthrough topic | What to listen for |
| --- | --- |
| Role | Their title, team, and scope in their own words. A founder can describe the hats they wear. A leader can describe their remit across teams. |
| Responsibilities | The work they do, the decisions they make or influence, and any limits they confirm. A recent example can clarify a broad title. |
| Expectations | What others count on them for, who sets that expectation, and how success is recognised. Keep formal measures and informal expectations distinct. |
| Aspirations | The kind of work they would like more of, a skill they want to deepen, or a direction they are considering. They can pass. |
| Stakeholders | The people or teams they work with, reporting lines, and who recommends, decides, or needs to be consulted on a particular decision. |

A PM might say, “I coordinate releases and leadership sets priorities.” If their influence matters, ask where they come into that decision.
If they say they join *after* Billing priorities are set, preserve that boundary and its scope. Leave unmentioned activities and skills open.

Keep examples tied to the release or period the PM describes. Ask before treating a one-off as recurring.
Describe the work respectfully. Record an aspiration in the PM’s words. Coaching or career planning needs a later invitation.

Follow useful details the PM offers, such as where their time goes, customer access, strengths they name, or how they prefer feedback.
A success measure might be release predictability, customer adoption, or team development. Check what actually applies here.

Use the four areas of execution, customer insight, strategy, and influence to understand an unfamiliar responsibility. Local expectations and career paths vary.
The PM’s own account supplies their profile. Career frameworks can inform a follow-up question when it helps. [Ravi Mehta’s competencies](https://www.ravi-mehta.com/product-manager-skills/) · [Lenny Rachitsky’s career ladders](https://www.lennysnewsletter.com/p/product-management-career-ladders)

## Agree how to capture it

Ask how they would like to start. They can talk it through, write their own profile, or share an existing role brief.
Reuse relevant material already authorised. Offer a bounded public lookup or connected source when it addresses a real gap.
A job ladder describes published expectations. A PM or a team document can explain how those expectations apply here.

Agree on the purpose, exact sources and private destinations before gathering anything. Name any temporary review draft in the plan.
Seek fresh permission for additional sources or destinations. Keep chat-only details out of proposals, gaps, and records.

Use `context/pm/context.md` for the PM’s remit, responsibilities, expectations, aspirations, and volunteered working preferences.
Use the [stakeholder map](stakeholders.md) at `context/stakeholders/overview.md` for relationships. A role or team may be all the identification needed.

Keep formal reporting, collaboration, and decision authority separate. Establish each from the person’s account or a source they approve.
Keep personal judgments and inferred motives out of the map. Review any legacy profile notes with the PM before bringing them forward.

## Review one point at a time

Run `pm.py pm-onboarding status` for the current source plan, phase, revision, and gap selectors. Run commands for the PM.
With their agreement, use `status --pending` to resume the current draft or `status --gap REV/INDEX` to inspect one selected question.
Use the selector returned by current status.

Use `plan` with `purpose`, `sources`, and `destinations`. Call `approve` after they agree. Use the revision returned after each change.

Send changes as JSON on standard input. For example, propose this plan before gathering anything.

```json
{"revision":0,"purpose":"Capture how Billing priorities are set.","sources":["PM conversation"],"destinations":["context/pm/context.md"]}
```

For a finding, use `propose` with an approved `source_scope`, one source and one entry under the [routing contract](context.md#route-supplied-evidence).
Use `scope: pm` and `role`, `responsibilities`, `expectations`, or `aspirations` for the four profile topics.
Use `scope: stakeholder` for the map once its destination is agreed.

Show the proposed sentence, its source and destination. Keep its scope, timeframe and qualifications visible. If the sentence interprets an excerpt, show the excerpt too.

> I’d put this in your profile. “For Billing this quarter, I recommend priorities. Leadership makes the final call.” Does that capture your part?

Accept the exact wording they approve. Re-propose edits for review. Keep a disagreement attributed and unresolved.
If they decline retention, use `discard` with the current revision. This clears the pending draft without creating a gap.

Finish the capture round before a separate, PM-confirmed `set-remit` change. Preserve their existing profile and unrelated remit entries.

Use `defer` for a pending finding or `gap` for a material unknown. Agree on `question`, `why`, `next_action`, and `resume_when`.
Offer that step when the cue arrives and questions are welcome. Propose a sourced answer referencing the exact open question in `answers`.
After the PM approves that wording, call `resolve` with the question.

Use `finish` to close a capture round. These operations use the capture revision.

## Pause or move on

Use `onboarding status` for the current walkthrough topic. Review relevant existing facts with the PM once.
Use `onboarding review-topic` with the walkthrough revision, `stage: pm`, topic ID, outcome, and actual PM reply.
A reviewed topic can stay open or be inapplicable. The receipt records its disposition. Their answer enters the profile only through approved capture.

A pause preserves the current topic. After the stakeholder pass, follow the product stage shown by onboarding.

## Use the profile later

Read the relevant topic with `pm.py pm-profile --topic responsibilities` when the PM asks for help with their remit.
Use the topic that answers the request.
Use `pm.py pm-profile` to list older or handwritten sections. Open an agreed section with `pm-profile --section "<heading>"`.
Check with the PM before opening a legacy section that mixes topics. Keep each claim’s qualifications, source, and timeframe.

An interest they shared can shape a conversation when relevant. Ask before turning it into development work.
