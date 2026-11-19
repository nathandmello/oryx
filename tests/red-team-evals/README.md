# Red-team quality benchmark

Use this benchmark after changes to the skill, review methods, model, or client. Score the review the PM receives.

Most cases are fictional. The public onboarding case uses a frozen paraphrase of the GitLab proposal. Its evaluation request assumes a pre-launch decision. [GitLab issue #246795](https://gitlab.com/gitlab-org/gitlab/-/work_items/246795)

## Set up the comparison

Run the PM Hub skill and the installed BMAD Advanced Elicitation skill in separate test checkouts. Use the BMAD revision printed by the case list. The pinned version includes the cold-reader workflow. [BMAD source](https://github.com/bmad-code-org/BMAD-METHOD/tree/e435a22574fe55722841086e5566420178b98df3/skills/core-tools/bmad-advanced-elicitation)

Use the same client, model, reasoning setting, time limit, source access, and reviewer capacity for both arms. Give neither arm drafting history, the rubric, or the other arm's output. Use a new session for each run. Record the settings and which isolation the logs show.

A matched same-session fallback measures fallback behaviour only. Use working cold readers in both arms for the comparison scores. If a tool fails before producing a review, fix the harness and repeat both arms for that trial.

## Collect reviews

1. List the cases. Render the exact same prompt for both arms of each comparison case.
2. Invoke the assigned skill by name. Supply the prompt and point it to the frozen artifact block. Capture the first review before any correction or approval.
3. Run at least two matched trials for every comparison case. Alternate which arm runs first.
4. Run the PM workflow cases at least once with the PM Hub skill. Use the setup command for each case.
5. Confirm the artifact bytes are unchanged. Keep the outputs and any workflow logs for grading.

```sh
mkdir -p .generated
python3 tools/pm.py eval-red-team fingerprint > .generated/red-team-inputs.json
python3 tools/pm.py eval-red-team list
python3 tools/pm.py eval-red-team setup pm-cold-reviewer
python3 tools/pm.py eval-red-team prompt experiment-proxy
python3 tools/pm.py eval-red-team rubric experiment-proxy
```

Save the fingerprint before collecting reviews. It records the listed skill, guidance, hook, and benchmark files and the pinned BMAD revision.

## Grade blind

Assign anonymous labels to the outputs before giving them to the grader. Remove identifiers that name the arm. Preserve the findings and methods. Give the grader the case, rubric, output, and observations needed to check actions such as waiting. Keep the mapping private until grades are fixed.

Give credit for an explicit finding or action that meets the criterion. Accept equivalent wording. Require text or a logged action to support each grade. Record one short reason per grade beside the original review. Treat silence, invented facts, and generic advice as misses when the criterion requires specifics.

After grading, replace anonymous labels with `candidate` and `bmad`. Save scores as a JSON object keyed by case ID. Each value is a list of trial objects with one boolean per criterion per arm. PM workflow trials use only `candidate`.

This example shows one trial. Supply all cases and their required repeats when scoring.

```json
{
  "experiment-proxy": [
    {
      "candidate": {"proxy": true, "comparison": true, "threshold": true, "decision": true},
      "bmad": {"proxy": true, "comparison": true, "threshold": false, "decision": true}
    }
  ]
}
```

```sh
python3 tools/pm.py eval-red-team score .generated/red-team-grades.json \
  --fingerprint .generated/red-team-inputs.json
```

The candidate must pass every required criterion in each trial. It must earn at least 85% per case and match or exceed BMAD per comparison case. The command exits with status 1 for a missed gate, incomplete comparison, or lower score.

Scoring with a fingerprint rejects changed inputs. Scoring without one displays the saved grades and marks the input version unverified.

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
