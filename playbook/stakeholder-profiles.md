# Stakeholder profiles

A private profile helps a PM prepare for recurring conversations with one person. It can start with one observation.
After product context and any chosen area walkthrough, the PM can start, skip, or return later. They can also ask directly.
Use `/pm context stakeholder-profile capture` for guided setup or updates and `/pm context stakeholder-profile coach` for preparation and rehearsal.

## Choose where a finding belongs

| Question | Record |
| --- | --- |
| Who works with whom? Who approves this specific decision? | The [stakeholder map](stakeholders.md) holds scoped relationships and authority. |
| What does this person ask for when reviewing a proposal? Which evidence has helped before? | The profile holds reviewed observations about working with this person. |
| Where do they stand on this rollout? Who needs a follow-up before Tuesday? | Use the initiative's existing context or work record, with its scope and date. |

“We agreed to postpone Tuesday’s pilot” can establish a position on that pilot. A recurring communication preference needs evidence of its own.
Repeated mentions of the same meeting trace back to one event.

## Build the profile together

Agree which identified person and sources to use. The PM can talk, write a line themselves, or share an approved document.
Use the [profile workflow](../.agents/skills/stakeholder-profiles/SKILL.md). Ask one question and work from the answer.

| Topic | What might help a future conversation |
| --- | --- |
| Role and relationships | Where the PM works with this person and for how long, if known. Link the map for decision rights. |
| Goals and concerns | Outcomes or risks the person actually named, with the product, decision or period they described. |
| Evidence | A specific comparison, customer account or operational measure they asked for or used. |
| Communication | A stated preference for a format or channel. Quote an actual phrase when permitted and useful. |
| History | A prior agreement, disagreement, or change of mind, including the evidence and circumstances. |

Separate observed behaviour, attributed reports and the PM's volunteered hypotheses. Clarify any claim of an enduring pattern.
Keep uncertain, work-related interpretations explicitly attributed when the PM wants them retained. Respect anything they want to keep in chat.
Guesses about private motives, identities or personal lives have no place in a working profile.

## Review one change

Use `pm.py stakeholder-profile list` with a name, alias or current role. Confirm any namesake with the PM.
Use `pm.py stakeholder-profile show ID --topic TOPIC` to inspect relevant accepted entries. Use the stable ID for every change.

Use `pm.py stakeholder-profile preview` with one proposed observation and its source.
Send JSON on standard input. For example, a PM supplied this quote from a Billing review.

```json
{
  "id": "jo-service", "name": "Jo Diaz", "role": "Service lead",
  "topic": "communication", "kind": "reported", "subject": "product/billing",
  "scope": "Billing pilot reviews", "source": "PM account of pilot review, opening question",
  "excerpt": "Could we start with any escalations that have no owner?",
  "wording": "Jo asked to see unowned escalations first at the Billing pilot review."
}
```

Show the exact wording, person, destination and source. The PM can accept, edit, see the evidence, or pass.
For a subscriber finding, preserve its `evidence` reference and original attribution. Include the fresh `source_read` when the original lives outside Studio.

Use `subject` for the relevant product, area or initiative. A general practice needs evidence that it applies across that scope.
After approval, send `review` and `approved_wording` to `pm.py stakeholder-profile accept`. Use the entire returned review and the exact accepted sentence.

Preview edits again. For a correction, identify the specific claim it replaces and preserve any history that still applies.
Recheck evidence after a new decision, a role change, a PM correction, or an interaction that contradicts the profile.

Use `aliases` for confirmed alternative names. Confirm `update_identity` and review a sourced change when a person's name or role changes.
Keep the same ID. Earlier names still resolve. A new role prompts a fresh check of previous observations.
Use `review_by` when a claim has an agreed review date.

## Apply one observation

If Jo asked about escalation coverage at the last pilot review, check whether this launch has an agreed route.
For a rehearsal, connect each possible question to its source. Keep imagined responses in chat.
A follow-up about the same draft can retain its audience. A different task, session or scope needs its own context.

## Shared Studio compatibility

Each accepted profile lives under `context/stakeholders/profiles/`. Its private identity directory contains names, roles, aliases and revisions.
Update both clients before sharing these records. After a restore or for older profiles, run `pm.py stakeholder-profile index --preview`.
After review, `pm.py stakeholder-profile index` rebuilds the directory from the original records. The same command repairs a stale directory.
