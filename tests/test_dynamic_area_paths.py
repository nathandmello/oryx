"""The same stable subject resolves independently of the team's folder vocabulary."""
import shutil
import unittest

import test_pm
import context_capture as capture
import filing
import layout
import pm
import records
import task_context


class DynamicAreaTests(unittest.TestCase):
    setUp = test_pm.HubTests.setUp

    def new_product(self):
        records.create(self.root, "company-context", layout.COMPANY)
        records.create(self.root, "product-context", layout.product("payments"))

    def finding(self, area, group, quote):
        entry = dict(scope="product", product="payments", product_area=area, topic="contribution",
                     source=1, location="Operating review", quote=quote)
        if group is not None:
            entry["area_group"] = group
        source = dict(reference="Pilot interview", coverage="read", date="2025-05-01", checked_on="2025-05-02",
                      text=quote)
        return capture.route(dict(sources=[source], entries=[entry]), self.work, None, single_excerpt=True)

    def test_capture_lookup_and_retrieval_share_home(self):
        quote = "Our team agreed success means fewer refund status contacts per merchant."
        with self.assertRaisesRegex(ValueError, "area_group"):
            self.finding("refunds", None, quote)
        plan = self.finding("refunds", "plugins", quote)
        dest = layout.area("payments", "refunds", "plugins")
        self.assertEqual(plan["entries"][0]["destination"], dest)
        self.assertEqual(plan["entries"][0]["section"], "Area outcomes")
        self.assertFalse((self.work / dest).exists())
        self.new_product()
        capture.apply(self.root, dest, plan, "Fixture PM", pm.capture_errors)
        text = (self.work / dest).read_text()
        self.assertTrue(text.startswith("<!-- pm: product-area-context -->"))
        self.assertIn(quote, text)
        self.assertEqual(records.parent_reference(dest, text), layout.product("payments"))
        self.assertEqual(self.finding("refunds", None, quote)["entries"][0]["destination"], dest)
        self.assertEqual(capture.area_context(self.work, "payments", "refunds")["area_brief"], dest)
        receipts = self.finding("receipts", "components", "Receipt delivery is measured within a day.")
        receipt_home = receipts["entries"][0]["destination"]
        capture.apply(self.root, receipt_home, receipts, "Fixture PM", pm.capture_errors)
        result = task_context.resolve(self.work, "Did Refunds get better?")
        self.assertEqual(result["scope"]["area"], "refunds")
        self.assertTrue(any(row["record"] == dest and row["sources"] for row in result["entries"]))
        self.assertFalse(any(row["record"] == receipt_home for row in result["entries"]))
        self.assertEqual(filing.topic_directories(self.work, layout.entity(dest).parents[1]), [])

    def test_duplicate_homes_require_resolution_and_legacy_paths_stay_in_place(self):
        self.new_product()
        quote = "Refunds are available for damaged purchases."
        old = layout.area("payments", "refunds")
        plan = self.finding("refunds", "areas", quote)
        capture.apply(self.root, old, plan, "Fixture PM", pm.capture_errors)
        with self.assertRaisesRegex(ValueError, "Reuse the existing"):
            self.finding("refunds", "plugins", quote)
        self.assertEqual(records.area_brief_path("payments", "refunds", private=self.work), old)
        dup = self.work / layout.area("payments", "refunds", "plugins")
        dup.parent.mkdir(parents=True)
        shutil.copyfile(self.work / old, dup)
        with self.assertRaisesRegex(ValueError, "Multiple homes"):
            self.finding("refunds", None, quote)
        result = task_context.resolve(self.work, "Did Refunds get better?")
        self.assertEqual(result["status"], "ambiguous")
        self.assertEqual(result["entries"], [])
        self.assertIn("Multiple homes", result["warnings"][0])

    def test_group_cannot_consume_a_topic_or_reserved_directory(self):
        for name in ("sources", "secrets", "initiatives", "..", "team/plugins", ".private"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                layout.area("payments", "refunds", name)
        product = self.work / layout.product("payments")
        topic = product.parent / "contracts" / "partner-terms.md"
        topic.parent.mkdir(parents=True)
        topic.write_text("Existing product note")
        with self.assertRaisesRegex(ValueError, "existing topic"):
            self.finding("refunds", "contracts", "Refunds require an invoice.")
        self.assertEqual(topic.read_text(), "Existing product note")
        old = product.parent / "casework" / "active" / "notes.md"
        old.parent.mkdir(parents=True)
        old.write_text("<!-- pm: context-note -->\n# Historical case\n")
        with self.assertRaisesRegex(ValueError, "conflicts with existing material"):
            self.finding("refunds", "casework", "Refunds require an invoice.")
        self.assertNotIn(old.relative_to(self.work).as_posix(), task_context.context_documents(self.work))
