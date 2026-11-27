"""Render blind review cases and score paired grades for the red-team skill."""

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = "tests/red-team-evals/cases.json"
MANIFEST = ROOT / MANIFEST_PATH
SUITES = {
    "core": MANIFEST_PATH,
    "context-guardrails": "tests/red-team-evals/context-guardrails.json",
    "context-sections": "tests/red-team-evals/context-sections.json",
}
INPUT_FILES = (
    "AGENTS.md",
    "CLAUDE.md",
    "README.md",
    ".claude/settings.json",
    ".codex/config.toml",
    ".codex/hooks.json",
    ".agents/skills/red-team/SKILL.md",
    ".agents/skills/red-team/references/methods.md",
    ".claude/skills/red-team/SKILL.md",
    ".claude/skills/red-team/references/methods.md",
    "playbook/brief-review.md",
    "playbook/context.md",
    "playbook/filing.md",
    "playbook/framework.md",
    "playbook/opportunities.md",
    "playbook/updates.md",
    "playbook/working.md",
    ".agents/skills/ingest-context/SKILL.md",
    ".claude/skills/ingest-context/SKILL.md",
    "tests/red-team-evals/README.md",
    "tools/context_capture.py",
    "tools/hook.py",
    "tools/pm.py",
    "tools/records.py",
    "tools/red_team_eval.py",
    "src/oryx/cli/command.py",
    "src/oryx/adapters/host_hooks.py",
    "src/oryx/workspace/records.py",
    "src/oryx/capabilities/context_capture.py",
)
MINIMUM_PERCENT = 85


def register(commands):
    parser = commands.add_parser("eval-red-team", help="run the red-team review benchmark")
    parser.add_argument("--suite", choices=SUITES, default="core")
    actions = parser.add_subparsers(dest="eval_action", required=True)
    actions.add_parser("list", help="list the benchmark cases")
    actions.add_parser("setup", help="print case setup for the test operator").add_argument("case")
    actions.add_parser("prompt", help="print a case without its grading rubric").add_argument("case")
    actions.add_parser("rubric", help="print the judge's criteria").add_argument("case")
    actions.add_parser("fingerprint", help="record the inputs before collecting reviews")
    scoring = actions.add_parser("score", help="score blind grades after unblinding")
    scoring.add_argument("grades", type=Path)
    scoring.add_argument("--fingerprint", type=Path, help="check the recorded inputs against this checkout")


def load_manifest(path=MANIFEST):
    return json.loads(path.read_text(encoding="utf-8"))


def input_fingerprint(manifest, manifest_path, manifest_bytes):
    files = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in INPUT_FILES}
    files[manifest_path] = hashlib.sha256(manifest_bytes).hexdigest()
    fingerprint = {"files": files}
    if "baseline_revision" in manifest:
        fingerprint["baseline_revision"] = manifest["baseline_revision"]
    return fingerprint


def render_prompt(case):
    sources = case["sources"]
    parts = [case["request"]]
    if isinstance(sources, list):
        parts.append(
            "Apply oryx's section rules. Give each proposed section as a heading with a one-line lead beneath it. "
            "Say what the section covers and name a task or decision that calls for it."
        )
        sources = "\n\n".join(
            f"S{number}. {source['title']} ({source['date']}, {source['location']}).\n"
            f"Frozen paraphrase: {source['summary']}\n{source['url']}"
            for number, source in enumerate(sources, 1)
        )
    parts.extend([
        "Treat the supplied material as a PM decision artifact. Use only the supplied evidence. Leave the artifact unchanged.",
        f"## Frozen artifact\n\n{case['artifact']}",
        f"## Supplied sources\n\n{sources or 'None supplied.'}",
    ])
    return "\n\n".join(parts)


