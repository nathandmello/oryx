"""Product-area ownership, scoped records and nonblocking remit onboarding."""

import json
from pathlib import Path
import subprocess
import sys
import unittest

import test_pm
import context_capture
import pm
import records


class ProductAreaTests(unittest.TestCase):
    setUp = test_pm.HubTests.setUp
    capture = test_pm.HubTests.context_capture
    save = test_pm.HubTests.save_remit
    run_hook = test_pm.HubTests.run_hook

    def cli(self, *args):
        return subprocess.run([sys.executable, str(self.root / "tools/pm.py"), *args],
                              cwd=self.root, text=True, capture_output=True, check=True).stdout

    @staticmethod
    def responsibility(subject, role="owner", dependencies=()):
        return {"subject": subject, "role": role, "goals": [], "depends_on": list(dependencies)}

    def startup(self):
        result = self.run_hook(json.dumps({"hook_event_name": "SessionStart", "cwd": str(self.root)}))
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]

    def test_hierarchy_and_confirmed_consequences(self):
        refunds = "product/checkout/area/refunds"
        receipts = "product/checkout/area/receipts"
        remit = {"responsibilities": [self.responsibility(refunds), self.responsibility(receipts, "shared"),
                                      self.responsibility("product/catalogue", dependencies=["product/tax"])],
                 "follow": ["product/payments/area/refunds", "product/search"]}
        routes = [
            ("checkout", "refunds", "owned"), ("checkout", "receipts", "shared"),
            ("checkout", "invoices", "fyi"), ("checkout", None, "fyi"),
            ("catalogue", "refunds", "owned"), ("elsewhere", "refunds", "fyi"),
            ("payments", "refunds", "following"), ("payments", "cards", "fyi"),
            ("search", "filters", "following"), ("tax", "rates", "dependency"),
        ]
        rows = [dict({"scope": "product", "product": product, "topic": "constraints", "question": "Which rule applies?"},
                     **({"product_area": area} if area else {})) for product, area, _ in routes]
        rows += [{"scope": "company", "topic": "constraints", "question": "When will the change take effect?",
                  "affects": {key: "The settlement date changes."}} for key in (refunds, "product/catalogue/area/search", "product/checkout")]
        self.assertEqual(self.save(remit).returncode, 0)
        preview = self.capture({"sources": [], "entries": rows})
        self.assertEqual(preview.returncode, 0, preview.stdout)
        got = json.loads(preview.stdout)["entries"]
        self.assertEqual([r["relevance"] for r in got], [want for _, _, want in routes] + ["affected", "affected", "company"])
        self.assertEqual([r["destination"] for r in got[:len(routes)]],
                         [f"products/{product}/context.md" for product, _, _ in routes])
        self.assertEqual(got[-3]["responsibilities"], [remit["responsibilities"][0]])

    def test_exact_area_role_wins_regardless_of_order(self):
        parent = self.responsibility("product/area")
        child = self.responsibility("product/area/area/refunds", "shared", ["product/other/area/credits"])
        for responsibilities in ([parent, child], [child, parent]):
            remit = {"responsibilities": responsibilities, "follow": []}
            for subject, expected in ((child["subject"], ("shared", [child])),
                                      ("product/area/area/invoices", ("owned", [parent])),
                                      ("product/other/area/credits", ("dependency", [child])),
                                      ("area/refunds", ("fyi", []))):
                self.assertEqual(context_capture.relevance(remit, subject, {}), expected)
            self.assertEqual(context_capture.relevance(remit, "company", {child["subject"]: "Delay."}), ("affected", [child]))
            both = context_capture.relevance(remit, "company", {child["subject"]: "Delay.", parent["subject"]: "Cost."})
            self.assertEqual(both, ("affected", responsibilities))

    def test_area_scope_survives_capture_answers_and_structured_rows(self):
        records.create(self.root, "company-context", "context/company.md")
        fact = {"scope": "product", "product": "shop", "product_area": "refunds", "topic": "constraints",
                "source": 1, "location": "Policy", "quote": "We will reimburse fees."}
        source = {"reference": "Fixture policy", "coverage": "read", "date": "undated", "checked_on": "2025-01-01"}
        question = {"scope": "product", "product": "shop", "topic": "constraints", "question": "Which fees?"}
        rows = [dict(question, product_area=area) for area in ("refunds", "receipts")]
        rows.extend([question, dict(question, question="Product area refunds — Which fees?")])
        name = "products/shop/context.md"
        def write(entries, dest=name):
            run = self.capture({"sources": [source], "entries": entries}, "--write", dest)
            self.assertEqual(run.returncode, 0, run.stdout)
            return json.loads(run.stdout)["written"]

        write(rows)
        write([dict(fact, answers=question["question"]), dict(fact, product_area="receipts"),
               dict(fact, topic="vocabulary", term={"name": "Fee", "owner": "Finance", "avoid": "Rate"}),
               dict(fact, topic="decisions", decision={"scope": "Pilot", "question": "Refund the fee?",
                    "person": "Finance PM", "date": "2025-01-01", "next_step": "Update the policy."})])
        self.assertIsNone(write([fact]))
        text = (self.work / name).read_text()
        self.assertNotIn("Unknown: Product area refunds — Which fees? <!--", text)
        self.assertIn("Unknown: Product area refunds — Which fees?\n", text)
        self.assertIn("Unknown: Product area receipts — Which fees?", text)
        self.assertIn("Unknown: Which fees?", text)
        self.assertIn("Fact: Product area refunds — Source excerpt", text)
        self.assertIn("Fact: Product area receipts — Source excerpt", text)
        self.assertIn("| Fee | Product area refunds — We will reimburse fees.", text)
        self.assertIn("| Refund the fee? | Product area refunds — Pilot <!-- product-area:refunds --> |", text)
        initiative = dict(fact, scope="initiative", initiative="returns", topic="constraints")
        dest = "products/shop/initiatives/returns/context.md"
        write([initiative], dest)
        self.assertIn("> We will reimburse fees.", (self.work / dest).read_text())
        self.assertEqual(sorted(p.relative_to(self.work).as_posix() for p in (self.work / "products/shop").rglob("*.md")),
                         [name, dest])
        self.assertEqual(pm.check(self.root), [])

    def test_invalid_areas_do_not_rewrite_existing_remits_or_create_records(self):
        old = {"responsibilities": [], "follow": ["area/refunds"]}
        self.assertEqual(self.save(old).returncode, 0)
        path = self.work / context_capture.REMIT_PATH
        before = path.read_bytes()
        for key in ("product/checkout/area/", "area/checkout/refunds", "product//area/refunds",
                    "product/checkout/area/../fees", "product/checkout/area/A"):
            result = self.save(dict(old, responsibilities=[self.responsibility(key)]))
            self.assertNotEqual(result.returncode, 0, key)
        self.assertNotEqual(self.save(dict(old, status="complete")).returncode, 0)
        self.assertEqual(path.read_bytes(), before)
        for scope, area in (("company", "refunds"), ("product", "../foo"), ("product", None)):
            row = {"scope": scope, "product_area": area, "topic": "constraints", "question": "Who approves refunds?"}
            if scope == "product":
                row["product"] = "checkout"
            self.assertNotEqual(self.capture({"sources": [], "entries": [row]}).returncode, 0)
        self.assertFalse((self.work / "products/checkout").exists())

    def test_new_and_existing_workspace_prompts(self):
        empty = {"responsibilities": [], "follow": []}
        whole = self.responsibility("product/shop")
        assigned = dict(empty, responsibilities=[whole])
        for remit, want in (
            (None, context_capture.REMIT_PROMPT), (empty, context_capture.REMIT_PROMPT),
            (dict(empty, follow=["area/pricing"]), context_capture.DRAFT_REMIT_PROMPT),
            (dict(assigned, status="draft"), context_capture.DRAFT_REMIT_PROMPT),
            (assigned, None), (dict(empty, status="confirmed"), None),
        ):
            path = self.work / context_capture.REMIT_PATH
            if remit is not None:
                self.assertEqual(self.save(remit).returncode, 0)
            before = path.read_bytes() if path.exists() else None
            guidance = self.startup()
            self.assertEqual(json.loads(self.cli("align", "--status")).get("remit_prompt"), want)
            if want:
                self.assertEqual(guidance.count(want), 1)
            else:
                self.assertNotIn(context_capture.REMIT_PROMPT, guidance)
                self.assertNotIn(context_capture.DRAFT_REMIT_PROMPT, guidance)
            self.assertEqual(path.read_bytes() if path.exists() else None, before)
            self.assertEqual(pm.check(self.root), [])
        self.work.rename(self.root.parent / "previous-private")
        self.assertNotIn(context_capture.REMIT_PROMPT, self.startup())
        self.assertIn(context_capture.REMIT_PROMPT, self.cli("init-workspace"))
        self.assertFalse((self.work / context_capture.REMIT_PATH).exists())

    def test_damaged_remit_is_reported_and_capture_preserves_it(self):
        path = self.work / context_capture.REMIT_PATH
        path.write_text('{"responsibilities":')
        original = path.read_bytes()
        self.assertIn("repairing", self.startup())
        question = {"scope": "product", "product": "shop", "product_area": "returns", "topic": "constraints",
                    "question": "What returns window applies?"}
        result = self.capture({"sources": [], "entries": [question]}, "--write", "products/shop/context.md")
        self.assertEqual(result.returncode, 0, result.stdout)
        plan = json.loads(result.stdout)
        self.assertEqual(plan["remit_status"], "invalid")
        self.assertTrue(plan["remit_error"])
        self.assertEqual(plan["entries"][0]["relevance"], "unknown")
        self.assertEqual(path.read_bytes(), original)
        self.assertTrue(any("pm-remit.json" in e for e in pm.check(self.root)))

    def test_old_install_preserves_remit_and_legacy_areas(self):
        path = self.work / context_capture.REMIT_PATH
        remit = {"responsibilities": [self.responsibility("area/checkout")], "follow": ["product/checkout"]}
        path.write_text(json.dumps(remit))
        settings = self.work / "settings.json"
        data = json.loads(settings.read_text())
        data["system_version"] = "0.2.0"
        settings.write_text(json.dumps(data))
        before = path.read_bytes()
        report = json.loads(self.cli("align"))
        self.assertTrue(Path(report["installation_backup"]).is_file())
        self.assertNotIn("remit_prompt", report)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(json.loads(settings.read_text())["system_version"], "0.3.0")
        self.assertEqual(context_capture.relevance(remit, "product/checkout/area/checkout", {}), ("following", []))
