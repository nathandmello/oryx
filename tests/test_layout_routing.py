"""Purpose-first filing through the same CLI used by agents."""

import json
from pathlib import Path
import subprocess
import sys
import unittest

import test_pm
import filing
import layout
import pm


class PurposeRoutingTests(unittest.TestCase):
    setUp = test_pm.HubTests.setUp

    def cli(self, *args, payload=None, ok=True):
        run = subprocess.run([sys.executable, str(self.root / "tools/pm.py"), *args], cwd=self.root,
                             input=json.dumps(payload), capture_output=True, text=True)
        self.assertEqual(run.returncode == 0, ok, run.stdout + run.stderr)
        return run.stdout

    def note(self, subject, *extra, ok=True):
        return self.cli("new", "context-note", "context/company/" + subject,
                        "--parent", layout.COMPANY, "--basis", "maintained-reference",
                        "--reason", "Managers consult the approved guidance weekly.",
                        "--trigger", "Legal issues revised guidance.", *extra, ok=ok)

    def test_topic_contract_across_creation_router_and_check(self):
        self.cli("new", "company-context", layout.COMPANY)
        peer = "context/company/cross-border-guidance.md"
        self.note("cross-border-guidance.md")
        to = "context/company/jurisdictions/domestic-guidance.md"
        flags = ["--topic-question", "Which rules apply to each jurisdiction?", "--topic-peer", peer]
        self.note("jurisdictions/domestic-guidance.md", ok=False)
        self.assertFalse((self.work / to).parent.exists())
        fake = {"scope": "company", "record": {"path": "context/company/board-notice/refund-policy.md",
                "parent": layout.COMPANY, "basis": "maintained-reference", "reason": "Review national policy.",
                "trigger": "The regulator changes policy.", "topic_peer": peer, "topic_question": flags[1]},
                "source": 1, "location": "Section A", "quote": "Refunds require a receipt."}
        batch = {"entries": [fake], "sources": [{"reference": "Board notice", "coverage": "read",
                                                 "date": "undated", "checked_on": "2025-01-01"}]}
        self.assertIn("source", self.cli("route-context", payload=batch, ok=False))
        self.note("jurisdictions/domestic-guidance.md", *flags)
        self.note("regulation/international-guidance.md", *flags, ok=False)
        self.note("jurisdictions/cross-border-guidance.md", ok=False)
        self.note("jurisdictions/local/methods.md", ok=False)
        for label in ("notes", "stuff", "uncategorized", "uncategorised", "unfiled", "everything", "catch-all"):
            self.note(f"{label}/federal-guidance.md", *flags, ok=False)
        self.note("fy2026/federal-guidance.md", *flags, ok=False)
        self.note("jurisdictions/municipal-guidance.md")
        owner = layout.COMPANY
        record = {"path": "context/company/jurisdictions/national-guidance.md", "parent": owner,
                  "basis": "maintained-reference", "reason": "Review the national rule monthly.",
                  "trigger": "The regulator publishes a rule."}
        row = {"scope": "company", "record": record, "question": "Which law governs returns?"}
        payload = {"sources": [], "entries": [row]}
        response = json.loads(self.cli("route-context", "--write", record["path"], payload=payload))
        self.assertEqual(response["written"], record["path"])
        self.assertIn("| Founding peer |", (self.work / record["path"]).read_text())
        self.assertEqual(pm.check(self.root), [])
        for folder in ("awards", "ownership", "eligibility", "operations", "markets"):
            (self.work / "context/company" / folder).mkdir()
        self.note("team-structure/headcount.md", *flags, ok=False)
        (self.work / "context/company/uncategorised").mkdir()
        errors = filing.topic_structure_errors(self.work)
        self.assertTrue(any("uncategorised" in issue for issue in errors))
        self.assertTrue(any("6 topic" in issue for issue in errors))

    def test_qualified_initiative_ids_and_context_only_writes(self):
        self.cli("new", "company-context", layout.COMPANY)
        for product in ("billing", "retail"):
            self.cli("new", "product-context", layout.product(product))
        self.cli("new", "initiative-context", layout.initiative("renewals"), "--parent", layout.product("billing"))
        row = {"scope": "initiative", "initiative": "renewals", "product": "retail",
               "topic": "outcome", "question": "Which users are eligible?"}
        payload = {"sources": [], "entries": [row]}
        qualified = layout.initiative("renewals", "retail")
        preview = json.loads(self.cli("route-context", payload=payload))
        self.assertEqual(preview["entries"][0]["destination"], qualified)
        self.cli("route-context", "--write", qualified, payload=payload)
        legacy = json.loads(self.cli("route-context", payload={"sources": [], "entries": [dict(row, product="billing")]}))
        self.assertEqual(legacy["entries"][0]["destination"], layout.initiative("renewals"))
        work = "workspace/initiatives/renewals/plan.md"
        (self.work / work).parent.mkdir(parents=True)
        plan = ("# Renewals plan\n\n## Scope\n\nEligible renewals.\n\n"
                "## Evidence\n\nConfirm the start date.\n\n## Next action\n\nCheck the timeline.\n")
        (self.work / work).write_text(plan)
        row.update(product="billing", record={"path": work, "reason": "Read the active plan."},
                   source=1, location="Item 2", quote="Renewals start in March.")
        row.pop("question")
        source = {"reference": "Fictional plan", "date": "undated", "checked_on": "2025-01-01", "coverage": "read"}
        payload = {"sources": [source], "entries": [row]}
        preview = json.loads(self.cli("route-context", payload=payload))
        self.assertIsNone(preview["entries"][0]["section"])
        self.cli("route-context", "--write", work, payload=payload, ok=False)
        self.assertEqual((self.work / work).read_text(), plan)
        self.assertEqual(pm.check(self.root), [])
