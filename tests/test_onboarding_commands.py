"""Exercise the public dispatcher with an empty or partially reviewed Studio."""

import json
import subprocess
import sys
import unittest

import test_pm
import company_onboarding
import context_capture
import ingestion_signals
import onboarding_review
from onboarding_fixtures import review_current_topic, reviewed_studio


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
        self.assertTrue(state["stage_available"])
        self.assertEqual(state["walkthroughs"]["pm"]["next_topic"]["id"], "role")
        self.assertIn("pm-onboarding", state["pm_updates"])
        self.assertEqual(self.cli("action", "portfolio", "roadmap", "show", ok=False)["onboarding"], state)
        self.assertEqual(self.cli("task-context", "Continue.")["onboarding"], state)
        self.assertFalse((self.work / "context/company/overview.md").exists())

    def test_unreadable_progress_holds_work_and_keeps_the_original_bytes(self):
        path = self.work / onboarding_review.FILE
        path.parent.mkdir(parents=True)
        path.write_bytes(b"broken walkthrough")
        state = self.cli("onboarding", "status")
        self.assertEqual(state["stage"], "repair")
        self.assertNotIn("company_updates", state)
        self.assertEqual(self.cli("roadmap", ok=False)["onboarding"], state)
        self.assertEqual(path.read_bytes(), b"broken walkthrough")

    def test_damaged_company_capture_does_not_hide_pm_but_damaged_current_capture_holds(self):
        while onboarding_review.status(self.work)["stage"] == "company":
            review_current_topic(self.work)
        company = self.work / company_onboarding.FILE
        company.write_bytes(b"broken company capture")
        state = self.cli("onboarding", "status")
        self.assertEqual(state["stage"], "pm")
        self.assertEqual(state["company_phase"], "unavailable")
        self.assertIn("pm_updates", state)
        profile = self.work / company_onboarding.PM_FILE
        profile.write_bytes(b"broken PM capture")
        state = self.cli("task-context", "Continue setup.")["onboarding"]
        self.assertEqual(state["stage"], "repair")
        self.assertEqual(self.cli("roadmap", ok=False)["onboarding"], state)
        self.assertEqual(profile.read_bytes(), b"broken PM capture")
        self.assertEqual(company.read_bytes(), b"broken company capture")

    def test_after_a_complete_pass_strategy_checks_its_own_prerequisite(self):
        reviewed_studio(self.root, self.work)
        activity = self.cli("task-context", "Help me with product strategy.")
        self.assertEqual(activity["activity_check"]["status"], "clarify_if_unknown")
        self.assertIn("company outcome", activity["activity_check"]["question_if_unclear"])
        self.assertNotIn("activity_check", self.cli("task-context", "Show the roadmap."))

    def test_product_handoff_offers_only_the_area_the_pm_shares(self):
        parent = "product/payments"
        owned = parent + "/area/refunds"
        context_capture.write_remit(self.work, {
            "status": "confirmed", "follow": [parent + "/area/ledger"],
            "responsibilities": [{"subject": owned, "role": "shared", "goals": [],
                                  "depends_on": [parent + "/area/settlement"]}],
        })
        while onboarding_review.status(self.work)["stage"] != "product":
            review_current_topic(self.work)
        state = self.cli("onboarding", "status")
        while state["stage"] == "product":
            state = self.cli("onboarding", "review-topic", data={
                "stage": "product", "revision": state["revision"], "subject": parent,
                "topic": state["walkthroughs"]["product"]["next_topic"]["id"],
                "outcome": "open", "pm_reply": "Let's leave that open.",
            })
        self.assertTrue(state["ready"])
        self.assertEqual(state["area_offers"], [owned])
        self.assertIn("optional", state["next_action"])
        self.assertNotIn("optional", self.cli("onboarding", "status")["next_action"])
        deferred = self.cli("onboarding", "select-area", data={
            "revision": state["revision"], "subject": None, "pm_reply": "Let's leave the area for later.",
        })
        self.assertEqual(deferred["optional_offer"]["workflow"], "profile-onboarding")
        self.assertEqual(deferred["optional_offer"]["next_action"], deferred["next_action"])

    def test_review_topic_returns_the_reserved_offer_for_the_client_to_present(self):
        source = "context/products/billing/sources/meeting.txt"
        path = self.work / source
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("Jo Diaz: I prefer a written summary with examples.\n")
        held = ingestion_signals.assess(self.work, {
            "moment": "busy", "source": {"kind": "transcript", "scope": source, "reference": source,
                "authorized": True, "purposes": ["stakeholder-profile"], "retention": "review",
                "subject": "product/billing"},
        })
        self.assertEqual(held["selection"]["status"], "deferred")
        while True:
            state = onboarding_review.status(self.work)
            if state["stage"] == "product" and state["walkthroughs"]["product"]["next_topic"]["id"] == "environment":
                break
            review_current_topic(self.work)
        result = self.cli("onboarding", "review-topic", data={
            "stage": "product", "revision": state["revision"], "subject": state["product_scope"]["subject"],
            "topic": "environment", "outcome": "open", "pm_reply": "Let's leave this open.",
        })
        self.assertIn("use only the selected optional offer", result["next_action"])
        offer = result["optional_offer"]
        self.assertEqual((offer["workflow"], offer["person"]), ("stakeholder-profile", "Jo Diaz"))
        self.assertEqual(self.cli("offer", "presented", offer["token"]), {"status": "presented"})
        self.assertNotIn("optional_offer", self.cli("onboarding", "status"))
