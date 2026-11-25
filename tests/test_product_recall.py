"""Recall one current, authorised product passage inside the still-gated walkthrough."""

import unittest
from unittest.mock import patch

import test_conversation
import test_pm
import company_onboarding
import context_capture
import context_embeddings
import evidence_reviews
import layout
import onboarding_review
import pm
import product_intake
import records
import task_context
from onboarding_fixtures import review_current_topic


class ProductRecallTests(unittest.TestCase):
    cli = test_conversation.ConversationTests.cli
    subject = "product/analytics/area/salesforce"

    def setUp(self):
        test_pm.HubTests.setUp(self)
        self.cwd = self.root
        while onboarding_review.status(self.work)["stage"] != "product":
            review_current_topic(self.work)
        context_capture.write_remit(self.work, {"status": "confirmed", "follow": [], "responsibilities": [
            {"subject": self.subject, "role": "owner", "goals": [], "depends_on": []}]})
        self.parent = layout.product("analytics")
        self.child = layout.area("analytics", "salesforce", "plugins")
        self.sibling = layout.area("analytics", "billing", "components")
        records.create(self.root, "product-context", self.parent, "Analytics")
        for child in (self.child, self.sibling):
            records.create(self.root, "product-area-context", child, "Component")

    def change(self, op, **fields):
        revision = company_onboarding.read(self.work, "product")[1]["revision"]
        return company_onboarding.change(self.root, op, dict(revision=revision, **fields),
                                         "Fixture PM", pm.capture_errors, kind="product")

    def plan(self, *sources):
        self.change("plan", sources=list(sources), destinations=[self.parent, self.child],
                    purpose="Reuse existing evidence about the plugin.", subject=self.subject)

    def populate(self, path, heading, body):
        target = self.work / path
        content = context_capture.edit_section(target.read_text(), heading, body)
        sources = ("| ID | Source | Source date | Checked on |\n| --- | --- | --- | --- |\n"
                   "| S1 | Pilot review | 2025-01-20 | 2025-01-25 |\n"
                   "| S2 | Future results | 2099-05-01 | 2099-05-02 |")
        target.write_text(context_capture.edit_section(content, "Sources", sources))

    def enter_area(self):
        while onboarding_review.status(self.work)["stage"] == "product":
            review_current_topic(self.work)
        return onboarding_review.select_area(self.work, {
            "subject": self.subject, "revision": onboarding_review.status(self.work)["revision"],
            "pm_reply": "Let's review our Salesforce plugin.",
        })

    def topic(self, target):
        if onboarding_review.status(self.work)["stage"] == "product":
            self.enter_area()
        while onboarding_review.status(self.work)["walkthroughs"]["area"]["next_topic"]["id"] != target:
            review_current_topic(self.work)

    def test_public_recall_reuses_reviewed_words_and_qualifications_without_saving(self):
        self.topic("performance")
        text = ("- Reported metric: In the ten-merchant pilot, weekly adoption rose from four to six accounts. [S1]\n"
                "  Open question at capture: Did the cohort change in January?")
        self.populate(self.child, "Goals, performance, and gaps", text + "\n"
                      "- Reported metric: Future results predict doubled weekly adoption. [S2]")
        self.populate(self.sibling, "Goals, performance, and gaps", "- Reported metric: Secret sibling result. [S1]")
        self.plan(self.child, self.sibling)
        self.assertEqual(self.cli("product-onboarding", "status", "--evidence")["status"], "plan_required")
        self.change("approve")
        paths = [self.work / name for name in (company_onboarding.PRODUCT_FILE, onboarding_review.FILE, self.child)]
        before = [path.read_bytes() for path in paths]
        result = self.cli("product-onboarding", "status", "--evidence")
        self.assertEqual(result["status"], "candidate")
        self.assertEqual(result["topic"], "performance")
        row = result["evidence"]
        self.assertEqual((row["scope"], row["record"]), (self.subject, self.child))
        self.assertEqual(row["text"], text)
        self.assertEqual(row["evidence_status"], "unresolved")
        self.assertEqual(row["sources"][0]["Source date"], "2025-01-20")
        self.assertNotIn("Secret sibling", str(result))
        self.assertNotIn("Future results", str(result))
        self.assertEqual(before, [path.read_bytes() for path in paths])

    def test_destinations_and_ambiguous_source_names_never_grant_search_access(self):
        self.topic("customers")
        self.populate(self.child, "Area users and workflow", "- Fact: Clinics use the plugin to find lost orders. [S1]")
        self.plan("PM conversation", "the plugin brief", self.sibling)
        self.change("approve")
        with patch.object(task_context, "read_document", side_effect=AssertionError("Unexpected file read")):
            self.assertEqual(product_intake.recall(self.work)["status"], "open")
        self.plan(self.child)
        self.change("approve")
        (self.work / self.child).unlink()
        (self.work / self.child).symlink_to(self.work / self.sibling)
        with self.assertRaisesRegex(ValueError, "regular workspace record"):
            product_intake.recall(self.work)

    def test_parent_evidence_keeps_parent_scope(self):
        self.topic("customers")
        self.populate(self.parent, "The users", "- Fact: The product's customers are clinic administrators. [S1]")
        self.plan(self.parent)
        self.change("approve")
        result = self.cli("product-onboarding", "status", "--evidence")
        self.assertEqual(result["status"], "candidate")
        self.assertEqual(result["subject"], self.subject)
        self.assertEqual(result["evidence"]["scope"], "product/analytics")

    def test_product_step_never_retrieves_its_owners_area_as_parent_evidence(self):
        while onboarding_review.status(self.work)["walkthroughs"]["product"]["next_topic"]["id"] != "customers":
            review_current_topic(self.work)
        area_claim = "The plugin’s customers are clinic administrators."
        self.populate(self.child, "Area users and workflow", f"- Fact: {area_claim} [S1]")
        self.change("plan", sources=[self.child], destinations=[self.parent], subject="product/analytics",
                    purpose="Review customers of the parent product.")
        self.change("approve")
        with patch.object(task_context, "read_document", side_effect=AssertionError("Area read while reviewing parent")):
            result = product_intake.recall(self.work)
        self.assertEqual(result["status"], "open")
        self.assertEqual(result["subject"], "product/analytics")

    def test_recall_preserves_active_reviews_in_approved_briefs(self):
        self.topic("customers")
        quote = "The plugin’s customers are clinic administrators."
        heading = "Area users and workflow"
        self.populate(self.child, heading, f"- Fact: {quote} [S1]")
        event = {"id": evidence_reviews.identifier(quote), "state": "open", "on": "2025-02-01",
                 "reason": "The two pilot accounts identify different buyers.", "classification": "potential conflict",
                 "targets": [], "scope": {"product": "analytics", "area": "salesforce", "initiative": None},
                 "claims": [{"record": self.child, "section": heading, "text": quote}]}
        parent = self.work / self.parent
        parent.write_text(evidence_reviews.append(parent.read_text(), [event]))
        self.plan(self.child)
        self.change("approve")
        def read_evidence():
            return self.cli("product-onboarding", "status", "--evidence")["evidence"]
        self.assertNotIn("risk_reviews", read_evidence())
        self.plan(self.child, self.parent)
        self.change("approve")
        recalled = read_evidence()
        self.assertEqual(recalled["evidence_status"], "under review")
        self.assertEqual(recalled["risk_reviews"], [event["id"]])
        parent.write_text(evidence_reviews.append(parent.read_text(), [{
            "id": event["id"], "state": "resolve", "on": "2025-03-01",
            "reason": "Both clinic buyers confirmed the segment.", "source": "Pilot follow-up.",
        }]))
        self.assertEqual(read_evidence()["evidence_status"], "source statement")

        child = self.work / self.child
        child.write_text(child.read_text() + "\n## " + evidence_reviews.HEADING + "\n\nMissing review events.\n")
        self.assertEqual(read_evidence()["evidence_status"], "under review")

    def test_approved_area_must_still_have_one_home_at_recall(self):
        self.topic("customers")
        self.populate(self.child, "Area users and workflow", "- Fact: The plugin’s customers are clinic administrators. [S1]")
        self.change("plan", sources=[self.child], destinations=[self.child],
                    purpose="Review what we know about the area.", subject=self.subject)
        self.change("approve")
        self.assertEqual(product_intake.recall(self.work)["status"], "candidate")
        duplicate = self.work / layout.area("analytics", "salesforce", "extensions")
        duplicate.parent.mkdir(parents=True)
        duplicate.write_bytes((self.work / self.child).read_bytes())
        with patch.object(task_context, "read_document", side_effect=AssertionError("Read ambiguous evidence")):
            self.cli("product-onboarding", "status", "--evidence", error="Multiple homes")
            with self.assertRaisesRegex(ValueError, "Multiple homes"):
                product_intake.recall(self.work)

    def test_recall_needs_a_relevant_claim_even_with_a_matching_heading_or_keyword(self):
        self.enter_area()
        self.plan(self.child)
        self.change("approve")
        self.populate(self.child, "Area scope and ownership", "- Fact: The product team chose a new meeting room. [S1]")
        with patch.object(context_embeddings, "encoder", side_effect=ValueError("Lexical search only")):
            self.assertEqual(product_intake.recall(self.work)["status"], "open")
        self.topic("customers")
        self.populate(self.child, "Area users and workflow", "- Fact: The team holds a daily stand-up at ten. [S1]\n"
                      "- Fact: The team discussed customers over lunch. [S1]")
        self.assertEqual(product_intake.recall(self.work)["status"], "open")
        self.topic("performance")
        self.populate(self.child, "Goals, performance, and gaps",
                      "- Fact: The team has a goal to improve weekly retention. [S1]")
        self.assertEqual(product_intake.recall(self.work)["status"], "open")

    def test_company_claim_about_another_product_does_not_answer_customer_question(self):
        self.topic("customers")
        records.create(self.root, "company-context", layout.COMPANY)
        self.populate(layout.COMPANY, "Customers and markets",
                      "- Fact: Customers of Notebooks buy paper maps at kiosks. [S1]")
        self.plan(layout.COMPANY)
        self.change("approve")
        self.assertEqual(product_intake.recall(self.work)["status"], "open")
        self.populate(layout.COMPANY, "Customers and markets",
                      "- Fact: Customers across all products are hospital administrators. [S1]")
        result = product_intake.recall(self.work)
        self.assertEqual(result["status"], "candidate")
        self.assertEqual(result["evidence"]["scope"], "company")

    def test_confirmed_absence_of_product_keeps_recall_open(self):
        context_capture.write_remit(self.work, {"status": "draft", "follow": [], "responsibilities": []})
        self.assertEqual(product_intake.recall(self.work)["status"], "select_scope")
        onboarding_review.select_product(self.work, {"revision": onboarding_review.status(self.work)["revision"],
                                          "subject": None, "pm_reply": "I have not been assigned a product."})
        result = product_intake.recall(self.work)
        self.assertEqual(result["status"], "open")
        self.assertIsNone(result["evidence"])

    def test_body_semantics_can_recover_different_terminology(self):
        self.topic("business-value")
        self.populate(self.parent, "The product",
                      "- Fact: Our commercial model depends on yearly licensing agreements. [S1]")
        self.plan(self.parent)
        self.change("approve")
        result = product_intake.recall(self.work)
        self.assertEqual(result["status"], "candidate")
        self.assertIn("licensing agreements", result["evidence"]["text"])
