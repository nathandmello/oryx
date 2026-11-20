"""Guard signed records from the unpublished format-1 opportunity workflow."""

import hashlib
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import initiative_store
import layout_upgrade
import upgrades


class OpportunityUpgradeTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name).resolve()
        self.private = self.home / "workspace"
        subprocess.run(["git", "init", "--quiet", str(self.private)], check=True)
        upgrades.fresh(self.private)
        self.register = self.private / "products/orders/initiatives.json"
        self.register.parent.mkdir(parents=True)
        self.company = self.private / "context/company.md"
        self.company.parent.mkdir(parents=True)
        self.company.write_bytes(b"<!-- pm: company-context -->\r\n# Company\r\n")
        self.product = self.register.parent / "context.md"
        self.product.write_bytes(b"<!-- pm: product-context -->\r\n# Orders\r\n")
        self.brief = self.register.parent / "initiatives/renewal/initiative-brief.md"
        self.brief.parent.mkdir(parents=True)
        self.brief.write_bytes(b"<!-- pm: initiative-brief -->\r\n# Renewal\r\n[Goal](../../goal.md)\r\n")
        self.goal = self.register.parent / "goal.md"
        self.goal.write_text("<!-- pm: goal -->\n# Goal\n## Work state\n\n| ID | renewals-goal |\n")

    def envelope(self):
        item = "orders-test/renewal"
        date = "2025-01-01"
        decision = {"type": "decision", "initiative": item, "on": date,
                    "reason": "The PM reviewed renewal risk.", "source": "PM review"}
        record = {"version": 1, "product": "orders", "events": [
            {"type": "setup", "company": "context/company.md", "product_context": "products/orders/context.md",
             "max_open": 5, "max_discovery": 2,
             "references": {"company_id": "company-test", "product_id": "orders-test"}},
            {"type": "capture", "initiative": item, "title": "Renew earlier", "source": "Renewal report",
             "observed_on": date, "summary": "Administrators missed renewal dates."},
            {"type": "describe", "initiative": item, "problem": "Missed renewals", "audience": "Administrators",
             "outcome": "Renew on time", "source": "Renewal report"},
            {**decision, "action": "evaluate", "evaluation": "Late renewals create avoidable service gaps."},
            {**decision, "action": "prepare-brief", "references": {}},
            {"type": "metric", "metric": "rate", "name": "Renewal rate", "definition": "On-time renewals",
             "unit": "percent", "source": "Metric guide"},
            {"type": "target", "initiative": item, "metric": "rate", "baseline": "70 percent", "target": "75 percent",
             "due": date, "guardrails": "Track cancellations", "source": "PM review"},
            {**decision, "action": "approve-initiative",
             "references": {"id": "brief-test", "path": self.brief.relative_to(self.private).as_posix(),
                            "sha256": hashlib.sha256(self.brief.read_bytes()).hexdigest()}},
        ]}
        key = self.home / "signing-key"
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)], check=True)
        payload = json.dumps(record, sort_keys=True, separators=(",", ":")).encode()
        signature = subprocess.run(["ssh-keygen", "-Y", "sign", "-f", str(key), "-n", "pm-hub-initiatives"],
                                   input=payload, capture_output=True, check=True).stdout.decode()
        return {"record": record, "signature": signature}

    def files(self):
        return {p.relative_to(self.private): p.read_bytes() for p in self.private.rglob("*")
                if p.is_file() and ".git" not in p.relative_to(self.private).parts}

    def test_detects_private_signed_data_before_rewriting_any_references(self):
        envelope = self.envelope()
        self.register.write_text(json.dumps(envelope))
        with (self.private / ".git/info/exclude").open("a") as excluded:
            excluded.write("\nproducts/orders/initiatives.json\n")
        before = self.files()
        self.assertEqual(layout_upgrade.legacy_initiative_registers(self.private), [self.register])
        for apply in (False, True):
            with self.assertRaisesRegex(ValueError, "products/orders/initiatives.json"):
                layout_upgrade.run(self.private, apply=apply)
            self.assertEqual(self.files(), before)
        self.assertFalse(layout_upgrade.pending(self.private))
        approved_digest = envelope["record"]["events"][-1]["references"]["sha256"]
        self.assertEqual(hashlib.sha256(self.brief.read_bytes()).hexdigest(), approved_digest)

    def test_already_relocated_workspace_cannot_start_a_second_register(self):
        self.register.write_text(json.dumps(self.envelope()))
        self.private.rename(self.home / "studio")
        self.private = self.home / "studio"
        before = self.files()
        setup = {"type": "setup", "company": "context/company/overview.md",
                 "product_context": "context/products/orders/overview.md", "max_open": 5, "max_discovery": 2}
        with self.assertRaisesRegex(ValueError, "products/orders/initiatives.json"):
            initiative_store.prepare(self.home, "orders", [setup])
        with self.assertRaisesRegex(ValueError, "products/orders/initiatives.json"):
            list(initiative_store.registrations(self.home))
        self.assertFalse((self.private / "workspace/backlogs/orders/initiatives.json").exists())
        self.assertEqual(self.files(), before)

    def test_unrelated_json_and_signed_source_copy_preserve_the_published_upgrade(self):
        self.register.write_text(json.dumps({"product": "orders", "initiatives": ["renewal"]}))
        source = self.register.parent / "sources/initiatives.json"
        source.parent.mkdir()
        source.write_text(json.dumps(self.envelope()))
        catalog = self.private / "products/catalog/context.md"
        catalog.parent.mkdir(parents=True)
        catalog.write_text("<!-- pm: product-context -->\n# Catalog\n")
        original, cited = self.register.read_bytes(), source.read_bytes()
        self.assertEqual(layout_upgrade.legacy_initiative_registers(self.private), [])
        preview = layout_upgrade.run(self.private)
        self.assertEqual(preview["moves"]["products/catalog/context.md"], "context/products/catalog/overview.md")
        layout_upgrade.run(self.private, apply=True)
        self.assertTrue((self.private / "context/products/catalog/overview.md").is_file())
        self.assertEqual(self.register.read_bytes(), original)
        self.assertEqual(source.read_bytes(), cited)
