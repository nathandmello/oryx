"""Exercise purpose-first conversion in disposable private repositories with real local files."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import conversion
import layout_upgrade
import pm_profile
import upgrades


class LayoutMigrationTests(unittest.TestCase):
    def setUp(self):
        root = tempfile.TemporaryDirectory()
        self.addCleanup(root.cleanup)
        self.private = Path(root.name).resolve() / "workspace"
        subprocess.run(["git", "init", "-q", str(self.private)], check=True)
        self.write(".gitignore", "*.local\n")
        upgrades.fresh(self.private)

    def write(self, name, content):
        path = self.private / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content.encode() if isinstance(content, str) else content)
        return path

    def run_upgrade(self, apply=True):
        return layout_upgrade.run(self.private, apply=apply)

    def test_personal_skill_links_survive_layout_changes_without_becoming_evidence(self):
        company = self.write("context/company.md", "<!-- pm: company-context -->\n# Company\n")
        product = self.write("products/credit/guide.md", "<!-- pm: product-context -->\n# Credit\n")
        old = self.write("customizations/views/notes.md", "## Sources\n\n[Example](../../context/company.md)\n")
        raw = self.write("customizations/skills/week/sources/method.md", "# How we write updates\n")
        registry = self.write("context/metrics.json", '{"version": 1, "revisions": []}\n')
        original = {path: path.read_bytes() for path in (old, raw, registry)}
        result = self.run_upgrade()
        self.assertIn("products/credit/guide.md", result["moves"])
        self.assertTrue(company.exists())
        self.assertFalse(product.exists())
        receipt = layout_upgrade.receipt(self.private, upgrades.read_state(self.private)[1])
        self.assertFalse(set(receipt.get("sources", ())) & {"customizations/skills/week/sources/method.md", "context/company.md"})
        self.assertNotIn("context/metrics.json", receipt.get("retained", {}))
        self.assertIn("Customization", receipt["retained"]["context/company.md"]["note"])
        self.assertTrue(all(path.read_bytes() == data for path, data in original.items()))

    def test_moves_references_stable_identity_and_profile_with_replay(self):
        company = self.write("context/company.md", "<!-- pm: company-context -->\r\n# Company\r\nExcluded permanently.\r\n")
        original = company.read_bytes()
        parent = self.write("products/basket/guide.md", "<!-- pm: product-context -->\n# Basket\n[Parent](../../context/company.md#company)\n")
        self.write("products/basket/initiatives/returns/context.md",
                   "<!-- pm: initiative-context -->\n# Faster returns\n## Context controls\n\n| Parent context | [Basket](../../guide.md) |\n")
        self.write("products/basket/goal.md", "<!-- pm: goal -->\n# Goal\n## Work state\n\n| ID | goal-faster |\n")
        self.write("products/basket/records/rates.md", "<!-- pm: context-note -->\n# Rates\n## Filing\n\n"
                   "| Field | Value |\n| --- | --- |\n| Owning record | [Parent](../guide.md) |\n| Basis | maintained-reference |\n"
                   "| Reader need | Prepare a quote |\n| Review trigger | New rate sheet |\n")
        profile = {"responsibilities": [{"subject": "product/basket", "role": "owner",
                                         "goals": ["products/basket/goal.md#goal"], "depends_on": []}], "follow": ["area/billing"]}
        old_json = self.write(layout_upgrade.OLD_PROFILE, json.dumps(profile, indent=3))
        story = self.write("context/reading.md", "[Rates][r]\r\n\r\n[r]: <../products/basket/records/rates.md#rates>\r\n")
        protected = self.write("products/basket/sources/report.md", b"Untouched.\r\n")
        expected_goal = "workspace/goals/product-basket-goal-faster.md"
        preview = self.run_upgrade(False)
        self.assertTrue(preview["changed"])
        self.assertFalse((self.private / layout_upgrade.PROFILE).exists())
        out = self.run_upgrade()
        self.assertEqual(preview, out)
        self.assertEqual((self.private / "context/company/overview.md").read_bytes(), original)
        self.assertEqual(protected.read_bytes(), b"Untouched.\r\n")
        self.assertEqual(story.read_bytes(), b"[Rates][r]\r\n\r\n[r]: <products/basket/rates.md#rates>\r\n")
        self.assertIn("../../company/overview.md#company", (self.private / "context/products/basket/overview.md").read_text())
        self.assertIn("../../products/basket/overview.md", (self.private / "context/initiatives/returns/overview.md").read_text())
        self.assertIn("[Parent](overview.md)", (self.private / "context/products/basket/rates.md").read_text())
        self.assertTrue((self.private / expected_goal).exists())
        data = pm_profile.parse((self.private / layout_upgrade.PROFILE).read_text())
        self.assertEqual(data["responsibilities"][0]["goals"], [expected_goal + "#goal"])
        self.assertEqual(data["follow"], ["area/billing"])
        self.assertFalse(parent.exists())
        self.assertFalse(old_json.exists())
        self.assertTrue(any(p.read_bytes() == original for p in (self.private / ".git/pm-hub-recovery").rglob("company.md")))
        self.assertFalse(self.run_upgrade()["changed"])

    def test_collisions_and_unclassifiable_material_remain_for_review(self):
        a = self.write("products/shop/guide.md", "<!-- pm: product-context -->\n# A\n")
        b = self.write("products/shop/context.md", "<!-- pm: product-context -->\n# B\n")
        raw = self.write("products/shop/research.bin", b"\xff\x14")
        self.write("products/shop/special.md", "# No marker\n")
        keep = self.write("products/shop/assistant.local", "private editor state")
        out = self.run_upgrade()
        self.assertFalse(out["moves"])
        self.assertEqual({r["path"] for r in out["outstanding"]},
                         {p.relative_to(self.private).as_posix() for p in (a, b, raw)} | {"products/shop/special.md"})
        self.assertEqual(raw.read_bytes(), b"\xff\x14")
        self.assertEqual(keep.read_text(), "private editor state")
        self.assertEqual(layout_upgrade.blocked(self.private, "context/products/shop/overview.md"),
                         ["products/shop/context.md", "products/shop/guide.md"])
        self.assertFalse(self.run_upgrade()["changed"])

    def test_protected_source_blocks_related_family_and_opaque_config_keeps_its_goal(self):
        self.write("products/a/brief.md", "<!-- pm: product-context -->\n# Shop\n")
        self.write("products/a/initiatives/pilot/context.md", "<!-- pm: initiative-context -->\n## Context controls\n\n"
                   "| Parent context | [Shop](../../brief.md) |\n")
        source = self.write("products/a/sources/source.md", "[Prior product](../brief.md)\n")
        self.write("products/a/goal.md", "<!-- pm: goal -->\n# Goal\n## Work state\n\n| ID | goal-next |\n")
        cfg = self.write("products/settings.yaml", "goal: products/a/goal.md\n")
        original = source.read_bytes(), cfg.read_bytes()
        out = self.run_upgrade()
        self.assertFalse(out["moves"])
        self.assertEqual((source.read_bytes(), cfg.read_bytes()), original)
        self.assertEqual(len(layout_upgrade.blocked(self.private, "context/initiatives/pilot/overview.md")), 1)

    def test_resume_preserves_concurrent_edits_and_file_modes(self):
        old = self.write("context/company.md", "<!-- pm: company-context -->\n# Company\n")
        os.chmod(old, 0o640)
        dest = self.private / "context/company/overview.md"
        real_swap = conversion.recoverable_swap
        def interruption(private, tx, name, before, candidate):
            if candidate is None:
                raise OSError("power loss")
            return real_swap(private, tx, name, before, candidate)
        with patch.object(conversion, "recoverable_swap", side_effect=interruption), self.assertRaises(OSError):
            self.run_upgrade()
        self.assertTrue(layout_upgrade.pending(self.private))
        self.assertEqual(dest.read_bytes(), old.read_bytes())
        preimage = old.read_bytes()
        old.write_bytes(preimage + b"Concurrent change\n")
        with self.assertRaisesRegex(ValueError, "Concurrent"):
            self.run_upgrade()
        self.assertIn(b"Concurrent change", old.read_bytes())
        old.write_bytes(preimage)
        self.run_upgrade()
        self.assertFalse(layout_upgrade.pending(self.private))
        self.assertFalse(old.exists())
        self.assertEqual(dest.stat().st_mode & 0o777, 0o640)
        self.assertFalse(self.run_upgrade()["changed"])

    def test_ignored_future_destination_preserves_committed_original(self):
        original = self.write("products/cart/goals.md", "<!-- pm: goal -->\n## Work state\n\n| ID | goal-repurchase |\n")
        self.write(".gitignore", "/workspace/\n")
        subprocess.run(["git", "-C", str(self.private), "add", "--", ".gitignore", "products/cart/goals.md"], check=True)
        before = original.read_bytes()
        out = self.run_upgrade()
        self.assertIn("ignores", next(row["note"] for row in out["outstanding"] if row["path"] == "products/cart/goals.md"))
        self.assertNotIn("products/cart/goals.md", out["moves"])
        self.assertEqual(original.read_bytes(), before)
        self.assertFalse((self.private / "workspace/goals/product-cart-goal-repurchase.md").exists())
        self.assertEqual(subprocess.check_output(["git", "-C", str(self.private), "show", ":products/cart/goals.md"]), before)
        self.assertEqual(subprocess.run(["git", "-C", str(self.private), "diff", "--quiet", "--", "products/cart/goals.md"]).returncode, 0)

    def test_tampered_journal_original_and_destination_remain(self):
        path = self.write("context/company.md", "<!-- pm: company-context -->\n# Company\n")
        with patch.object(layout_upgrade, "apply_plan", side_effect=OSError("interrupted")), self.assertRaises(OSError):
            self.run_upgrade()
        journal = layout_upgrade.journal_path(self.private)
        data = json.loads(journal.read_text())
        data["plan"]["writes"]["context/company/overview.md"]["text"] = "Lost history"
        journal.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, "Invalid layout journal"):
            self.run_upgrade()
        self.assertTrue(path.exists())
        self.assertFalse((self.private / "context/company/overview.md").exists())

    def test_mixed_purpose_and_case_only_folder_conflicts(self):
        self.write("products/help/guide.md", "<!-- pm: product-context -->\n# Help\n## Backlog\n- Promise to ship in July\n")
        other = self.write("products/desk/brief.md", "<!-- pm: product-context -->\n# Desk\n")
        self.write("context/Products/legacy.md", "An existing manual note.\n")
        out = self.run_upgrade()
        self.assertFalse(out["moves"])
        self.assertTrue(other.exists())
        self.assertEqual(layout_upgrade.blocked(self.private, "context/products/help/overview.md"), ["products/help/guide.md"])
        self.assertEqual({row["path"] for row in out["outstanding"]},
                         {"products/help/guide.md", "products/desk/brief.md", "context/Products/legacy.md"})

    def test_verbatim_examples_and_html_links_are_never_silently_rewritten(self):
        raw = "<!-- pm: product-context -->\n# Receipts\n> The policy says [always](local-policy.pdf).\n"
        typed = self.write("products/pay/brief.md", raw)
        self.write("products/pay/local-policy.pdf", b"evidence")
        receipt = self.write("context/company.md", "<!-- pm: company-context -->\n# Company\n")
        self.write("products/pay/navigation.html", '<a href="../../context/company.md">Company source</a>')
        out = self.run_upgrade()
        self.assertFalse(out["moves"])
        self.assertEqual(typed.read_text(), raw)
        self.assertTrue(receipt.is_file())

    def test_relative_references_in_config_keep_working(self):
        for stem in ("retention", "trial", "some notes"):
            self.write(f"products/teller/{stem}.md", f"<!-- pm: goal -->\n## Work state\n\n| ID | goal-{stem.replace(' ', '-')} |\n")
        self.write("products/teller/config/goals.json", '{"first":"../retention.md", "next":"../some notes.md"}')
        self.write("products/teller/rules.yaml", 'trial: ./trial.md\nnotes: ./some%20notes.md\n')
        result = self.run_upgrade()
        self.assertEqual(result["moves"], {})
        for stem in ("retention", "trial", "some notes"):
            self.assertTrue((self.private / f"products/teller/{stem}.md").is_file())

    def test_malformed_receipt_fails_before_writing(self):
        name = self.write("context/company.md", "<!-- pm: company-context -->\n# Company\n")
        path = self.private / upgrades.LEDGER
        original = json.loads(path.read_text())
        original[layout_upgrade.RULE] = {"version": 1, "sources": ["../unrelated"]}
        path.write_text(json.dumps(original))
        with self.assertRaisesRegex(ValueError, "Unsafe"):
            self.run_upgrade()
        self.assertTrue(name.is_file())
        self.assertFalse(layout_upgrade.pending(self.private))

    def test_actual_markdown_link_and_identical_literal_in_one_document(self):
        self.write("context/company.md", "<!-- pm: company-context -->\n# Company\n")
        example = "[Original](../../context/company.md#company)"
        guide = "<!-- pm: product-context -->\n# Product\n"
        guide += f"{example}\nInline `{example}` example.\n\n```md\n{example}\n```\n"
        self.write("products/cart/brief.md", guide)
        result = self.run_upgrade()
        self.assertIn("products/cart/brief.md", result["moves"])
        changed = (self.private / "context/products/cart/overview.md").read_text()
        self.assertIn("\n[Original](../../company/overview.md#company)\n", changed)
        self.assertEqual(changed.count(example), 2)

    def test_tracked_locally_deleted_destination_stays_deleted(self):
        old = self.write("context/company.md", "<!-- pm: company-context -->\n# Old company\n")
        name = "context/company/overview.md"
        removed = self.write(name, "Intentionally removed local record\n")
        subprocess.run(["git", "-C", str(self.private), "add", "--", name], check=True)
        removed.unlink()
        result = self.run_upgrade()
        self.assertEqual(result["moves"], {})
        self.assertTrue(old.exists())
        self.assertFalse(removed.exists())
        self.assertEqual(subprocess.check_output(["git", "-C", str(self.private), "show", ":" + name]),
                         b"Intentionally removed local record\n")
