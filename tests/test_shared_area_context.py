"""Verified product relationships can retrieve an area's evidence without assigning ownership."""

import json
import unittest
from unittest.mock import patch

import test_pm
from onboarding_fixtures import reviewed_studio
import evidence_reviews
import filing
import layout
import records
import task_context


class SharedAreaContextTests(unittest.TestCase):
    setUp = test_pm.HubTests.setUp
    capture = test_pm.HubTests.context_capture

    def create(self, kind, path):
        contract = None
        if kind == "product-area-context":
            product, _, _ = layout.area_identity(path)
            contract = filing.area_contract(self.work, path, layout.product(product), None,
                                            "Support checks this connector each week.", "The sync contract changes.")
        return records.create(self.root, kind, path, path.split("/")[-2].title(), filing_contract=contract)

    def record(self, product, quote, destination, **fields):
        entry = dict(scope="product", product=product, topic="offer", source=1, location="Section 1", quote=quote, **fields)
        ref = dict(reference="Platform review for " + product, date="undated", checked_on="2025-06-11", coverage="read", text=quote)
        result = self.capture(dict(sources=[ref], entries=[entry]), "--write", destination)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def setup_shared(self):
        reviewed_studio(self.root, self.work)
        self.create("company-context", layout.COMPANY)
        self.home, self.consumer = layout.product("analytics"), layout.product("billing")
        self.area = layout.area("analytics", "salesforce", "plugins")
        self.create("product-context", self.home)
        self.create("product-context", self.consumer)
        plugin = self.create("product-area-context", self.area)
        plugin.write_text(plugin.read_text().replace("# Salesforce\n", "# CRM Connector\n"))
        self.subject = "product/analytics/area/salesforce"
        self.ref = "Billing uses the Salesforce plugin maintained by Analytics."
        self.detail = "The connector syncs renewal records for the pilot merchants."
        self.parent_fact = "Analytics sends weekly reports to the investor committee."
        self.record("analytics", self.parent_fact, self.home)
        self.record("analytics", self.detail, self.area, product_area="salesforce")
        self.record("billing", self.ref, self.consumer, shared_area=self.subject)

    def resolve(self, prompt="", **scope):
        return task_context.resolve(self.work, prompt, explicit=scope or None)

    def test_read_only_consumer_receives_cited_shared_area_and_no_foreign_parent(self):
        self.setup_shared()
        import context_capture
        direct = context_capture.area_context(self.work, "billing", "salesforce")
        self.assertEqual(direct["area_brief"], self.area)
        self.assertEqual(direct["product_briefs"], [self.consumer])
        for result in (self.resolve("For Billing, what does Salesforce sync?"),
                       self.resolve("What does the CRM Connector sync for Billing?"),
                       self.resolve("What does this connector sync?", product="billing", area="salesforce")):
            with self.subTest(scope=result["scope"]):
                self.assertEqual(result["scope"]["product"], "billing")
                self.assertEqual(result["scope"]["area"], "salesforce")
                shared = result["shared_area"]
                self.assertEqual(shared["subject"], self.subject)
                self.assertEqual(shared["relationship"]["record"], self.consumer)
                self.assertIn(self.ref, shared["relationship"]["text"])
                self.assertEqual(shared["relationship"]["sources"][0]["Source"], "Platform review for billing")
                row = next(row for row in result["entries"] if self.detail in row["text"])
                self.assertEqual((row["record"], row["applies_within"]), (self.area, self.subject))
                self.assertEqual(row["sources"][0]["Source"], "Platform review for analytics")
                self.assertNotIn(self.parent_fact, json.dumps(result))
        local = self.resolve("Show current policies", product="billing")
        self.assertNotIn("shared_area", local)
        self.assertNotIn(self.detail, json.dumps(local))

    def test_expired_or_unqualified_relationship_cannot_follow_the_area(self):
        self.setup_shared()
        result = self.resolve("What synced as of 2025-06-10?", product="billing", area="salesforce")
        self.assertNotIn("shared_area", result)
        self.assertNotIn(self.detail, json.dumps(result))
        path = self.work / self.consumer
        original = path.read_text()
        path.write_text(original.replace("  Shared area:", "  Open question at capture: Is this the same plugin?\n  Shared area:"))
        result = self.resolve("Which records sync?", product="billing", area="salesforce")
        self.assertNotIn("shared_area", result)
        self.assertNotIn(self.detail, json.dumps(result))
        path.write_text(original)
        with patch.object(task_context.upgrades, "source_paths", return_value={self.area}):
            archived = self.resolve(product="billing", area="salesforce")
        self.assertEqual(archived["status"], "ambiguous")
        self.assertNotIn(self.detail, json.dumps(archived))
        (self.work / self.area).unlink()
        result = self.resolve("Which records sync?", product="billing", area="salesforce")
        self.assertEqual(result["status"], "ambiguous")
        self.assertFalse(result["entries"])
        self.assertTrue(result["warnings"])

    def test_consumer_cannot_write_through_the_link_or_guess_between_namesakes(self):
        self.setup_shared()
        ref = dict(reference="Operations interview", date="undated", checked_on="2025-06-12", coverage="read")
        entry = dict(scope="product", product="billing", product_area="salesforce", topic="offer",
                     source=1, location="Interview", quote="The connector syncs nightly.")
        result = self.capture(dict(sources=[ref], entries=[entry]), "--write", self.area)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn(entry["quote"], (self.work / self.area).read_text())
        # A local brief with the same name describes a separate entity.
        own_area = layout.area("billing", "salesforce", "components")
        self.create("product-area-context", own_area)
        result = self.resolve("Which records sync?", product="billing", area="salesforce")
        self.assertEqual(result["status"], "ambiguous")
        self.assertEqual(set(result["choices"]), {self.subject, "product/billing/area/salesforce"})
        self.assertFalse(result["entries"])
        # The PM can still file against the explicitly identified, existing local namesake.
        self.record("billing", entry["quote"], own_area, product_area="salesforce", area_group="components")
        self.assertNotIn(entry["quote"], (self.work / self.area).read_text())

    def test_contested_link_or_canonical_finding_retains_its_evidence_limits(self):
        self.setup_shared()
        result = self.resolve("What syncs?", product="billing", area="salesforce")
        shared = result["shared_area"]
        local = next(row for row in result["entries"] if self.detail in row["text"])
        for row, quote, product, area in ((local, self.detail, "analytics", "salesforce"),
                                           (shared["relationship"], self.ref, "billing", None)):
            event = {"id": evidence_reviews.identifier(quote), "state": "open", "on": "2025-06-12",
                     "reason": "Conflicting descriptions need a review.", "classification": "potential conflict",
                     "targets": [], "scope": {"product": product, "area": area, "initiative": None},
                     "claims": [{"text": quote, "section": row["section"], "record": row["record"]}]}
            owner = self.work / row["record"]
            owner.write_text(evidence_reviews.append(owner.read_text(), [event]))
            now = self.resolve("What syncs?", product="billing", area="salesforce")
            if area:
                found = next(entry for entry in now["entries"] if self.detail in entry["text"])
                self.assertEqual(found["evidence_status"], "under review")
                self.assertIn(event["id"], found["risk_reviews"])
            else:
                self.assertEqual(now["status"], "ambiguous")
                self.assertFalse(now["entries"])
                self.assertIn(event["id"], now["warnings"][0])
        before = self.resolve("What synced as of 2025-06-11?", product="billing", area="salesforce")
        self.assertEqual(before["shared_area"]["subject"], self.subject)
