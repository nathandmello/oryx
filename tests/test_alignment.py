"""Regression cases for old consumers, concurrent writers, and literal evidence."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from hashlib import sha256
import json
from pathlib import Path
import re
import threading
import unittest

import test_pm
import context_capture
import hook
import pm
import records
import storage
import upgrades


class AlignmentTests(unittest.TestCase):
    setUp = test_pm.HubTests.setUp
    capture = test_pm.HubTests.context_capture

    def test_installed_review_resumes_and_preserves_custom_work(self):
        ledger = self.work / upgrades.LEDGER
        ledger.unlink()
        settings = self.work / "settings.json"
        previous = json.loads(settings.read_text())
        previous["system_version"] = "0.1.0"
        settings.write_text(json.dumps(previous))
        guide = self.work / "README.md"
        old, new = upgrades.STARTERS["README.md"]
        guide.write_bytes((old + "\r\n\r\nPM checkpoint: interview on Friday.\r\n").encode())
        doc = self.work / "context/company.md"
        doc.write_text("Company standing commitments.\n")
        sidecar = self.work / "context/company-audit.md"
        sidecar.write_text("This audit contains a decision awaiting confirmation.\n")
        preview = pm.alignment(self.root)
        self.assertTrue(preview["needs_setup"])
        self.assertFalse(ledger.exists())
        self.assertIn("0.1.0", settings.read_text())
        self.assertEqual({item["path"] for item in preview["outstanding"]},
                         {"context/company.md", "context/company-audit.md", "README.md"})
        first = pm.alignment(self.root, prepare=True)
        self.assertEqual(first["updated_guides"], ["README.md"])
        self.assertIn(new.encode(), guide.read_bytes())
        self.assertTrue(guide.read_bytes().endswith(b"PM checkpoint: interview on Friday.\r\n"))
        self.assertTrue(any(old.encode() in path.read_bytes()
                            for path in (self.work / ".git/pm-hub-recovery").rglob("README.md")))
        self.assertEqual(json.loads(settings.read_text())["system_version"], "0.2.0")
        self.assertEqual(pm.alignment(self.root)["outstanding"], first["outstanding"])
        digest = sha256(doc.read_bytes()).hexdigest()
        backed = pm.alignment(self.root, prepare=True, backup=["context/company.md"])
        self.assertEqual((self.work / backed["backups"]["context/company.md"]).read_bytes(), doc.read_bytes())
        doc.write_text("Edited while the earlier review was open.\n")
        with self.assertRaisesRegex(ValueError, "changed since review"):
            pm.alignment(self.root, True, "context/company.md", "reviewed", digest, "Verified original minutes.")
        digest = sha256(doc.read_bytes()).hexdigest()
        pm.alignment(self.root, True, "context/company.md", "reviewed", digest, "Verified original minutes.")
        custom = next(item for item in pm.alignment(self.root)["outstanding"] if item["path"] == "README.md")
        pm.alignment(self.root, True, "README.md", "reviewed", custom["digest"], "Retained the PM checkpoint after the guide update.")
        item = pm.alignment(self.root)["outstanding"][0]
        self.assertEqual(item["path"], "context/company-audit.md")
        pm.alignment(self.root, True, item["path"], "waiting", item["digest"], "Waiting for approved minutes.")
        self.assertEqual(pm.alignment(self.root)["outstanding"][0]["status"], "waiting")
        pm.alignment(self.root, True, item["path"], "reviewed", item["digest"], "Retained as a dated company event.")
        before = ledger.read_bytes()
        self.assertEqual(pm.alignment(self.root, True)["outstanding"], [])
        self.assertEqual(ledger.read_bytes(), before)
        self.assertTrue(sidecar.exists())

    def test_same_preview_destination_required_including_sibling_initiatives(self):
        doc = records.create(self.root, "company-context", "context/company.md")
        other = records.create(self.root, "company-context", "context/unit-europe.md")
        question = {"scope": "company", "topic": "direction", "question": "What is the target?"}
        data = {"sources": [], "entries": [question]}
        before = other.read_bytes()
        self.assertEqual(json.loads(self.capture(data).stdout)["entries"][0]["destination"], "context/company.md")
        self.assertNotEqual(self.capture(data, "--write", "context/unit-europe.md").returncode, 0)
        self.assertEqual(other.read_bytes(), before)
        self.assertTrue(doc.exists())
        foreign = "products/shop/initiatives/returns/context.md"
        records.create(self.root, "initiative-context", foreign)
        data["entries"] = [dict(question, scope="initiative", product="shop", initiative="orders", topic="outcome",
                                record={"path": foreign, "reason": "Record the initiative outcome."})]
        self.assertNotEqual(self.capture(data).returncode, 0)

    def test_mixed_evidence_keeps_exclusions_dates_and_relative_links(self):
        path = self.work / "context/meeting notes.md"
        exclusion = "We will not enter the data centre business or create or own LLM models."
        positive = "We will rent capacity as required and use existing models."
        product = "Customers use invoices."
        path.write_text(exclusion + " " + positive + "\n\n" + product)
        source = {"reference": "[Minutes](context/meeting%20notes.md)", "date": "undated",
                  "coverage": "read", "checked_on": "2025-01-01"}
        row = {"scope": "company", "topic": "constraints", "source": 1, "location": "Minutes", "quote": positive}
        data = {"sources": [source], "entries": [row]}
        self.assertIn("entire commitment", self.capture(data).stdout)
        data["entries"].extend([dict(row, quote=exclusion),
                                dict(row, scope="product", product="shop", topic="customers", quote=product)])
        for name, relative in [("context/company.md", "meeting%20notes.md"),
                               ("products/shop/context.md", "../../context/meeting%20notes.md")]:
            result = self.capture(data, "--write", name)
            self.assertEqual(result.returncode, 0, result.stdout)
            self.assertIn(f"[Minutes]({relative})", (self.work / name).read_text())
        company = self.work / "context/company.md"
        self.assertIn(exclusion, company.read_text())
        source["checked_on"] = "2025-03-01"
        self.assertIsNone(json.loads(self.capture(data, "--write", "context/company.md").stdout)["written"])
        extra = "Procurement reviews the invoice."
        path.write_text(path.read_text() + "\n\n" + extra)
        data["entries"].append(dict(row, quote=extra))
        self.assertEqual(self.capture(data, "--write", "context/company.md").returncode, 0)
        self.assertTrue(all(day in company.read_text() for day in ("2025-01-01", "2025-03-01")))
        source.update(reference="Meeting minutes [S8]", text=path.read_text())
        self.assertEqual(self.capture(data, "--write", "context/company.md").returncode, 0)
        data["entries"][0]["quote"] = "Rewritten without source support."
        self.assertIn("differs from", self.capture(data).stdout)
        self.assertEqual(pm.check(self.root), [])

    def test_conjoined_obligations_route_without_dropping_negation_or_conditions(self):
        left = "The company will rent capacity"
        right = "Atlas must not retain evidence unless Legal approves."
        source = {"reference": "Approved policy", "coverage": "read", "date": "undated", "checked_on": "2025-01-01",
                  "text": f"{left}, and {right}"}
        rows = [{"scope": "company", "topic": "constraints", "quote": left, "source": 1, "location": "Policy"},
                {"scope": "product", "product": "atlas", "topic": "data-boundaries", "quote": right,
                 "source": 1, "location": "Policy"}]
        data = {"sources": [source], "entries": rows}
        result = self.capture(data)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(json.loads(result.stdout)["source_checks"][0]["commitment_sentences"], 1)
        for shortened in ("Atlas must", "retain evidence unless Legal approves.", "Atlas must not retain evidence"):
            rows[1]["quote"] = shortened
            self.assertNotEqual(self.capture(data).returncode, 0)
        rows[1].update(quote=right, rule="Atlas prefers approved evidence.")
        self.assertNotEqual(self.capture(data).returncode, 0)

    def test_legacy_brief_and_compact_state_rows(self):
        path = records.create(self.root, "product-context", "products/ledger/introduction.md")
        row = {"scope": "product", "product": "ledger", "topic": "offer", "source": 1, "location": "Page 1",
               "quote": "The ledger lists transfers."}
        data = {"sources": [{"reference": "Fictional ledger minutes", "date": "undated", "checked_on": "2025-01-01",
                             "coverage": "read"}], "entries": [row]}
        name = path.relative_to(self.work).as_posix()
        self.assertEqual(json.loads(self.capture(data).stdout)["entries"][0]["destination"], name)
        text = path.read_text().replace("| State | draft |", "|State|complete|")
        text = re.sub(r"^\| Last checkpoint \| .* \|$", "|Last checkpoint|2025-01-01: Accepted.|", text, flags=re.M)
        path.write_text(text)
        result = self.capture(data, "--write", name)
        self.assertEqual(result.returncode, 0, result.stdout)
        state = records.work_state(path.read_text())[0]
        self.assertEqual(state["State"], "draft")
        self.assertIn(date.today().isoformat(), state["Last checkpoint"])
        self.assertFalse((path.parent / "context.md").exists())
        records.create(self.root, "product-context", "products/ledger/another.md")
        self.assertEqual(json.loads(self.capture(data).stdout)["entries"][0]["disposition"], "ambiguous")

    def test_concurrent_hub_writers_reject_stale_input(self):
        path = self.work / "context/fixture.md"
        path.write_text("original")
        ready = threading.Barrier(2)
        def write(value):
            original = path.read_text()
            ready.wait(timeout=5)
            with storage.writer_lock(self.work):
                try:
                    storage.replace_text(path, original, value)
                except ValueError:
                    return "conflict"
            return value
        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(write, ("first", "second")))
        self.assertCountEqual(results, ["conflict", path.read_text()])

    def test_native_hook_recognises_typed_notes_among_ordinary_product_files(self):
        path = "products/shop/price.md"
        payload = {"tool_name": "Write", "tool_input": {"file_path": path, "content": "<!-- pm: context-note -->\n"}}
        self.assertTrue(hook.edit_guard(self.root, self.work, payload))
        payload = {"tool_name": "apply_patch", "tool_input": {"input": "*** Begin Patch\n*** Add File: " + path +
                   "\n+<!-- pm: context-note -->\n*** End Patch"}}
        self.assertTrue(hook.edit_guard(self.root, self.work, payload))
        payload["tool_input"]["input"] = payload["tool_input"]["input"].replace("<!-- pm: context-note -->", "# Work")
        self.assertTrue(hook.edit_guard(self.root, self.work, payload))

    def test_vocabulary_and_incompatible_remit(self):
        errors = records.context_table_errors("## Vocabulary\n| Term | Meaning | Owner | Avoid |\n| --- | --- | --- | --- |\n"
                                              "| Seat | Active user | Product | Account |\n", "Vocabulary", False)
        self.assertTrue(any("source reference in Meaning" in error for error in errors))
        settings = self.work / "settings.json"
        settings.write_text(settings.read_text().replace('"workspace_format": 1', '"workspace_format": 2'))
        result = test_pm.HubTests.save_remit(self, {"responsibilities": [], "follow": []})
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.work / context_capture.REMIT_PATH).exists())
