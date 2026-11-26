"""Optional profile setup yields to the PM's work and survives changes of client."""

import subprocess
import sys
import unittest

import test_pm
import context_capture
import onboarding
import onboarding_profile_step
import onboarding_review
from onboarding_fixtures import review_current_topic


class ProfileOnboardingTests(unittest.TestCase):
    setUp = test_pm.HubTests.setUp

    def handoff(self, subject=None, *, prompt=True):
        if subject:
            context_capture.write_remit(self.work, {"status": "confirmed", "follow": [],
                "responsibilities": [{"subject": subject, "role": "owner", "goals": [], "depends_on": []}]})
        while True:
            state = onboarding_review.status(self.work)
            if state["stage"] == "product" and state["walkthroughs"]["product"]["next_topic"]["id"] == "environment":
                break
            review_current_topic(self.work)
        return onboarding_review.review(self.work, {
            "revision": state["revision"], "stage": "product", "subject": state["product_scope"]["subject"],
            "topic": "environment", "outcome": "open", "pm_reply": "We can leave this open.",
            "offer_profiles": prompt,
        })

    def choice(self, choice, *, revision=None, reply="That's my choice."):
        revision = onboarding_profile_step.status(self.work)["revision"] if revision is None else revision
        return onboarding_review.profiles(self.work, {"revision": revision, "choice": choice, "pm_reply": reply})

    def area(self, subject):
        state = onboarding_review.status(self.work)
        return onboarding_review.select_area(self.work, {"revision": state["revision"], "subject": subject,
                                             "pm_reply": "Let's cover that area." if subject else "Leave that area for later."})

    def test_product_owner_gets_one_invitation_and_can_resume_or_finish_without_recording_personal_data(self):
        optional = self.work / onboarding_profile_step.FILE
        with self.assertRaisesRegex(ValueError, "parent product"):
            self.choice("start")
        self.assertFalse(optional.exists())
        result = self.handoff("product/checkout")
        self.assertIn("Offer optional stakeholder profiles", result["next_action"])
        self.assertTrue(result["ready"])
        self.assertEqual(result["stakeholder_profiles"], {"revision": 1, "status": "offered"})
        self.assertNotIn("Offer", onboarding.status(self.work)["next_action"])
        original = (self.work / onboarding_review.FILE).read_bytes()

        self.assertEqual(self.choice("skip")["stakeholder_profiles"]["status"], "skipped")
        with self.assertRaisesRegex(ValueError, "revision"):
            self.choice("start", revision=1)
        with self.assertRaisesRegex(ValueError, "PM's choice"):
            self.choice("start", reply="")
        self.assertEqual(self.choice("start")["stakeholder_profiles"]["status"], "active")
        self.assertEqual(self.choice("later")["stakeholder_profiles"]["status"], "deferred")
        self.assertEqual(self.choice("start")["stakeholder_profiles"]["status"], "active")
        done = self.choice("finish")
        self.assertEqual(done["stakeholder_profiles"]["status"], "complete")
        self.assertEqual(done["stage"], "ready")
        self.assertEqual(self.choice("finish")["stakeholder_profiles"], done["stakeholder_profiles"])
        self.assertNotIn("That's my choice", optional.read_text())
        self.assertEqual((self.work / onboarding_review.FILE).read_bytes(), original)
        self.assertFalse((self.work / "context/stakeholders/profiles").exists())

    def test_area_completion_or_deferral_precedes_invitation(self):
        area = "product/analytics/area/filters"
        result = self.handoff(area)
        self.assertIn("review of their area", result["next_action"])
        self.assertEqual(result["stakeholder_profiles"]["status"], "available")
        self.assertFalse((self.work / onboarding_profile_step.FILE).exists())
        self.assertEqual(self.area(area)["stage"], "area")
        while True:
            state = onboarding_review.status(self.work)
            topic = state["walkthroughs"]["area"]["next_topic"]["id"]
            after = onboarding_review.review(self.work, {"revision": state["revision"], "stage": "area", "subject": area,
                                           "topic": topic, "outcome": "open", "pm_reply": "That's open for now."})
            if after["stage"] == "ready":
                break
            self.assertEqual(after["stakeholder_profiles"]["status"], "available")
        self.assertEqual(after["stakeholder_profiles"]["status"], "offered")
        self.assertIn("Offer optional stakeholder profiles", after["next_action"])
        self.assertNotIn("Offer optional stakeholder profiles", self.area(None)["next_action"])

    def test_on_demand_profile_setup_can_coexist_with_active_area_without_guessing_on_resume(self):
        area = "product/analytics/area/filters"
        self.handoff(area)
        self.area(area)
        active = self.choice("start")
        self.assertTrue(active["ready"])
        self.assertIsNone(onboarding.area_request(active, "Resume setup."))
        self.assertEqual(onboarding.profile_request(active, "Resume setup.")["onboarding"]["stage"], "choose")
        self.assertEqual(onboarding.area_request(active, "Resume area setup.")["onboarding"]["subject"], area)
        self.assertEqual(onboarding.profile_request(active, "Resume stakeholder profile setup.")["onboarding"]["stage"],
                         "stakeholder_profiles")

    def test_skipping_area_and_returning_to_it_does_not_repeat_the_profiles_invitation(self):
        area = "product/analytics/area/filters"
        self.handoff(area)
        result = self.area(None)
        self.assertIn("Offer optional stakeholder profiles", result["next_action"])
        self.area(area)
        self.assertNotIn("Offer optional", self.area(None)["next_action"])

    def test_old_installations_and_quiet_handoffs_do_not_prompt_on_read_or_on_other_work(self):
        state = self.handoff("product/analytics", prompt=False)
        optional = self.work / onboarding_profile_step.FILE
        self.assertTrue(state["ready"])
        self.assertFalse(optional.exists())
        for prompt in ("Show my roadmap", "Review the stakeholder map", "Create a profile for Jordan",
                       "Review the draft that mentions stakeholder profile setup"):
            self.assertIsNone(onboarding.profile_request(state, prompt))
        route = onboarding.profile_request(state, "Let's set up stakeholder profiles.")
        self.assertEqual(route["status"], "optional_stakeholder_profiles")
        self.assertFalse(optional.exists())
        active = self.choice("start")
        self.assertIsNotNone(onboarding.profile_request(active, "Resume setup."))
        self.assertIsNone(onboarding.profile_request(active, "Resume the launch review."))

    def test_damaged_optional_checkpoint_does_not_close_hub(self):
        self.handoff()
        optional = self.work / onboarding_profile_step.FILE
        optional.write_text("damaged optional checkpoint")
        state = onboarding.status(self.work)
        self.assertTrue(state["ready"])
        self.assertEqual(state["stakeholder_profiles"]["status"], "repair")
        self.assertIsNone(onboarding.profile_request(state, "Show my roadmap"))
        self.assertEqual(optional.read_text(), "damaged optional checkpoint")

    def test_source_silence_prevents_the_handoff_offer_and_permits_explicit_setup(self):
        command = [sys.executable, str(self.root / "tools/pm.py"), "override", "profile-suggestions",
                   "off", "--source", "onboarding"]
        result = subprocess.run(command, cwd=self.work, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        result = self.handoff()
        self.assertEqual(result["stakeholder_profiles"]["status"], "available")
        self.assertNotIn("Offer optional", result["next_action"])
        self.assertEqual(self.choice("start")["stakeholder_profiles"]["status"], "active")
