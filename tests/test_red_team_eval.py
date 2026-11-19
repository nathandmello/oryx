"""Check the benchmark plumbing without calling a model or grading its replies."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import red_team_eval as benchmark


class RedTeamBenchmarkTests(unittest.TestCase):
    def setUp(self):
        manifest = benchmark.load_manifest()
        self.cases = manifest["cases"]
        self.assertRegex(manifest["bmad_revision"], r"^[0-9a-f]{40}$")
        self.grades = {}
        for case_id, case in self.cases.items():
            self.assertTrue(case["criteria"])
            self.assertTrue(set(case["gates"]) <= case["criteria"].keys())
            arms = ("candidate", "bmad") if case.get("compare", True) else ("candidate",)
            self.grades[case_id] = [
                {arm: dict.fromkeys(case["criteria"], True) for arm in arms}
                for _ in arms
            ]

    def test_prompt_includes_sources_and_excludes_grading_criteria(self):
        case = self.cases["context-provenance"]
        prompt = benchmark.render_prompt(case)
        self.assertIn(case["request"], prompt)
        self.assertIn(case["artifact"], prompt)
        self.assertIn(case["sources"], prompt)
        self.assertNotIn(case["criteria"]["provenance"], prompt)

    def test_cold_prompt_keeps_the_drafting_prelude_out(self):
        case = self.cases["pm-cold-reviewer"]
        self.assertIn("PRIVATE_DRAFT_482", case["setup"])
        self.assertNotIn("PRIVATE_DRAFT_482", benchmark.render_prompt(case))

    def test_complete_matching_grades_pass(self):
        results = benchmark.score(self.cases, self.grades)
        self.assertTrue(all(not misses for _, _, misses in results.values()))
        self.assertEqual(results["pm-method-choice"][0], {"candidate": 3})

    def test_one_paired_trial_cannot_establish_parity(self):
        self.grades["experiment-readout"].pop()
        results = benchmark.score(self.cases, self.grades)
        self.assertIn("parity needs at least two matched trials", results["experiment-readout"][2])

    def test_required_miss_fails_despite_matching_bmad(self):
        trial = self.grades["experiment-proxy"][0]
        trial["candidate"]["proxy"] = trial["bmad"]["proxy"] = False
        results = benchmark.score(self.cases, self.grades)
        self.assertEqual(results["experiment-proxy"][2], ["trial 1 missed proxy"])

    def test_falling_behind_bmad_fails_even_when_absolute_score_passes(self):
        self.grades["experiment-proxy"][0]["candidate"]["threshold"] = False
        results = benchmark.score(self.cases, self.grades)
        self.assertEqual(results["experiment-proxy"][2], ["candidate below BMAD"])

    def test_matching_low_scores_fail_the_absolute_floor(self):
        for trial in self.grades["experiment-proxy"]:
            trial["candidate"]["threshold"] = trial["bmad"]["threshold"] = False
        results = benchmark.score(self.cases, self.grades)
        self.assertEqual(results["experiment-proxy"][2], ["candidate below 85%"])

    def test_grader_rejects_missing_and_nonboolean_criteria(self):
        grades = self.grades["experiment-proxy"][0]["candidate"]
        del grades["threshold"]
        with self.assertRaisesRegex(ValueError, "every rubric criterion"):
            benchmark.score(self.cases, self.grades)
        grades["threshold"] = 1
        with self.assertRaisesRegex(ValueError, "must be true or false"):
            benchmark.score(self.cases, self.grades)

    def test_cli_distinguishes_matching_stale_and_unrecorded_inputs(self):
        command = [sys.executable, str(benchmark.ROOT / "tools/pm.py"), "eval-red-team"]
        with tempfile.TemporaryDirectory() as directory:
            grades_path = Path(directory) / "grades.json"
            grades_path.write_text(json.dumps(self.grades), encoding="utf-8")
            fingerprint_path = Path(directory) / "inputs.json"
            recorded = subprocess.run([*command, "fingerprint"], capture_output=True, text=True, check=True)
            fingerprint_path.write_text(recorded.stdout, encoding="utf-8")

            scoring = [*command, "score", str(grades_path)]
            verified = subprocess.run([*scoring, "--fingerprint", str(fingerprint_path)],
                                      capture_output=True, text=True, check=True)
            self.assertIn("input fingerprint matches): PASS", verified.stdout)
            archived = subprocess.run(scoring, capture_output=True, text=True, check=True)
            self.assertIn("input version unverified): PASS", archived.stdout)

            changed = json.loads(recorded.stdout)
            changed["files"][".agents/skills/red-team/SKILL.md"] = "0" * 64
            fingerprint_path.write_text(json.dumps(changed), encoding="utf-8")
            rejected = subprocess.run([*scoring, "--fingerprint", str(fingerprint_path)],
                                      capture_output=True, text=True)
            self.assertEqual(rejected.returncode, 1)
            self.assertIn("recorded benchmark inputs differ", rejected.stdout)
            self.assertNotIn("PASS", rejected.stdout)

    def test_native_startup_inputs_are_bound_to_fingerprint(self):
        command = [sys.executable, str(benchmark.ROOT / "tools/pm.py"), "eval-red-team", "fingerprint"]
        result = subprocess.run(command, capture_output=True, text=True, check=True)
        files = json.loads(result.stdout)["files"]
        startup = {".claude/settings.json", ".codex/config.toml", ".codex/hooks.json", "tools/hook.py", "tools/pm.py"}
        self.assertTrue(startup <= files.keys())

    def test_context_suite_uses_its_own_cases_and_fingerprint(self):
        suite_name = "context-guardrails"
        manifest_path = benchmark.SUITES[suite_name]
        cases = benchmark.load_manifest(benchmark.ROOT / manifest_path)["cases"]
        command = [sys.executable, str(benchmark.ROOT / "tools/pm.py"), "eval-red-team", "--suite", suite_name]
        grades = {name: [{"candidate": dict.fromkeys(case["criteria"], True)}] for name, case in cases.items()}
        with tempfile.TemporaryDirectory() as directory:
            scores_path = Path(directory) / "grades.json"
            scores_path.write_text(json.dumps(grades), encoding="utf-8")
            fingerprint_path = Path(directory) / "inputs.json"
            recorded = subprocess.run([*command, "fingerprint"], capture_output=True, text=True, check=True)
            self.assertIn(manifest_path, json.loads(recorded.stdout)["files"])
            fingerprint_path.write_text(recorded.stdout, encoding="utf-8")

            scoring = [*command, "score", str(scores_path), "--fingerprint", str(fingerprint_path)]
            checked = subprocess.run(scoring, capture_output=True, text=True, check=True)
            self.assertIn("context-distorted-draft: candidate 5/5 (pass)", checked.stdout)
            self.assertIn("context-approved-pilot: candidate 3/3 (pass)", checked.stdout)

            grades["context-distorted-draft"][0]["candidate"]["authority"] = False
            scores_path.write_text(json.dumps(grades), encoding="utf-8")
            rejected = subprocess.run(scoring, capture_output=True, text=True)
            self.assertEqual(rejected.returncode, 1)
            self.assertIn("trial 1 missed authority", rejected.stdout)

    def test_context_section_prompts_hide_reference_routes_and_rubrics(self):
        manifest = benchmark.ROOT / benchmark.SUITES["context-sections"]
        cases = benchmark.load_manifest(manifest)["cases"]
        for case_id, case in cases.items():
            with self.subTest(case=case_id):
                prompt = benchmark.render_prompt(case)
                self.assertIn(case["artifact"], prompt)
                self.assertIn("name a task or decision that calls for it", prompt)
                for number, source in enumerate(case["sources"], 1):
                    self.assertIn(f"S{number}. {source['title']}", prompt)
                    self.assertIn(source["url"], prompt)
                    self.assertIn(source["summary"], prompt)
                for entry in case["capture"]["entries"]:
                    if "lead" in entry:
                        self.assertNotIn(entry["lead"], prompt)
                self.assertTrue(set(case["gates"]) <= case["criteria"].keys())
                for criterion in case["criteria"].values():
                    self.assertNotIn(criterion, prompt)
