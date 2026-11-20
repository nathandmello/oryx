"""Capture only confirmed stakeholder facts and retrieve them within their own context."""

from datetime import date
import json
import unittest

import test_pm
import layout
import records
import task_context
from onboarding_fixtures import reviewed_studio


class StakeholderTests(unittest.TestCase):
    setUp = test_pm.HubTests.setUp
    capture = test_pm.HubTests.context_capture

    def test_preview_capture_resume_and_lookup_preserve_scope(self):
        reviewed_studio(self.root, self.work)
        today = date.today().isoformat()
        reporting = "The Billing PM reports to the Group PM this quarter."
        authority = "For Billing renewals, the PM recommends the price and Finance approves it."
        source = {"reference": "PM discussion of the Billing remit", "date": today, "checked_on": today,
                  "coverage": "read", "text": reporting + "\n" + authority}
        entries = [
            {"scope": "stakeholder", "topic": "reporting", "source": 1, "location": "First reply", "quote": reporting},
            {"scope": "stakeholder", "topic": "authority", "source": 1, "location": "Second reply", "quote": authority},
            {"scope": "stakeholder", "topic": "collaboration", "question": "Who advises on Billing renewals?"},
        ]
        data = {"sources": [source], "entries": entries}
        preview = self.capture(data)
        self.assertEqual(preview.returncode, 0, preview.stderr + preview.stdout)
        plan = json.loads(preview.stdout)
        self.assertEqual({row["destination"] for row in plan["entries"]}, {layout.STAKEHOLDERS})
        path = self.work / layout.STAKEHOLDERS
        self.assertFalse(path.exists())
        pm_profile = self.work / layout.PROFILE
        pm_profile.parent.mkdir(parents=True, exist_ok=True)
        legacy = "# PM context\n\n## PM stakeholders\n\nLegacy stakeholder note.\n"
        pm_profile.write_text(legacy)

        saved = self.capture(data, "--write", layout.STAKEHOLDERS)
        self.assertEqual(saved.returncode, 0, saved.stderr + saved.stdout)
        snapshot = path.read_bytes()
        self.assertIn(reporting, snapshot.decode())
        self.assertIn("## Decision roles", snapshot.decode())
        retry = self.capture(data, "--write", layout.STAKEHOLDERS)
        self.assertEqual(retry.returncode, 0, retry.stdout + retry.stderr)
        self.assertEqual(path.read_bytes(), snapshot)
        self.assertEqual(pm_profile.read_text(), legacy)
        found, state = task_context.turn_context(self.work, "Show my stakeholder map.")
        self.assertEqual(found["scope"], {"stakeholders": True})
        self.assertTrue(any(layout.PROFILE in warning for warning in found["warnings"]))
        self.assertNotIn("Legacy stakeholder note", str(found["entries"]))
        later, _ = task_context.turn_context(self.work, "What about Finance?", saved=state)
        self.assertEqual(later["scope"], found["scope"])
        row = next(r for r in later["entries"] if authority in r["text"])
        self.assertEqual(row["sources"][0]["Source"], source["reference"])
        by_path = task_context.resolve(self.work, f"Read {layout.STAKEHOLDERS}")
        self.assertEqual(by_path["scope"], found["scope"])
        records.create(self.root, "product-context", layout.product("billing"), "Billing")
        work = task_context.resolve(self.work, "Compare Billing rollout options with stakeholders")
        self.assertEqual(work["scope"]["product"], "billing")
        self.assertNotIn(layout.STAKEHOLDERS, {r["record"] for r in work["entries"]})
        company = task_context.resolve(self.work, "Show company context.")
        self.assertNotIn(layout.STAKEHOLDERS, {r["record"] for r in company["entries"]})

    def test_stakeholder_lookup_without_map_keeps_relationship_unknown(self):
        result = task_context.resolve(self.work, "Who does the PM report to?")
        self.assertEqual(result["entries"], [])
        self.assertIn(f"No readable stakeholder map was found at {layout.STAKEHOLDERS}.", result["warnings"])
        self.assertFalse((self.work / layout.STAKEHOLDERS).exists())

    def test_uncertain_stakeholder_authority_stays_with_the_map(self):
        reviewed_studio(self.root, self.work)
        today = date.today().isoformat()
        fact = "Finance advises on Billing renewals."
        source = {"reference": "Renewals discussion with the PM", "date": today, "checked_on": today,
                  "coverage": "read", "text": fact}
        packet = {"sources": [source], "entries": [
            {"scope": "stakeholder", "topic": "authority", "source": 1, "location": "PM reply", "quote": fact,
             "risk": {"reason": "The approver for renewal exceptions still needs confirmation."}}]}
        saved = self.capture(packet, "--write", layout.STAKEHOLDERS)
        self.assertEqual(saved.returncode, 0, saved.stderr + saved.stdout)
        risk, = json.loads(saved.stdout)["risk_events"]
        by_id = task_context.resolve(self.work, f"Review {risk['id']}.")
        self.assertEqual(by_id["scope"], {"stakeholders": True})
        self.assertEqual({r["id"] for r in by_id["risks"]}, {risk["id"]})
        self.assertNotIn(risk["id"], str(task_context.resolve(self.work, "Show company context.")))

    def test_named_approval_questions_use_the_product_and_its_stakeholder_evidence(self):
        reviewed_studio(self.root, self.work)
        today = date.today().isoformat()
        billing = "Finance approves Billing renewals up to the current threshold."
        shipping = "Operations approves Shipping renewals for the pilot."
        unknown = "One VP approves renewals for an unnamed team."
        limit = "Billing renewals above the threshold need a separate exception review."
        source = {"reference": "PM discussion of renewal responsibilities", "date": today, "checked_on": today,
                  "coverage": "read", "text": "\n".join([billing, shipping, unknown, limit])}
        entries = [{"scope": "stakeholder", "topic": "authority", "source": 1, "location": "PM account", "quote": fact}
                   for fact in (billing, shipping, unknown)]
        entries[2]["location"] = "Billing and Shipping discussion, third reply"
        entries[1]["risk"] = {"reason": "The Shipping pilot's temporary approver needs confirmation."}
        data = {"sources": [source], "entries": entries}
        result = self.capture(data, "--write", layout.STAKEHOLDERS)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        data["entries"] = [{"scope": "product", "product": "billing", "topic": "constraints", "source": 1,
                            "location": "Exception policy", "quote": limit}]
        result = self.capture(data, "--write", layout.product("billing"))
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        _, map_state = task_context.turn_context(self.work, "Show my stakeholder map.")
        for prompt, saved in (("Who approves Billing renewals?", {}),
                              ("Who approves Billing renewals?", map_state),
                              ("What about Billing renewals?", map_state)):
            with self.subTest(prompt=prompt, from_map=bool(saved)):
                result, _ = task_context.turn_context(self.work, prompt, saved=saved)
                self.assertEqual(result["scope"]["product"], "billing")
                self.assertTrue(result["scope"]["stakeholders"])
                rows = {row["record"]: row for row in result["entries"] if billing in row["text"] or limit in row["text"]}
                self.assertEqual(set(rows), {layout.STAKEHOLDERS, layout.product("billing")})
                self.assertEqual(rows[layout.STAKEHOLDERS]["sources"][0]["Source"], source["reference"])
                self.assertNotIn(shipping, str(result))
                self.assertNotIn(unknown, str(result))
                self.assertNotIn("temporary approver", str(result))
        for scoped in (task_context.resolve(self.work, "Who approves renewals?", explicit={"product": "billing"}),
                       task_context.resolve(self.work, "Who approves renewals for product/billing?")):
            self.assertIn(billing, str(scoped["entries"]))
            self.assertNotIn(unknown, str(scoped["entries"]))
        ordinary, _ = task_context.turn_context(self.work, "Prepare a Billing renewals update for stakeholders.", saved=map_state)
        self.assertNotIn("stakeholders", ordinary["scope"])
        self.assertNotIn(layout.STAKEHOLDERS, str(ordinary["entries"]))
