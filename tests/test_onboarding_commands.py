"""Exercise the public dispatcher with an empty or partially reviewed Studio."""

import json
import subprocess
import sys
import unittest

import test_pm
import onboarding_review
from onboarding_fixtures import reviewed_studio


class OnboardingCommandTests(unittest.TestCase):
    setUp = test_pm.HubTests.setUp

    def cli(self, *args, data=None, ok=True):
        run = subprocess.run([sys.executable, str(self.root / "tools/pm.py"), *args], cwd=self.work,
                             input=json.dumps(data) if data is not None else None, capture_output=True, text=True)
        self.assertEqual(run.returncode == 0, ok, run.stdout + run.stderr)
        return json.loads(run.stdout)

    def test_roadmap_and_strategy_requests_return_to_the_current_topic(self):
        for args in (("roadmap",), ("action", "portfolio", "roadmap", "show"),
                     ("action", "strategy", "brief", "draft"), ("new", "strategy", "workspace/strategies/q4.md")):
            with self.subTest(args=args):
                result = self.cli(*args, ok=False)
                self.assertEqual(result["status"], "onboarding_required")
                self.assertEqual(result["onboarding"]["stage"], "company")
        self.assertFalse((self.work / "workspace/strategies/q4.md").exists())
        self.assertFalse((self.work / onboarding_review.FILE).exists())
        state = self.cli("onboarding", "status")
        self.assertEqual(self.cli("task-context", "Help me with Q4.")["onboarding"], state)
        while state["stage"] == "company":
            topic = state["walkthroughs"]["company"]["next_topic"]["id"]
            state = self.cli("onboarding", "review-topic", data={
                "stage": "company", "revision": state["revision"], "topic": topic,
                "outcome": "open", "pm_reply": "We covered this. I'd like to leave it open.",
            })
        self.assertEqual(state["stage"], "pm")
        self.assertFalse(state["stage_available"])
        self.assertEqual(self.cli("action", "portfolio", "roadmap", "show", ok=False)["onboarding"], state)
        self.assertFalse((self.work / "context/company/overview.md").exists())

    def test_unreadable_progress_holds_work_and_keeps_the_original_bytes(self):
        path = self.work / onboarding_review.FILE
        path.parent.mkdir(parents=True)
        path.write_bytes(b"broken walkthrough")
        state = self.cli("onboarding", "status")
        self.assertEqual(state["stage"], "repair")
        self.assertEqual(self.cli("roadmap", ok=False)["onboarding"], state)
        self.assertEqual(path.read_bytes(), b"broken walkthrough")

    def test_after_a_complete_pass_strategy_checks_its_own_prerequisite(self):
        reviewed_studio(self.root, self.work)
        activity = self.cli("task-context", "Help me with product strategy.")
        self.assertEqual(activity["activity_check"]["status"], "clarify_if_unknown")
        self.assertIn("company outcome", activity["activity_check"]["question_if_unclear"])
        self.assertNotIn("activity_check", self.cli("task-context", "Show the roadmap."))
