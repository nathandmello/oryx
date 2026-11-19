"""Exercise retrieval against live private records, including cold and failed caches."""

from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import shlex
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import context_embeddings
import context_index
import task_context as context


class RetrievalTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.private = self.root / "private"
        self.private.mkdir()
        (self.root / "playbook").mkdir()
        shutil.copy(ROOT / "playbook/saas-metrics.json", self.root / "playbook")
        self.cache = self.root / "account.sqlite"
        cache_override = patch.object(context_index, "cache_path", return_value=self.cache)
        cache_override.start()
        self.addCleanup(cache_override.stop)
        self.add("company/overview", "Company", "Keep account details private.", kind="company-context")
        self.pricing = self.add("company/a", "Rate calendar", "Pricing reviews occur on the first Tuesday of each quarter.")
        self.discount = self.add("company/b", "Finance desk", "Finance approves promotional discounts before launch.")
        self.refunds = self.add("company/c", "Customer remedy", "Damaged merchandise can be returned for a full refund.")
        self.password = self.add("company/d", "Account recovery", "Reset forgotten passwords through the emailed recovery link.")
        self.backups = self.add("company/e", "Infrastructure", "Database backups run nightly and are kept for thirty days.")

    def add(self, name, title, fact, *, kind="context-note", day="undated"):
        path = self.private / ("context/" + name + ".md")
        path.parent.mkdir(parents=True, exist_ok=True)
        section, label = {"company-context": ("Data boundaries", "Rule"),
                          "product-context": ("The product", "Fact")}.get(kind, ("Context", "Fact"))
        path.write_text(f"<!-- pm: {kind} -->\n# {title}\n\n## {section}\n\n- {label}: {fact} [S1]\n\n"
                        "## Sources\n\n| ID | Source | Source date | Checked on |\n| --- | --- | --- | --- |\n"
                        f"| S1 | [Primary](https://example.test/{path.stem}) | {day} | 2025-01-01 |\n",
                        encoding="utf-8")
        return path

    def resolve(self, query, **kwargs):
        return context.resolve(self.private, query, explicit={"company": True}, explain=True, **kwargs)

    def notes(self, result):
        return [self.private / row["record"] for row in result["entries"] if not row["binding"]]

    def test_paraphrases_near_misses_and_abstention(self):
        cases = [
            ("How often do we revisit what customers pay?", self.pricing),
            ("When should we reassess what we charge?", self.pricing),
            ("I received a broken item. Can I get my money back?", self.refunds),
            ("I am locked out and cannot remember my login.", self.password),
            ("How long do we retain copies in case the server fails?", self.backups),
            ("Who signs off on sale promotions?", self.discount),
            ("What is the mascot’s favorite pizza?", None),
            ("Where is our office parrot?", None),
            ("How do we choose the color of the logo?", None),
        ]
        for query, target in cases:
            with self.subTest(query=query):
                result = self.resolve(query)
                self.assertEqual(self.notes(result), [target] if target else [])
                self.assertTrue(result["entries"][0]["binding"])
                self.assertEqual("evidence_gap" in result, target is None)
                if target:
                    self.assertEqual(result["entries"][1]["sources"][0]["Source"],
                                     f"[Primary](https://example.test/{target.stem})")

    def test_live_changes_rename_delete_and_scope(self):
        query = "I received a broken item. Can I get my money back?"
        self.assertIn(self.refunds, self.notes(self.resolve(query)))
        self.refunds.write_text(self.refunds.read_text().replace("a full refund", "a partial refund"))
        self.assertIn("partial refund", str(self.resolve(query)["entries"]))
        moved = self.refunds.with_name("renamed.md")
        self.refunds.rename(moved)
        self.assertEqual(self.notes(self.resolve(query)), [moved])
        other = self.add("products/other/returns", "Customer remedy", "Damaged merchandise qualifies for replacement.")
        self.add("products/other/overview", "Other", "A separate product.", kind="product-context")
        moved.unlink()
        self.assertEqual(self.notes(self.resolve(query)), [])
        result = context.resolve(self.private, query)
        self.assertFalse(result["scope"])
        self.assertFalse(result["entries"])
        self.assertNotIn(str(other), str(result))

    def test_eligibility_and_budget_before_search(self):
        self.add("company/future", "New remedy", "Damaged merchandise receives double refunds.", day="2039-01-01")
        legacy = self.add("company/withdrawn", "Earlier remedy", "Return damaged items for credit.")
        legacy.write_text(legacy.read_text().replace("credit. [S1]", "credit. [S1] *(Superseded by [S2])*") +
                          "| S2 | Superseding source | 2025-02-01 | 2025-03-01 |\n")
        self.add("company/sources/raw", "Raw remedy", "The raw refund transcript.")
        hidden = self.add("company/.hidden", "Hidden remedy", "Hidden refund details.")
        self.add("company/secret-comment", "Other", "<!-- Full refund for all damages -->")
        broken_source = self.add("company/bad", "Unverified", "All customers receive double refunds.")
        broken_source.write_text(broken_source.read_text().replace("[S1]", "[S99]"))
        if os.name == "posix":
            (hidden.parent / "alias.md").symlink_to(hidden)
        result = self.resolve("Find refunds for damaged merchandise as of 2026-01-01")
        self.assertEqual(self.notes(result), [self.refunds])
        self.assertIn(legacy, self.notes(self.resolve("Use context/company/withdrawn.md as of 2025-01-01")))
        policy = self.private / "context/company/overview.md"
        policy.write_text(policy.read_text().replace("## Sources", ("- Rule: " + "private " * 150 + "[S1]\n") * 10 + "\n## Sources"))
        result = self.resolve("How are refunds handled?")
        self.assertLessEqual(len(json.dumps(result["entries"], ensure_ascii=False)), 6500)
        self.assertTrue(any("remaining binding" in message for message in result["warnings"]))

    def test_cache_failure_concurrency_and_live_revalidation(self):
        query = "I received a broken item. Can I get my money back?"
        with ThreadPoolExecutor(4) as workers:
            results = list(workers.map(self.resolve, [query] * 8))
        self.assertTrue(all(self.notes(result) == [self.refunds] for result in results))
        self.resolve(query)  # Let the first uncontended query fill any missed cache writes.
        with patch.object(context, "read_document", wraps=context.read_document) as reads:
            self.resolve(query)
        self.assertEqual({call.args[1] for call in reads.call_args_list},
                         {self.private / "context/company/overview.md", self.refunds})
        self.cache.write_bytes(b"unreadable database")
        self.assertEqual(self.notes(self.resolve(query)), [self.refunds])
        self.assertEqual(self.notes(self.resolve(query)), [self.refunds])
        with sqlite3.connect(self.cache) as db:
            db.execute("UPDATE notes SET rows=?", (b"damaged projection",))
            db.execute("UPDATE vectors SET value=?", (bytes(1024),))
        self.assertEqual(self.notes(self.resolve(query)), [self.refunds])
        with patch.object(context_index, "sqlite3", None):
            self.assertEqual(self.notes(self.resolve(query)), [self.refunds])
        with sqlite3.connect(self.cache) as db:
            db.execute("BEGIN EXCLUSIVE")
            self.assertEqual(self.notes(self.resolve(query)), [self.refunds])
        with patch.object(context_index, "cache_path", side_effect=PermissionError):
            self.assertEqual(self.notes(self.resolve(query)), [self.refunds])
        with patch.object(context_embeddings, "encoder", side_effect=ValueError("invalid model")):
            result = self.resolve("Find promotional discounts")
        self.assertEqual(result["retrieval"]["mode"], "lexical")
        self.assertIn(self.discount, self.notes(result))
        self.assertFalse(result["warnings"])

    def test_ignore_changes_exact_identifiers_and_navigation(self):
        subprocess.run(["git", "init", "-q", str(self.private)], check=True)
        self.add("company/contract", "Interface", "List history via conversations.history.")
        result = self.resolve("Which record documents conversations.history?")
        self.assertIn("Interface", str(context.catalog(self.private)))
        self.assertIn("conversations.history", result["entries"][1]["text"])
        q = "I received a broken item. Can I get my money back?"
        self.assertEqual(self.notes(self.resolve(q)), [self.refunds])
        with patch.object(context.upgrades, "source_paths", return_value={"context/company/c.md"}):
            self.assertNotIn(self.refunds, self.notes(self.resolve(q)))
        (self.private / ".gitignore").write_text("context/company/c.md\n")
        self.assertNotIn(self.refunds, self.notes(self.resolve(q)))
        with patch.object(context_embeddings, "encoder", side_effect=AssertionError("unneeded inference")):
            context.catalog(self.private)
            self.assertEqual(self.notes(self.resolve("")), [])

    def test_client_registrations_and_cli_agree(self):
        from test_pm import HubTests
        install = HubTests()
        install.setUp()
        self.addCleanup(install.doCleanups)
        shutil.copytree(self.private / "context", install.work / "context", dirs_exist_ok=True)
        query = "Company-wide, how often do we revisit what customers pay?"
        cli = [sys.executable, "-B", str(install.root / "tools/pm.py"), "task-context"]
        result = json.loads(subprocess.check_output(cli + [query], cwd=install.root))
        self.assertNotIn("retrieval", result)
        self.assertEqual(result["entries"][1]["record"], "context/company/a.md")
        for config in (".codex/hooks.json", ".claude/settings.json"):
            with self.subTest(config=config):
                events = json.loads((install.root / config).read_text())["hooks"]
                registration = events["UserPromptSubmit"][0]["hooks"][0]
                command = ([registration["command"], *registration["args"]] if "args" in registration
                           else shlex.split(registration["command"]))
                payload = {"cwd": str(install.root), "session_id": config, "prompt": query,
                           "hook_event_name": "UserPromptSubmit"}
                output = subprocess.check_output(command, input=json.dumps(payload), cwd=install.root, text=True)
                evidence = json.loads(json.loads(output)["hookSpecificOutput"]["additionalContext"].splitlines()[-1])
                self.assertEqual(evidence, result)
                self.assertEqual(context.previous_scope(install.work, config)["binding"],
                                 [{"record": "context/company/overview.md", "section": "Data boundaries"}])

    def test_scopes_shared_titles_and_time_limited_lookup(self):
        for product in ("atlas", "orchid"):
            self.add(f"products/{product}/overview", product.title(), "Product overview.", kind="product-context")
            self.add(f"products/{product}/returns", "Returns", f"Damaged goods qualify for {product} credit.")
        scope = {"product": "atlas"}
        result = context.resolve(self.private, "How do we refund broken items?", explicit=scope)
        self.assertNotIn("orchid", str(result))
        self.assertIn("products/atlas/returns.md", str(result))
        with patch.object(context, "read_document", wraps=context.read_document) as opened:
            named = context.resolve(self.private, "For Atlas, who handles damaged goods?")
        self.assertEqual(named["scope"]["product"], "atlas")
        unrelated = self.private / "context/products/orchid/returns.md"
        self.assertNotIn(unrelated, {call.args[1] for call in opened.call_args_list})
        self.add("products/orchid/overview", "Atlas", "An overlapping title.", kind="product-context")
        self.assertEqual(context.resolve(self.private, "For Atlas, who handles damaged goods?")["status"], "ambiguous")
        ambiguous = context.resolve(self.private, "Compare Atlas and Orchid returns")
        self.assertEqual(ambiguous["status"], "ambiguous")
        self.assertFalse(ambiguous["entries"])
        with patch("context_search.OPTIONAL_SECONDS", 0):
            result = self.resolve("Who approves promotional discounts?")
        self.assertEqual(result["retrieval"]["mode"], "hybrid-time-limited")
        self.assertIn(self.discount, self.notes(result))
        self.assertFalse(result["warnings"])

    def test_model_reference_output(self):
        model = context_embeddings.encoder()
        self.assertEqual(list(model.token_ids("café naïve résumé")), [6674, 14749, 12752])
        self.assertEqual(list(model.token_ids("中文测试")), [752, 867])
        self.assertFalse(any(model.encode("")))
        expected = GOLDEN_HELLO
        self.assertTrue(all(abs(actual - ref) < 0.000001 for actual, ref in zip(model.encode("Hello World"), expected)))


GOLDEN_HELLO = (-0.03410079, -0.0794194, -0.14359494, 0.0850961, 0.0191801, 0.14176597, 0.04389796, -0.12707147, 0.09827717, 0.09434305, -0.0711348, 0.024307)