def grade_review(case_id, arm, grades, criteria):
    if not isinstance(grades, dict) or grades.keys() != criteria.keys():
        raise ValueError(f"{case_id}: {arm} needs one grade for every rubric criterion")
    for criterion, grade in grades.items():
        if type(grade) is not bool:
            raise ValueError(f"{case_id}: {arm} grade for {criterion} must be true or false")
    return sum(grades.values())


def score(cases, grades):
    if not isinstance(grades, dict) or grades.keys() != cases.keys():
        raise ValueError("Grades need exactly the case IDs in the benchmark")

    results = {}
    for case_id, case in cases.items():
        trials = grades[case_id]
        paired = case.get("compare", True)
        expected_arms = {"candidate", "baseline"} if paired else {"candidate"}
        if not isinstance(trials, list) or not trials:
            raise ValueError(f"{case_id}: supply a nonempty list of graded trials")

        totals = dict.fromkeys(expected_arms, 0)
        misses = []
        criteria = case["criteria"]
        for index, trial in enumerate(trials, 1):
            if not isinstance(trial, dict) or trial.keys() != expected_arms:
                raise ValueError(f"{case_id}: trial {index} needs {', '.join(sorted(expected_arms))}")
            for arm, arm_grades in trial.items():
                totals[arm] += grade_review(case_id, arm, arm_grades, criteria)
            for gate in case["gates"]:
                if not trial["candidate"][gate]:
                    misses.append(f"trial {index} missed {gate}")

        possible = len(trials) * len(criteria)
        if paired and len(trials) < 2:
            misses.append("parity needs at least two matched trials")
        if totals["candidate"] * 100 < possible * MINIMUM_PERCENT:
            misses.append(f"candidate below {MINIMUM_PERCENT}%")
        if paired and totals["candidate"] < totals["baseline"]:
            misses.append("candidate below baseline")
        results[case_id] = (totals, possible, misses)
    return results


def run(args):
    manifest_path = SUITES[args.suite]
    manifest_bytes = (ROOT / manifest_path).read_bytes()
    manifest = json.loads(manifest_bytes)
    cases = manifest["cases"]
    if args.eval_action == "fingerprint":
        print(json.dumps(input_fingerprint(manifest, manifest_path, manifest_bytes), indent=2, sort_keys=True))
        return 0

    if args.eval_action == "list":
        if "baseline_revision" in manifest:
            print(f"Oryx baseline revision {manifest['baseline_revision']}")
        for case_id, case in cases.items():
            print(f"{case_id} ({'comparison' if case.get('compare', True) else 'PM workflow'})")
        return 0

    if args.eval_action == "score":
        label = "Saved red-team grades (input version unverified)"
        if args.fingerprint:
            recorded = json.loads(args.fingerprint.read_text(encoding="utf-8"))
            if recorded != input_fingerprint(manifest, manifest_path, manifest_bytes):
                raise ValueError("The recorded benchmark inputs differ from this checkout")
            label = "Red-team benchmark (input fingerprint matches)"
        grades = json.loads(args.grades.read_text(encoding="utf-8"))
        results = score(cases, grades)
        for case_id, (totals, possible, misses) in results.items():
            marks = ", ".join(f"{arm} {totals[arm]}/{possible}" for arm in sorted(totals))
            outcome = ", ".join(misses) if misses else "pass"
            print(f"{case_id}: {marks} ({outcome})")
        passed = all(not misses for _, _, misses in results.values())
        print(f"{label}: {'PASS' if passed else 'FAIL'}.")
        return int(not passed)

    if args.case not in cases:
        raise ValueError(f"Unknown red-team eval case {args.case!r} in suite {args.suite!r}")
    case = cases[args.case]
    if args.eval_action == "setup":
        print(case.get("setup", "Use the matched settings described in the benchmark guide."))
    elif args.eval_action == "prompt":
        print(render_prompt(case))
    else:
        print(case["request"])
        for criterion, description in case["criteria"].items():
            suffix = " (required)" if criterion in case["gates"] else ""
            print(f"{criterion}{suffix}: {description}")
    return 0
