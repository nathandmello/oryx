"""Consumer upgrade, evidence fidelity and filing tests in disposable Git workspaces."""

import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
import zipfile

import test_pm
import conversion
import pm
import records
import storage
import upgrades


class FilingTests(unittest.TestCase):
    setUp = test_pm.HubTests.setUp

    def cli(self, *args, data=None):
        return subprocess.run([sys.executable, str(self.root / "tools/pm.py"), *args], cwd=self.root,
                              input=json.dumps(data), text=True, capture_output=True)

    def start(self, event):
        hook = subprocess.run([sys.executable, str(self.root / "tools/hook.py")], cwd=self.root, text=True,
                              input=json.dumps({"hook_event_name": event}), capture_output=True)
        self.assertEqual(hook.returncode, 0, hook.stderr)
        return json.loads(hook.stdout)

    def legacy(self):
        ledger = self.work / upgrades.LEDGER
        ledger.write_text('{"context-evidence-0.2": {}}')
        source = self.work / "context/sources/board.md"
        source.parent.mkdir()
        exclusion = "We will not enter the data centre business or create or own LLM models."
        action = "We will rent capacity as required and use existing models."
        source.write_text(exclusion + "\n" + action + "\n")
        main = records.create(self.root, "company-context", "context/company.md")
        old = "- Rule: We prefer existing models. [S1]"
        main.write_text(main.read_text().replace("## Constraints and open questions\n", "## Constraints and open questions\n\n" + old + "\n").replace("| {{S1}}", "| S1 | [Board minutes](sources/board.md) | undated | 2025-01-01 |\n| {{S1}}"))
        side = self.work / "product-scraps-from-meetings.md"
        side.write_bytes((action + "\r\n").encode())
        received = {p: p.read_bytes() for p in (main, side, source)}
        plan = {"id": "board-capacity", "reason": "Restored both exclusions and conditions from the approved board minutes.",
                "changes": [
                    {"path": "context/company.md", "before": upgrades.fingerprint(main),
                     "text": main.read_text().replace(old, "- Rule: " + exclusion + " [S1]\n- Rule: " + action + " [S1]"),
                     "replacements": [{"line": main.read_text().splitlines().index(old) + 1, "source": "context/sources/board.md",
                                       "digest": upgrades.fingerprint(source), "quote": exclusion, "destination": "context/company.md"}]},
                    {"path": side.name, "before": upgrades.fingerprint(side), "into": "context/company.md"}]}
        return received, plan

    def test_open_finds_arbitrary_names_and_converts_with_verified_recovery(self):
        received, plan = self.legacy()
        other = self.work / "products/amber/initiatives/birch/willow.md"
        other.parent.mkdir(parents=True)
        other.write_text("# Incident\n\nCustomers received refunds in March.\n")
        open_event = self.start("SessionStart")
        self.assertIn("execute playbook/updates.md", open_event["hookSpecificOutput"]["additionalContext"])
        pending = pm.alignment(self.root)["outstanding"]
        self.assertEqual({i["path"] for i in pending}, {p.relative_to(self.work).as_posix() for p in [*received, other]})
        self.assertEqual(self.start("Stop")["decision"], "block")
        preview = self.cli("align", "--preview-plan", data=plan)
        self.assertEqual(preview.returncode, 0, preview.stdout)
        self.assertFalse((self.work / conversion.HISTORY).exists())
        for path, data in received.items():
            self.assertEqual(path.read_bytes(), data)
        result = self.cli("align", "--apply-plan", data=plan)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        main, old, source = received
        self.assertFalse(old.exists())
        self.assertIn("will not enter", main.read_text())
        self.assertIn("as required", main.read_text())
        self.assertEqual(source.read_bytes(), received[source])
        self.assertTrue(other.exists())
        saved = self.work / conversion.HISTORY / "board-capacity.zip"
        with zipfile.ZipFile(saved) as archive:
            for path in (main, old):
                self.assertEqual(archive.read("original/" + path.relative_to(self.work).as_posix()), received[path])
        self.assertIn("already applied", self.cli("align", "--apply-plan", data=plan).stdout)
        self.assertEqual(pm.check(self.root), [])

    def test_safeguards_reject_dropped_claims_dirty_files_ignored_archives_and_sources(self):
        received, plan = self.legacy()
        main, side, source = received
        prepared = self.cli("align")
        self.assertEqual(prepared.returncode, 0, prepared.stdout)
        edits = plan["changes"]
        candidate = edits[0]["text"]
        edits[0]["text"] = main.read_text()
        self.assertNotEqual(self.cli("align", "--apply-plan", data=plan).returncode, 0)
        edits[0]["text"] = candidate
        def reject(needle):
            result = self.cli("align", "--apply-plan", data=plan)
            self.assertIn(needle, result.stdout)
            self.assertEqual(main.read_bytes(), received[main])
            self.assertTrue(side.exists())
            self.assertFalse((self.work / conversion.HISTORY).exists())
        ignore = self.work / ".gitignore"
        ignore.write_text(ignore.read_text() + "\n*.zip\n")
        reject("Private Git must include")
        ignore.write_text(ignore.read_text().replace("*.zip", ""))
        edits[1]["path"] = "context/sources/board.md"
        reject("Keep original source")
        edits[1]["path"] = side.name
        side.write_text("A different draft.\n")
        reject("Local edits changed")
        side.write_bytes(received[side])
        (self.work / "context/reference.md").write_text(f"[Earlier note](../{side.name})")
        reject("incoming link")
        self.assertEqual(source.read_bytes(), received[source])

    def test_interrupted_after_fold_resumes_and_invalid_state_fails_before_writes(self):
        received, plan = self.legacy()
        main, side, _ = received
        pm.alignment(self.root, True)
        ledger = self.work / upgrades.LEDGER
        base = json.loads(ledger.read_text())
        ledger.write_text(json.dumps(dict(base, **{upgrades.TRANSACTIONS: []})))
        self.assertIn("Invalid filing transaction ledger", self.cli("align", "--apply-plan", data=plan).stdout)
        self.assertEqual(main.read_bytes(), received[main])
        ledger.write_text(json.dumps(base))
        original_replace = storage.replace_text
        def fail_once(path, before, after):
            if path == ledger:
                raise OSError("out of disk")
            original_replace(path, before, after)
        with patch.object(storage, "replace_text", side_effect=fail_once), self.assertRaises(OSError):
            conversion.apply(self.work, plan, pm.filing_validator(self.root), pm.LINK)
        self.assertFalse(side.exists())
        self.assertTrue(conversion.pointer(self.work).exists())
        self.start("SessionStart")
        self.assertFalse(conversion.pointer(self.work).exists())
        self.assertIn(plan["id"], json.loads(ledger.read_text())[upgrades.TRANSACTIONS])
        self.assertEqual(pm.check(self.root), [])

    def test_new_supporting_record_gate_applies_to_company_product_initiative_and_artifact(self):
        company = records.create(self.root, "company-context", "context/company.md")
        product = records.create(self.root, "product-context", "products/checkout/context.md")
        initiative = records.create(self.root, "initiative-context", "products/checkout/initiatives/renewal/context.md")
        goal = records.create(self.root, "goal", "products/checkout/adoption.md")
        for parent, folder in ((company, company.parent), (product, product.parent), (initiative, initiative.parent), (goal, goal.parent)):
            owned = folder / "records"
            if parent == goal:
                owned /= goal.stem
            path = (owned / "supplier-pricing.md").relative_to(self.work).as_posix()
            incomplete = self.cli("new", "context-note", path)
            self.assertNotEqual(incomplete.returncode, 0)
            args = ("--parent", parent.relative_to(self.work).as_posix(), "--basis", "maintained-reference",
                    "--reason", "Finance compares supplier prices at renewal.", "--trigger", "The supplier publishes a new rate.")
            result = self.cli("new", "context-note", path, *args)
            self.assertEqual(result.returncode, 0, result.stdout)
            self.assertIn("## Filing", (self.work / path).read_text())
            self.assertNotEqual(self.cli("new", "context-note", path, *args).returncode, 0)
        bad = self.cli("new", "company-context", "context/other.md")
        self.assertNotEqual(bad.returncode, 0)
        self.assertEqual(pm.check(self.root), [])

    def test_headings_links_and_navigation_are_accounted_for(self):
        received, plan = self.legacy()
        main, side, _ = received
        text = "# Excluded markets: Belarus and Russia\n\n# Company context: research notes\n\n" + side.read_text()
        side.write_text(text)
        row = plan["changes"][1]
        row["before"] = upgrades.fingerprint(side)
        row["replacements"] = [{"line": 3, "disposition": "navigation"}]
        refused = self.cli("align", "--preview-plan", data=plan)
        self.assertIn("Account for the original content", refused.stdout)
        row["replacements"].append({"line": 1, "disposition": "navigation"})
        self.assertIn("Archive only", self.cli("align", "--preview-plan", data=plan).stdout)
        row["replacements"].pop()
        plan["changes"][0]["text"] += "\n# Excluded markets: Belarus and Russia\n"
        reference = self.work / "context/review.md"
        reference.write_text(f"[Scope](../{side.name}#missing-section)\n")
        plan["changes"].append({"path": "context/review.md", "before": upgrades.fingerprint(reference),
                                "text": "[Scope](company.md#missing-section)\n"})
        self.assertIn("missing anchor", self.cli("align", "--preview-plan", data=plan).stdout)
        plan["changes"][0]["text"] += '\n<a id="missing-section"></a>\n'
        success = self.cli("align", "--apply-plan", data=plan)
        self.assertEqual(success.returncode, 0, success.stdout)
        self.assertIn("Belarus and Russia", main.read_text())
        self.assertNotIn("# Research notes", main.read_text())

    def test_preserves_untracked_concurrent_editor_bytes(self):
        received, plan = self.legacy()
        main = next(iter(received))
        pm.alignment(self.root, True)
        real_rename = conversion.os.rename
        latest = b"New material from another editor"
        def concurrent_save(src, target):
            if src == main:
                main.write_bytes(latest)
            real_rename(src, target)
        with patch.object(conversion.os, "rename", side_effect=concurrent_save), self.assertRaisesRegex(ValueError, "Concurrent"):
            conversion.apply(self.work, plan, pm.filing_validator(self.root), pm.LINK)
        self.assertEqual(main.read_bytes(), latest)
        self.assertTrue(conversion.pointer(self.work).exists())
        self.assertEqual(list(received)[1].read_bytes(), list(received.values())[1])

    def test_portable_mid_swap_recovery_and_one_scan_per_checkout(self):
        received, plan = self.legacy()
        main = next(iter(received))
        pm.alignment(self.root, True)
        original_replace = storage.replace_text
        def interrupt(path, before, after):
            if path == main:
                raise OSError("disk full")
            original_replace(path, before, after)
        with patch.object(storage, "replace_text", side_effect=interrupt), self.assertRaises(OSError):
            conversion.apply(self.work, plan, pm.filing_validator(self.root), pm.LINK)
        self.assertFalse(main.exists())
        subprocess.run(["git", "-C", str(self.work), "add", "-A"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(self.work), "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                        "-c", "commit.gpgsign=false", "commit", "-qm", "Private snapshot"], check=True)
        saved = self.root.parent / "old-private"
        self.work.rename(saved)
        subprocess.run(["git", "clone", "-q", str(saved), str(self.work)], check=True)
        stray = self.work / "loose scratch.md"
        stray.write_text("Independent untracked record in this clone.")
        self.start("SessionStart")
        self.assertTrue(main.exists())
        self.assertFalse(conversion.pointer(self.work).exists())
        self.assertIn("will not enter", main.read_text())
        self.assertIn(stray.name, {r["path"] for r in pm.alignment(self.root)["outstanding"]})

    def test_waiting_legacy_record_keeps_working_and_registered_sources_are_protected(self):
        received, plan = self.legacy()
        _, _, source = received
        odd = self.work / "products/sample/records/field-study/September.md"
        odd.parent.mkdir(parents=True)
        odd.write_text("Interview arranged for September.\n")
        self.start("SessionStart")
        self.assertFalse(any("September" in e for e in pm.check(self.root)))
        self.cli("align", "--record", odd.relative_to(self.work).as_posix(), "--outcome", "waiting",
                 "--digest", upgrades.fingerprint(odd), "--note", "Waiting for consent to publish the interview.")
        self.assertFalse(any("September" in e for e in pm.check(self.root)))
        original = self.work / "context/decisions.md"
        original.write_bytes(source.read_bytes())
        register = self.work / "context/log.md"
        register.write_text("## Sources\n\n[Minutes](decisions.md)\n")
        plan["changes"][1]["path"] = "context/decisions.md"
        plan["changes"][1]["before"] = upgrades.fingerprint(original)
        self.assertIn("primary source", self.cli("align", "--apply-plan", data=plan).stdout)

    def test_existing_supporting_record_must_belong_to_the_declared_scope(self):
        records.create(self.root, "company-context", "context/company.md")
        records.create(self.root, "product-context", "products/shop/context.md")
        parent = "products/shop/initiatives/cart/context.md"
        records.create(self.root, "initiative-context", parent)
        note = "products/shop/initiatives/cart/records/terms.md"
        made = self.cli("new", "context-note", note, "--parent", parent, "--basis", "maintained-reference",
                        "--reason", "Operations looks up the latest rates.", "--trigger", "Finance revises rates.")
        self.assertEqual(made.returncode, 0, made.stdout)
        payload = {"sources": [], "entries": [{"scope": "product", "product": "shop", "topic": "offer",
                   "question": "What change applies to all orders?", "record": {"path": note, "reason": "Confirm general pricing."}}]}
        result = self.cli("route-context", "--write", note, data=payload)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("all orders", (self.work / note).read_text())

    def test_refile_a_purposeful_typed_record_to_a_new_home_keeps_its_id(self):
        import filing
        parent = records.create(self.root, "company-context", "context/company.md")
        original = records.create(self.root, "context-note", "context/project-friday.md", "Regional rate changes")
        original.write_bytes(original.read_text().replace("\n", "\r\n").encode())
        name = "context/records/regional-rates.md"
        destination = self.work / name
        contract = filing.note_contract(self.work, name, "context/company.md", "maintained-reference",
                                        "Finance looks up rates for each market.", "Finance publishes the quarterly rates.")
        new = records.retarget_links(original.read_text(), original, destination, self.root, {})
        new = filing.add_contract(new, self.work, destination, contract)
        plan = {"id": "regional-rates", "reason": "Finance reuses this quarterly reference independently.",
                "changes": [{"path": name, "before": "absent", "text": new},
                            {"path": "context/project-friday.md", "before": upgrades.fingerprint(original), "into": name},
                            {"path": "context/company.md", "before": upgrades.fingerprint(parent),
                             "text": parent.read_text() + "\n[Regional rates](records/regional-rates.md)\n"}]}
        expected = original.read_bytes()
        result = self.cli("align", "--apply-plan", data=plan)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(records.work_state(destination.read_text())[0]["ID"], records.work_state(expected.decode())[0]["ID"])
        with zipfile.ZipFile(self.work / ".hub-history/regional-rates.zip") as saved:
            self.assertEqual(saved.read("original/context/project-friday.md"), expected)
        self.assertEqual(pm.check(self.root), [])
