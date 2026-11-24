"""A framework pass counts the PM's interactions independently of saved facts."""

import json
import unittest

import test_pm
import company_onboarding
import context_capture
import onboarding_review as review
import pm


class WalkthroughTests(unittest.TestCase):
    setUp = test_pm.HubTests.setUp

    def record(self, outcome="open", **changes):
        status = review.status(self.work)
        stage = status["stage"]
        topic = status["walkthroughs"][stage]["next_topic"]["id"]
        values = {"revision": status["revision"], "stage": stage, "topic": topic,
                  "outcome": outcome, "pm_reply": "Leave that open for now."}
        if stage == "product":
            values["subject"] = status["product_scope"]["subject"]
        return review.review(self.work, dict(values, **changes))

    def select(self, subject):
        return review.select_product(self.work, {"revision": review.status(self.work)["revision"],
                                     "subject": subject, "pm_reply": "Let's use this scope for the walkthrough."})

    def product_stage(self):
        while review.status(self.work)["stage"] in {"company", "pm"}:
            self.record()

    def remit(self, *subjects):
        context_capture.write_remit(self.work, {"status": "confirmed", "follow": [],
            "responsibilities": [{"subject": s, "role": "owner", "goals": [], "depends_on": []} for s in subjects]})

    def test_first_pass_can_leave_every_answer_open_without_a_product_or_area_record(self):
        self.assertFalse((self.work / review.FILE).exists())
        topics = ("customers", "economics", "portfolio", "growth", "tradeoffs")
        for number, topic in enumerate(topics):
            walk = company_onboarding.status(self.work)["walkthrough"]
            self.assertEqual(walk["next_topic"]["id"], topic)
            self.assertEqual(len(walk["reviewed"]), number)
            state = self.record()
        self.assertTrue(state["walkthroughs"]["company"]["complete"])
        self.assertEqual(state["walkthroughs"]["company"]["reviewed"], dict.fromkeys(topics, "open"))
        self.assertEqual(state["stage"], "pm")
        self.assertTrue(state["stage_available"])
        profile = self.work / pm.layout.PROFILE
        profile_before = profile.read_bytes() if profile.exists() else None
        for topic in ("role", "responsibilities", "expectations", "aspirations", "stakeholders"):
            self.assertEqual(state["walkthroughs"]["pm"]["next_topic"]["id"], topic)
            state = self.record()
        self.assertEqual(state["stage"], "product")
        self.assertTrue(state["stage_available"])
        self.assertFalse(state["ready"])
        self.assertTrue(state["walkthroughs"]["pm"]["complete"])
        self.assertEqual(profile.read_bytes() if profile.exists() else None, profile_before)
        self.assertFalse((self.work / pm.layout.STAKEHOLDERS).exists())
        self.assertFalse((self.work / "context/company/overview.md").exists())
        self.assertNotIn("Leave that open", (self.work / review.FILE).read_text())
        self.assertEqual(pm.check(self.root), [])
        with self.assertRaisesRegex(ValueError, "currently available"):
            review.review(self.work, {"revision": state["revision"], "stage": "pm", "topic": "fake",
                                      "outcome": "reviewed", "pm_reply": "Yes."})
        with self.assertRaisesRegex(ValueError, "Choose the product"):
            self.record()
        self.assertIsNone(self.select(None)["product_scope"]["subject"])
        for topic in ("purpose", "customers", "experience", "business-value", "performance", "environment"):
            state = self.record(topic=topic)
        self.assertTrue(state["ready"])
        self.assertIsNone(state["reviewed_product_subject"])
        self.assertFalse(list((self.work / "context/products").glob("**/overview.md")))

    def test_coverage_belongs_to_selected_scope_and_survives_switching(self):
        first, second = "product/payments/area/refunds", "product/support"
        self.remit(first, second)
        self.product_stage()
        scope = review.status(self.work)["product_scope"]
        self.assertTrue(scope["selection_required"])
        self.assertCountEqual(scope["choices"], [first, second])
        with self.assertRaisesRegex(ValueError, "Confirm the product"):
            self.select("product/payments")  # Owning Refunds gives no authority over its parent.
        self.select(first)
        covered = self.record("reviewed")
        self.assertEqual(covered["walkthroughs"]["product"]["next_topic"]["id"], "customers")
        self.assertEqual(self.select(second)["walkthroughs"]["product"]["reviewed"], {})
        resumed = self.select(first)
        self.assertEqual(resumed["walkthroughs"]["product"], covered["walkthroughs"]["product"])
        while review.status(self.work)["stage"] == "product":
            result = self.record()
        self.assertEqual(result["reviewed_product_subject"], first)
        self.assertFalse(self.select(second)["ready"])
        self.assertTrue(self.select(first)["ready"])

    def test_single_remit_is_reused_and_moved_responsibility_requires_fresh_review(self):
        first, second = "product/payments", "product/lending"
        self.remit(first)
        self.product_stage()
        status = review.status(self.work)
        self.assertEqual(status["product_scope"], {"choices": [first], "subject": first, "selection_required": False})
        self.remit(second)
        with self.assertRaisesRegex(ValueError, "scope changed"):
            self.record(subject=first)
        self.record()
        self.remit(first)
        self.assertTrue(review.status(self.work)["product_scope"]["selection_required"])
        with self.assertRaisesRegex(ValueError, "Choose the product"):
            self.record()
        self.assertEqual(self.select(first)["walkthroughs"]["product"]["reviewed"], {})

    def test_old_pm_completion_opens_product_setup_without_rewriting_receipts(self):
        self.product_stage()
        path = self.work / review.FILE
        prior = json.loads(path.read_bytes())
        self.assertEqual(set(prior), {"format", "revision", "reviewed", "completed"})
        original = path.read_bytes()
        self.assertTrue(review.status(self.work)["product_scope"]["selection_required"])
        self.assertEqual(path.read_bytes(), original)
        self.select(None)
        self.record()
        self.remit("product/payments")
        pending = review.status(self.work)
        self.assertTrue(pending["product_scope"]["selection_required"])
        fresh = self.select("product/payments")
        self.assertEqual(fresh["walkthroughs"]["product"]["reviewed"], {})
        current = json.loads(path.read_bytes())
        for stage in ("company", "pm"):
            self.assertEqual(current["completed"][stage], prior["completed"][stage])
            self.assertEqual(current["reviewed"][stage], prior["reviewed"][stage])

    def test_pausing_existing_capture_and_writing_a_brief_do_not_review_any_topics(self):
        company = self.work / "context/company/overview.md"
        company.parent.mkdir(parents=True, exist_ok=True)
        company.write_text("# Existing brief\n\nOur product helps clinics.\n")
        company_onboarding.change(self.root, "finish", {"revision": 0}, "Fixture PM", pm.capture_errors)
        capture_before = (self.work / company_onboarding.FILE).read_bytes()
        self.assertFalse((self.work / review.FILE).exists())
        resumed = self.record("reviewed", pm_reply="Our existing description still holds.")
        self.assertEqual(resumed["walkthroughs"]["company"]["next_topic"]["id"], "economics")
        self.assertEqual((self.work / company_onboarding.FILE).read_bytes(), capture_before)
        self.assertEqual(company_onboarding.status(self.work)["walkthrough"], resumed["walkthroughs"]["company"])

    def test_rejects_stale_skipped_invalid_and_unconfirmed_topics_atomically(self):
        state = self.record("not_applicable", pm_reply="This is an internal platform.")
        original = (self.work / review.FILE).read_bytes()
        for update in ({"revision": 0}, {"topic": "customers"}, {"topic": "growth"},
                       {"outcome": "answered all"}, {"pm_reply": " "}, {"stage": "product"}):
            with self.subTest(update=update), self.assertRaises(ValueError):
                self.record(**update)
        self.assertEqual((self.work / review.FILE).read_bytes(), original)
        self.assertEqual(review.status(self.work), state)

    def test_pending_wording_and_broken_or_redirected_checkpoints_are_not_bypasses(self):
        def change(op, data):
            revision = company_onboarding.status(self.work)["revision"]
            return company_onboarding.change(self.root, op, {"revision": revision, **data},
                                             "Fixture PM", pm.capture_errors)
        change("plan", {"purpose": "Identify the segment.", "sources": ["Example source"]})
        change("approve", {})
        change("propose", {"source_scope": "Example source", "sources": [{
            "reference": "Example source", "date": "undated", "checked_on": "2025-02-01",
            "coverage": "read", "text": "We serve clinics."}], "entries": [{
            "scope": "company", "topic": "markets", "source": 1, "location": "Slide 1", "quote": "We serve clinics."}]})
        with self.assertRaisesRegex(ValueError, "pending company finding"):
            self.record()
        path = self.work / review.FILE
        self.assertFalse(path.exists())
        original = self.root.parent / "test-checkpoint"
        original.write_bytes(b"{}")
        path.symlink_to(original)
        with self.assertRaisesRegex(ValueError, "regular walkthrough"):
            review.status(self.work)
        self.assertEqual(original.read_bytes(), b"{}")

    def test_registered_frameworks_alone_never_imply_reviewed_coverage(self):
        path = self.root / review.MANIFEST
        definitions = json.loads(path.read_text())
        for stage in ("pm", "product"):
            definitions[stage] = [{"id": "fixture-topic", "question": "What should this fixture cover?"}]
        path.write_text(json.dumps(definitions))
        for _ in definitions["company"]:
            self.record()
        self.assertEqual(self.record()["stage"], "product")
        self.select(None)
        completed = self.record()
        self.assertTrue(completed["ready"])
        self.assertEqual(completed["stage"], "ready")
        self.assertTrue(all(walk["complete"] for walk in completed["walkthroughs"].values()))

    def test_framework_updates_extend_an_active_pass_but_preserve_a_finished_pass(self):
        path = self.root / review.MANIFEST
        definitions = review.manifest(self.root)
        self.record()
        definitions["company"].append({"id": "added-during-review", "question": "What has changed?"})
        path.write_text(json.dumps(definitions))
        for _ in range(4):
            status = self.record()
        self.assertEqual(status["walkthroughs"]["company"]["next_topic"]["id"], "added-during-review")
        self.assertEqual(self.record()["stage"], "pm")
        checkpoint = (self.work / review.FILE).read_bytes()
        definitions["company"].append({"id": "added-later", "question": "What would you revisit now?"})
        path.write_text(json.dumps(definitions))
        status = review.status(self.work)
        self.assertEqual(status["stage"], "pm")
        self.assertTrue(status["walkthroughs"]["company"]["complete"])
        self.assertIsNone(status["walkthroughs"]["company"]["next_topic"])
        self.assertNotIn("added-later", status["walkthroughs"]["company"]["reviewed"])
        self.assertEqual((self.work / review.FILE).read_bytes(), checkpoint)

    def test_removed_remaining_topics_wait_for_the_pm_to_close_the_pass(self):
        self.record()
        path = self.root / review.MANIFEST
        definitions = review.manifest(self.root)
        definitions["company"] = definitions["company"][:1]
        path.write_text(json.dumps(definitions))
        self.assertEqual(review.status(self.work)["walkthroughs"]["company"]["next_topic"]["id"], "customers")
        self.assertEqual(self.record()["stage"], "pm")
        self.assertTrue(review.status(self.work)["walkthroughs"]["company"]["complete"])
