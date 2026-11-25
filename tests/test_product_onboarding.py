"""Product context is captured only in its agreed, sourced and reviewed scope."""

import json
import subprocess
import sys
import unittest
from unittest.mock import patch

import test_pm
import test_pm_onboarding
import company_onboarding as capture
import context_capture
import layout
import onboarding_review
import pm
import records
import storage
from onboarding_fixtures import review_current_topic


class ProductOnboardingTests(unittest.TestCase):
    setUp = test_pm.HubTests.setUp
    product = "analytics"
    subject = "product/analytics/area/salesforce"
    parent = "context/products/analytics/overview.md"
    area = "context/products/analytics/plugins/salesforce/overview.md"

    def start(self, *subjects, opt_in=True):
        while onboarding_review.status(self.work)["stage"] in {"company", "pm"}:
            review_current_topic(self.work)
        remit = {"status": "confirmed", "responsibilities": [
            {"subject": subject, "role": "owner", "goals": [], "depends_on": []}
            for subject in (subjects or (self.subject,))], "follow": []}
        context_capture.write_remit(self.work, remit)
        if opt_in and self.subject in (subjects or (self.subject,)):
            self.enter_area()

    def enter_area(self):
        while onboarding_review.status(self.work)["stage"] == "product":
            review_current_topic(self.work)
        state = onboarding_review.status(self.work)
        return onboarding_review.select_area(self.work, {
            "subject": self.subject, "revision": state["revision"], "pm_reply": "Let's review the Salesforce plugin.",
        })

    def change(self, operation, **payload):
        payload.setdefault("revision", capture.read(self.work, "product")[1]["revision"])
        return capture.change(self.root, operation, payload, "Fixture PM", pm.capture_errors, kind="product")

    def plan(self, destinations=None, subject=None, **options):
        return self.change("plan", purpose="Understand the current pilot experience.", subject=subject or self.subject,
                           sources=["PM discussion"], destinations=destinations or [self.parent, self.area], **options)

    def propose(self, *, parent=False, text="The Salesforce connector is in a closed pilot.", **overrides):
        source = {"reference": "PM discussion", "date": "undated", "checked_on": "2026-01-05",
                  "coverage": "partial", "text": text + " The unrelated secret fixture is here."}
        entry = {"scope": "product", "product": self.product, "source": 1, "topic": "customers",
                 "location": "PM reply", "quote": text}
        if not parent:
            entry["product_area"] = "salesforce"
        return self.change("propose", source_scope="PM discussion", sources=[source], entries=[dict(entry, **overrides)])

    def test_direct_creation_respects_the_planned_subject_across_folder_names(self):
        self.start(opt_in=False)
        while onboarding_review.status(self.work)["stage"] == "product":
            review_current_topic(self.work)
        records.create(self.root, "product-context", self.parent, "Analytics")
        self.plan([self.area])
        self.change("approve")
        for area, allowed in (("salesforce", False), ("reporting", True)):
            path = layout.area(self.product, area, "extensions")
            result = subprocess.run([
                sys.executable, str(self.root / "tools/pm.py"), "new", "product-area-context", path,
                "--reason", "Support uses the guide every week.", "--trigger", "A new integration ships.",
            ], cwd=self.root, text=True, capture_output=True)
            self.assertEqual(result.returncode == 0, allowed, result.stdout + result.stderr)
            self.assertEqual((self.work / path).is_file(), allowed)
            if not allowed:
                self.assertIn("product-onboarding", result.stderr + result.stdout)
        self.propose()
        self.change("accept")
        self.assertTrue((self.work / self.area).is_file())

    def test_selected_area_owns_its_generic_capture_even_before_a_plan(self):
        self.start()
        sibling = layout.area(self.product, "reporting", "plugins")
        self.assertTrue(capture.product_capture_owns(self.work, self.area))
        self.assertFalse(capture.product_capture_owns(self.work, sibling))
        for area, active in (("salesforce", True), ("reporting", False)):
            entry = {"scope": "product", "product": self.product, "product_area": area}
            self.assertEqual(capture.entries_in_product_round(self.work, [entry]), active)

    def test_pausing_the_area_walkthrough_does_not_expand_its_approved_capture_plan(self):
        self.start()
        self.plan([self.parent, self.area])
        self.change("approve")
        self.propose()
        checkpoint = self.work / capture.PRODUCT_FILE
        approved = checkpoint.read_bytes()
        onboarding_review.select_area(self.work, {"revision": onboarding_review.status(self.work)["revision"],
                                      "subject": None, "pm_reply": "Let's pause the plugin walkthrough."})
        self.assertEqual(onboarding_review.status(self.work)["stage"], "ready")
        self.assertEqual(checkpoint.read_bytes(), approved)
        self.change("discard")
        with self.assertRaisesRegex(ValueError, "Product-wide findings need their own round"):
            self.propose(parent=True, text="All Analytics users work at clinics.")
        self.assertFalse((self.work / self.parent).exists())
        self.assertFalse((self.work / self.area).exists())

    def test_legacy_pending_child_can_be_deferred_while_parent_review_resumes(self):
        self.start()
        self.plan()
        self.change("approve")
        quote = "The connector is available to the pilot cohort."
        self.propose(text=quote)
        path = self.work / onboarding_review.FILE
        mixed = json.loads(path.read_text())
        mixed.pop("area_selection")
        mixed.pop("area_history", None)
        mixed["product_selection"] = self.subject
        mixed["reviewed"]["product"] = {"purpose": "open"}
        del mixed["completed"]["product"]
        path.write_text(json.dumps(mixed))
        self.assertEqual(onboarding_review.status(self.work)["product_scope"]["subject"], "product/analytics")
        with self.assertRaisesRegex(ValueError, "parent product"):
            self.change("accept")
        self.change("defer", destination=self.area, question="Who joined the pilot?",
                    why="Understand the cohort.", next_action="Review the approved roster.",
                    resume_when="Pilot roster arrives")
        self.change("finish")
        self.plan([self.parent], subject="product/analytics")
        gap = capture.read(self.work, "product")[1]["gaps"][0]
        self.assertEqual((gap["subject"], gap["basis"]["quote"]), (self.subject, quote))
        self.assertFalse((self.work / self.area).exists())

    def test_area_capture_requires_parent_review_and_can_create_an_approved_parent_shell(self):
        self.start(opt_in=False)
        with self.assertRaisesRegex(ValueError, "parent product"):
            self.plan()
        state = capture.status(self.work, "product")
        self.assertEqual(state["subject"], "product/analytics")
        self.assertEqual(state["responsibilities"], [self.subject])
        self.enter_area()
        with self.assertRaisesRegex(ValueError, "Include the missing parent"):
            self.plan([self.area])
        self.plan(titles={self.parent: "Acme Analytics", self.area: "Salesforce Plug-in"})
        with self.assertRaisesRegex(ValueError, "approve"):
            self.propose()
        self.change("approve")
        with self.assertRaisesRegex(ValueError, "selected area"):
            self.propose(parent=True)
        finding = self.propose()["pending"]
        self.assertEqual(finding["destination"], self.area)
        self.assertEqual(finding["creates_parent"], self.parent)
        self.assertFalse((self.work / self.parent).exists())
        self.assertFalse((self.work / self.area).exists())
        self.assertIsNone(capture.status(self.work, "product")["pending"])
        self.assertNotIn("unrelated secret", (self.work / capture.PRODUCT_FILE).read_text())
        with self.assertRaisesRegex(ValueError, "grouping"):
            self.propose(area_group="components")
        self.change("accept")
        child = (self.work / self.area).read_text()
        self.assertIn("# Salesforce Plug-in", child)
        self.assertIn("Area users and workflow", child)
        self.assertIn(finding["entry"]["quote"], child)
        self.assertIn("PM discussion", child)
        self.assertIn("# Acme Analytics", (self.work / self.parent).read_text())
        self.assertNotIn(finding["entry"]["quote"], (self.work / self.parent).read_text())
        self.assertEqual(pm.records.parent_reference(self.area, child), self.parent)
        self.assertEqual(context_capture.read_remit(self.work)["responsibilities"][0]["subject"], self.subject)

    def test_ready_studio_requires_this_areas_parent_review_for_guided_capture(self):
        self.start("product/other", self.subject, opt_in=False)
        onboarding_review.select_product(self.work, {"revision": onboarding_review.status(self.work)["revision"],
                                         "subject": "product/other", "pm_reply": "Let's cover the other product first."})
        while onboarding_review.status(self.work)["stage"] == "product":
            review_current_topic(self.work)
        self.assertTrue(onboarding_review.status(self.work)["ready"])
        with self.assertRaisesRegex(ValueError, "parent product first"):
            self.plan()
        onboarding_review.select_product(self.work, {"revision": onboarding_review.status(self.work)["revision"],
                                         "subject": "product/analytics", "pm_reply": "Now let's cover Analytics."})
        while onboarding_review.status(self.work)["stage"] == "product":
            review_current_topic(self.work)
        self.assertEqual(self.plan()["phase"], "plan")

    def test_defer_resolve_require_the_same_scope_and_reviewed_answer(self):
        self.start()
        self.plan()
        self.change("approve")
        self.propose()
        gap = {"question": "Who participates in the connector pilot?", "why": "Check the sample.",
               "next_action": "Review the pilot roster.", "resume_when": "pilot roster arrives"}
        with self.assertRaisesRegex(ValueError, "pending finding"):
            self.change("defer", destination=self.parent, **gap)
        self.change("defer", destination=self.area, **gap)
        with self.assertRaisesRegex(ValueError, "area question"):
            self.change("gap", destination=self.parent, **gap)
        self.change("gap", destination=self.area, **dict(gap, question="Who can grant pilot access?"))
        state = capture.status(self.work, "product")
        self.assertEqual(state["gap_count"], 2)
        self.assertNotIn("gaps", state)
        self.assertFalse((self.work / self.area).exists())
        first = capture.status(self.work, "product", gap=state["gap_selectors"][0])["gap"]
        self.assertEqual(first["subject"], self.subject)
        self.assertEqual(first["destination"], self.area)
        self.propose(text="Support team members use the connector pilot.", answers=gap["question"])
        self.change("resolve", question=gap["question"])
        state = capture.read(self.work, "product")[1]
        self.assertEqual([g["question"] for g in state["gaps"]], ["Who can grant pilot access?"])
        self.assertIn("Support team members", (self.work / self.area).read_text())

    def test_cli_answers_a_legacy_area_question_in_its_approved_original_home(self):
        self.start()
        question = "Which access limit applies to the connector pilot?"
        quote = "Only clinic administrators can configure the connector during the pilot."
        test_pm.legacy_inline_area(self.root, self.work, self.product, "salesforce", question)
        parent = self.work / self.parent
        before = parent.read_bytes()
        source = dict(reference="PM discussion", checked_on="2026-01-05", date="undated",
                      coverage="partial", text=quote)
        entry = dict(scope="product", product=self.product, product_area="salesforce", topic="constraints",
                     quote=quote, source=1, location="PM reply", answers=question)

        def command(operation, *, expected=0, **fields):
            fields["revision"] = capture.read(self.work, "product")[1]["revision"]
            return test_pm_onboarding.PMOnboardingTests.cli(
                self, "product-onboarding", operation, data=fields, expected=expected)

        proposal = dict(source_scope="PM discussion", sources=[source], entries=[entry])
        self.plan([self.area])
        command("approve")
        self.assertIn("destination", command("propose", expected=1, **proposal))
        self.plan([self.parent, self.area])
        self.assertIn("approve", command("propose", expected=1, **proposal))
        command("approve")
        pending = json.loads(command("propose", **proposal))["pending"]
        self.assertEqual(pending["destination"], self.parent)
        self.assertEqual(pending["entry"]["product_area"], "salesforce")
        self.assertEqual(parent.read_bytes(), before)
        self.assertFalse((self.work / self.area).exists())

        # A redirect during review requires another preview. It cannot create a shadow area.
        parent.write_text(parent.read_text().replace(question, "Which role approves integrations?"))
        self.assertIn("destination changed", command("accept", expected=1))
        self.assertFalse((self.work / self.area).exists())
        parent.write_bytes(before)
        record = dict(path=self.parent, reason="This brief holds the original scoped pilot question.")
        unrelated = dict(entry, record=record, answers="Which teams use the connector?")
        self.assertIn("record", command("propose", expected=1, **dict(proposal, entries=[unrelated])))
        command("propose", **dict(proposal, entries=[dict(entry, record=record)]))
        command("accept")
        saved = parent.read_text()
        self.assertNotIn("- Unknown: Product area salesforce", saved)
        self.assertIn(f"Answers: Product area salesforce — {question} <!-- product-area:salesforce -->", saved)
        self.assertIn(quote, saved)
        self.assertIn("PM discussion", saved)
        self.assertFalse((self.work / self.area).exists())

    def test_scope_changes_reject_stale_approval_and_chat_only_drafts_can_be_discarded(self):
        self.start()
        with self.assertRaisesRegex(ValueError, "confirmed|Confirm"):
            self.plan([self.parent], subject="product/analytics")
        self.plan()
        self.change("approve")
        self.propose()
        with self.assertRaisesRegex(ValueError, "plan"):
            self.propose(product_area="other")
        remit = context_capture.read_remit(self.work)
        remit["responsibilities"].clear()
        context_capture.write_remit(self.work, remit)
        with self.assertRaisesRegex(ValueError, "Confirm"):
            self.change("accept")
        self.change("discard")
        self.change("finish")
        self.assertFalse((self.work / self.area).exists())
        self.assertFalse((self.work / self.parent).exists())
        self.assertNotIn("Salesforce connector is", (self.work / capture.PRODUCT_FILE).read_text())

    def test_parent_write_and_area_retry_preserve_exact_evidence(self):
        self.start(opt_in=False)
        self.plan([self.parent], subject="product/analytics")
        self.change("approve")
        self.propose(parent=True, text="The customers are independent clinic administrators.")
        self.change("accept")
        original_parent = (self.work / self.parent).read_bytes()
        self.change("finish")
        self.enter_area()
        self.plan([self.area])
        self.change("approve")
        self.propose()
        real_write = storage.replace_text
        def interrupt(path, *args):
            if path == self.work / capture.PRODUCT_FILE:
                raise OSError("Stopped after saving the finding")
            return real_write(path, *args)
        with patch.object(storage, "replace_text", interrupt), self.assertRaisesRegex(OSError, "Stopped"):
            self.change("accept")
        after = (self.work / self.area).read_bytes()
        self.change("accept")
        self.assertEqual((self.work / self.area).read_bytes(), after)
        self.assertEqual((self.work / self.parent).read_bytes(), original_parent)
        self.assertIsNone(capture.status(self.work, "product", pending=True)["pending"])

    def test_failed_first_area_save_keeps_the_review_and_can_retry(self):
        self.start()
        self.plan()
        self.change("approve")
        review = self.propose()
        with patch.object(context_capture, "apply", side_effect=ValueError("Area validation failed")):
            with self.assertRaisesRegex(ValueError, "Area validation failed"):
                self.change("accept")
        self.assertFalse((self.work / self.parent).exists())
        self.assertFalse((self.work / self.area).exists())
        self.assertEqual(review["pending"], capture.status(self.work, "product", pending=True)["pending"])
        self.change("accept")
        self.assertTrue((self.work / self.area).is_file())

    def test_agreed_revisit_cue_exposes_only_a_scoped_gap_selector(self):
        self.start()
        self.plan()
        self.change("approve")
        question = "Which clinicians use the private pilot?"
        self.change("gap", destination=self.area, question=question, why="Confirm pilot reach.",
                    next_action="Check the pilot roster.", resume_when="pilot roster arrives")
        self.change("finish")
        hint = capture.followup(self.work, "The pilot roster arrives.", False, "product", subject=self.subject)
        self.assertIn("status --gap", hint)
        self.assertNotIn(question, hint)
        self.assertIsNone(capture.followup(self.work, "The pilot roster arrives.", False, "product",
                                           subject="product/payment"))

    def test_uncertain_founder_interpretation_stays_attributed_with_its_open_question(self):
        self.start("product/analytics")
        self.plan([self.parent], "product/analytics")
        self.change("approve")
        self.propose(parent=True, text="I think clinics may need this to find missed appointments.",
                     interpretation="The founder expects clinics to value missed-appointment reports.",
                     uncertainty="Which clinics have validated this need?")
        self.change("accept")
        text = (self.work / self.parent).read_text()
        self.assertIn("- Interpretation:", text)
        self.assertIn("Open question at capture:", text)
        self.assertIn("PM discussion", text)
        self.assertEqual(set(json.loads((self.work / capture.PRODUCT_FILE).read_bytes())["plan"]["destinations"]),
                         {self.parent})
