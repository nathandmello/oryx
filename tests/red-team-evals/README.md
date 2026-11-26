# Red-team quality benchmark

Use this benchmark after changes to the skill, review methods, model, or client. Score the review the PM receives.

Most cases are fictional. The public onboarding case uses a frozen paraphrase of the GitLab proposal. Its evaluation request assumes a pre-launch decision. [GitLab issue #246795](https://gitlab.com/gitlab-org/gitlab/-/work_items/246795)

## Set up the comparison

Compare the current oryx red-team skill with the earlier oryx revision printed by `list`.
Create a separate local worktree at that revision with `git worktree add --detach <directory> <revision>`. Keep it clean during testing.

Use the same client, model, reasoning setting, time limit, source access, and reviewer capacity for both arms. Give neither arm drafting history, the rubric, or the other arm's output. Use a new session for each run. Record the settings and which isolation the logs show.

A matched same-session fallback measures fallback behaviour only. Use working cold readers in both arms for the comparison scores. If a tool fails before producing a review, fix the harness and repeat both arms for that trial.

## Collect reviews

1. Render each comparison prompt in the candidate checkout. Use that same prompt for both arms.
2. Invoke the red-team skill in each checkout. Supply the frozen artifact. Capture the first review before any correction or approval.
3. Run at least two matched trials for every comparison case. Alternate which arm runs first.
4. Run the PM workflow cases at least once with the oryx skill. Use the setup command for each case.
5. Confirm the artifact bytes are unchanged. Keep the outputs and any workflow logs for grading.

```sh
mkdir -p .generated
python3 tools/pm.py eval-red-team fingerprint > .generated/red-team-inputs.json
python3 tools/pm.py eval-red-team list
python3 tools/pm.py eval-red-team setup pm-cold-reviewer
python3 tools/pm.py eval-red-team prompt experiment-proxy
python3 tools/pm.py eval-red-team rubric experiment-proxy
```

Save the fingerprint before collecting reviews. It records the candidate inputs and the expected baseline revision for a paired suite.

## Grade blind

Assign anonymous labels to the outputs before giving them to the grader. Remove identifiers that name the arm. Preserve the findings and methods. Give the grader the case, rubric, output, and observations needed to check actions such as waiting. Keep the mapping private until grades are fixed.

Give credit for an explicit finding or action that meets the criterion. Accept equivalent wording. Require text or a logged action to support each grade. Record one short reason per grade beside the original review. Treat silence, invented facts, and generic advice as misses when the criterion requires specifics.

After grading, replace anonymous labels with `candidate` and `baseline`. Save scores as a JSON object keyed by case ID. Each value is a list of trial objects with one boolean per criterion per arm. PM workflow trials use only `candidate`.

This example shows one trial. Supply all cases and their required repeats when scoring.

```json
{
  "experiment-proxy": [
    {
      "candidate": {"proxy": true, "comparison": true, "threshold": true, "decision": true},
      "baseline": {"proxy": true, "comparison": true, "threshold": false, "decision": true}
    }
  ]
}
```

```sh
python3 tools/pm.py eval-red-team score .generated/red-team-grades.json \
  --fingerprint .generated/red-team-inputs.json
```

The candidate must pass every required criterion in each trial. It must earn at least 85% per case and match or exceed the baseline for each comparison case. The command exits with status 1 for a missed gate, incomplete comparison, or lower score.

Scoring with a fingerprint rejects changed inputs. Without a fingerprint, the command marks the input version unverified.
Score archived runs in the oryx revision that supplied their cases and comparison arm.

Record the tested client, model, and isolation with the results. Repeat for any other client or model covered by a parity claim. The score describes these cases and settings. Use a fresh case to check a fix prompted by a benchmark miss.

## Context guardrails

The context suite tests a draft that drops source constraints and a draft with a valid, bounded exception. Both cases test the candidate only. Use the same suite option for fingerprinting, prompts, rubrics, and scoring. [PM Hub 0.2.0 changes](https://github.com/nathandmello/pm-hub/pull/1)

```sh
python3 tools/pm.py eval-red-team --suite context-guardrails list
python3 tools/pm.py eval-red-team --suite context-guardrails fingerprint > .generated/context-inputs.json
python3 tools/pm.py eval-red-team --suite context-guardrails prompt context-distorted-draft
python3 tools/pm.py eval-red-team --suite context-guardrails rubric context-distorted-draft
python3 tools/pm.py eval-red-team --suite context-guardrails score .generated/context-grades.json \
  --fingerprint .generated/context-inputs.json
```

## Real-world context sections

Four frozen source packets cover annual GMV, renewal eligibility, storefront rules, and API versions.
The cases contain source links and paraphrases. Treat the supplied dates and scope as the evidence for each scenario.

Use the capture tests to replay reference routes through `route-context`. They check previews, leads, citations, replays, and rejection of a wrong source.
Grade the agent's decisions in separate sessions. Give the reviewer the prompt, which includes oryx's section rule. Keep reference routes and criteria with the grader.

```sh
python3 -m unittest discover -s tests -p test_pm.py -k test_real_world_context
python3 tools/pm.py eval-red-team --suite context-sections list
python3 tools/pm.py eval-red-team --suite context-sections fingerprint > .generated/context-sections-inputs.json
python3 tools/pm.py eval-red-team --suite context-sections prompt shopify-annual-gmv
python3 tools/pm.py eval-red-team --suite context-sections rubric shopify-annual-gmv
python3 tools/pm.py eval-red-team --suite context-sections score .generated/context-sections-grades.json \
  --fingerprint .generated/context-sections-inputs.json
```

Use candidate-only grades for this suite. Record the model and client for each decision review.
