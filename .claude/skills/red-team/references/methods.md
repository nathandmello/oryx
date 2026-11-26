# Methods for PM red-team reviews

## Choose methods by the decision at stake

- **Brief or initiative.** Pair Assumption Audit with Pre-mortem for a proposed commitment. Use First Principles when the problem or priority is in doubt.
- **Company, product, or initiative context.** Pair Source Triangulation with Stakeholder Lens. Check unsupported claims, inherited commitments, and gaps that affect the reader.
- **Requirements or workflow.** Pair Edge Case Sweep with Stakeholder Lens or Failure Mode Analysis. Look for conflicting rules, missing states, and ambiguous acceptance criteria.
- **Experiment or readout.** Pair Assumption Audit with Falsification. Check whether the design or result supports the intended decision.
- **Roadmap, launch, or operating plan.** Pair Pre-mortem with Failure Mode Analysis. Check dependencies, incentives, trade-offs, and recovery.

For product bets, use the [PM framework](../../../../playbook/framework.md) to trace goal, customer problem, approach, and outcome. Check value, usability, feasibility, and viability with their owners.

## Check context and authority

Check inherited commitments, the exception owner, and the limits of any approval.

Compare material statements with the original passages clause by clause. Preserve actors, obligations, negation, conditions, exceptions, numbers, dates, and adjacent commitments or exclusions.

Cite original locations. Mark coverage as read, partial, or unavailable. Distinguish proposals and opinions from decisions. Keep a question open until evidence answers it.

Use the [filing test](../../../../playbook/filing.md) to identify the owning record and flag duplicate notes. Keep original evidence at its source. Link delivery records.

Before recommending a move, check incoming links and stable IDs. Use the [recoverable filing workflow](../../../../playbook/updates.md#convert-existing-work) for authorised moves and consolidation.

## Method and required output

### Assumption Audit

List what must be true for the recommendation to work. Mark explicit and implicit assumptions. For each key assumption, record the evidence for it and what breaks if it is false. Stress-test the least supported assumption with the highest decision impact.

### Pre-mortem

Assume the decision was made and the plan failed by a relevant date. Work backward to explain plausible causes. For each material cause, name the draft detail that makes it plausible, an early signal, and a prevention step.

### Red Team vs Blue Team

Make the strongest case against the proposal using a realistic counterexample or a competing option. Record that case before making the strongest defence the supplied evidence supports. Show which objections survive, where evidence is missing, and what evidence can change the judgment.

### Stakeholder Lens

Trace the work from the perspective of an affected user, operator, or decision owner. Identify their goal, burden, and missing information at a concrete step. Mark inferred needs as hypotheses. Use supplied evidence to support claims about real people.

### Edge Case Sweep and Failure Mode Analysis

For a sweep, walk through plausible boundary cases such as missing input, retries, or conflicting actions. Record each trigger, expected behaviour, and behaviour specified in the draft. For failure analysis, trace likely or severe failures through their dependencies. Record the cause, downstream effect, detection, and recovery. Anchor each gap in a rule, dependency, or missing state.

### First Principles and Source Triangulation

For First Principles, rebuild the recommendation from established facts and constraints. Compare it with the best plausible alternative, including the status quo when relevant. For Source Triangulation, trace key claims to their original evidence. Check scope, date, independence, and contrary evidence. Count repeated accounts of one source once.

### Falsification

Name evidence that can disprove the claim or distinguish a competing explanation. Check the hypothesis, comparison, guardrails, and decision rule. Verify that every arm can measure the primary outcome. For A/B tests, check assignment, exposure, telemetry, sample size, and stopping rules. In readouts, compare observed and intended allocation. Preserve inconclusive results and flag criteria changed after results.

## Apply an AI lens when the artifact makes AI claims

Check that each claim maps to a representative task, a baseline, and an evaluation criterion. Look for ordinary cases, costly edge cases, and differences across user groups or contexts. Check source fidelity, data exposure, human review, and fallback where relevant. For a launch, check the monitoring signal and the condition for stopping or rolling back.

## Rate decision impact

- **Blocker.** Proceeding now depends on resolving the issue or obtaining the missing evidence.
- **Material.** The issue can change the decision, scope, or safeguards. The next step can proceed with a stated condition or trade-off.
- **Watch.** A plausible risk merits a named signal or a later checkpoint.

An experiment claims that AI summaries reduce ticket resolution time. Its only measure is summary opens.

- **Blocker · Success metric.** Opens measure usage. The plan has no measure of resolution speed, so either outcome leaves the claim untested.
- **Next check.** Product and Analytics define time to resolution and a reopen-rate guardrail before launch. Keep opens as a diagnostic.

## Sources

- Assumptions, source quality, and competing explanations draw on the [UK Ministry of Defence Red Teaming Handbook](https://www.gov.uk/government/publications/a-guide-to-red-teaming). The pre-mortem uses [Gary Klein's project method](https://hbr.org/2007/09/performing-a-project-premortem).
- Experiment checks draw on [Microsoft Research's pre-experiment patterns](https://www.microsoft.com/en-us/research/articles/patterns-of-trustworthy-experimentation-pre-experiment-stage/).
- AI review draws on [OpenAI's evaluation guidance](https://developers.openai.com/api/docs/guides/evaluation-best-practices) and the [NIST Generative AI Profile](https://www.nist.gov/publications/artificial-intelligence-risk-management-framework-generative-artificial-intelligence).
