"""Exercise optional company workflows through the installed Hub."""

from concurrent.futures import ThreadPoolExecutor
import json
import subprocess
import sys
import unittest

import test_pm
import company_source
import hook
import overrides


def bundle(revision=1, **changes):
    return {"format": 1, "id": "product-ops", "revision": revision, "rules": {
        "weekly-review-order": {"scope": "Weekly reviews", "behavior": "Start with risks."},
        "handovers": {"scope": "Friday handovers", "behavior": "Name the next owner."},
    }, **changes}


class CompanySourceTests(unittest.TestCase):
    setUp = test_pm.HubTests.setUp

    def cli(self, *args):
        result = subprocess.run([sys.executable, str(self.root / "tools/pm.py"), *args],
                                cwd=self.root, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        return json.loads(result.stdout)

    def test_local_import_personal_changes_and_source_withdrawal(self):
        path = self.root.parent / "company workflows.json"
        path.write_text(json.dumps(bundle()), encoding="utf-8")
        core = (self.root / overrides.DEFAULTS_FILE).read_bytes()
        self.assertIsNone(self.cli("company", "show"))
        self.assertTrue(self.cli("action", "workspace", "company", "apply", str(path))["changed"])
        self.assertFalse(self.cli("company", "import", str(path))["changed"])
        self.assertEqual(self.cli("action", "workspace", "company", "show"), bundle())
        self.assertEqual(test_pm.pm.check(self.root), [])
        self.assertEqual(self.cli("override", "show", "weekly-review-order")["effective"][-1]["behavior"],
                         "Start with risks.")
        self.cli("override", "set", "weekly-review-order", "--scope", "Weekly reviews",
                 "--behavior", "Start with customer evidence.")
        self.assertEqual(self.cli("override", "show", "weekly-review-order")["effective"][-1]["behavior"],
                         "Start with customer evidence.")
        self.assertIn("Name the next owner.", self.cli("action", "workspace", "workflow", "open", "handovers")
                      ["workflow_guidance"])
        self.assertEqual(self.cli("align")["covered_overrides"], [])
        self.assertTrue(self.cli("action", "workspace", "company", "reset")["removed"])
        self.assertFalse(self.cli("company", "remove")["removed"])
        self.assertNotIn("handovers", self.cli("override", "list")["effective"])
        self.assertEqual(self.cli("override", "show", "weekly-review-order")["effective"][-1]["behavior"],
                         "Start with customer evidence.")
        self.assertEqual((self.root / overrides.DEFAULTS_FILE).read_bytes(), core)
        self.assertTrue(path.is_file())

    def test_new_revision_replaces_only_its_source_and_replays_are_safe(self):
        first = bundle()
        second = bundle(3, rules={"first-look": {"scope": "Early drafts", "behavior": "Describe the gap."}})
        company_source.install(self.work, json.dumps(first))
        company_source.install(self.work, json.dumps(second))
        original = (self.work / company_source.FILE).read_bytes()
        for invalid in (first, bundle(3), bundle(4, id="other-team")):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    company_source.install(self.work, json.dumps(invalid))
                self.assertEqual((self.work / company_source.FILE).read_bytes(), original)
        self.assertEqual(company_source.workflow_rules(self.root), second["rules"])
        self.assertFalse(company_source.install(self.work, json.dumps(second, sort_keys=True))["changed"])

    def test_invalid_bundle_cannot_replace_current_source(self):
        company_source.install(self.work, json.dumps(bundle()))
        invalid = [bundle(True), bundle(0), bundle(2, format=True), bundle(2, format=2),
                   bundle(2, id=""), bundle(2, metrics={}), bundle(2, rules=[]),
                   bundle(2, rules={"bad": {"scope": "Reviews", "behavior": ""}}),
                   bundle(2, rules={"A name": {"scope": "Reviews", "behavior": "Ask first."}})]
        same_scope = {"target": "review-order", "scope": "Friday", "behavior": "Review blockers."}
        invalid.append(bundle(2, rules={"a": same_scope, "b": dict(same_scope, behavior="Review risks.")}))
        texts = [json.dumps(value) for value in invalid] + ["null", '{"id": 1, "id": 2}', "{"]
        for text in texts:
            with self.subTest(text=text):
                with self.assertRaises(ValueError):
                    company_source.install(self.work, text)
        self.assertEqual(company_source.read(self.work)[1], bundle())

    def test_concurrent_revision_imports_keep_the_newest_and_the_whole_file(self):
        def publish(revision):
            try:
                company_source.install(self.work, json.dumps(bundle(revision)))
            except ValueError as exc:
                self.assertIn("newer", str(exc))
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(publish, [3, 1, 4, 2]))
        self.assertEqual(company_source.read(self.work)[1], bundle(4))

    def test_damaged_local_copy_can_be_detached(self):
        self.assertFalse((self.work / company_source.FILE).exists())
        company_source.install(self.work, json.dumps(bundle()))
        (self.work / company_source.FILE).write_text("partial", encoding="utf-8")
        with self.assertRaises(ValueError):
            company_source.workflow_rules(self.root)
        self.assertTrue(any("customizations/" in error for error in test_pm.pm.check(self.root)))
        self.assertTrue(self.cli("company", "remove")["removed"])
        self.assertEqual(company_source.workflow_rules(self.root), {})

    def test_damaged_source_preserves_personal_work_and_can_be_reimported(self):
        path = self.root.parent / "known company.json"
        path.write_text(json.dumps(bundle()), encoding="utf-8")
        self.cli("company", "import", str(path))
        core = overrides.defaults(self.root)
        weekly = core["weekly-review-order"]
        core["board-updates"] = {"scope": "Board updates", "behavior": "Append the core board appendix."}
        (self.root / overrides.DEFAULTS_FILE).write_text(json.dumps(core), encoding="utf-8")
        self.cli("override", "set", "weekly-review-order", "--scope", weekly["scope"], "--behavior", weekly["behavior"])
        self.cli("override", "set", "morning", "--scope", "Mornings", "--behavior", "Read my intake notes.")
        installed = self.work / company_source.FILE
        rules = self.work / overrides.FILE
        personal_bytes = rules.read_bytes()
        for damage in (b'{"id":', b'\xff\xf0'):
            with self.subTest(damage=damage):
                installed.write_bytes(damage)
                for command in (("align", "--status"), ("align",)):
                    status = self.cli(*command)
                    self.assertIn("company import", status["company_review"])
                    self.assertEqual(status["covered_overrides"], [])
                guidance = hook.reply_preferences(self.root)["hookSpecificOutput"]["additionalContext"]
                self.assertIn("Read my intake notes.", guidance)
                self.assertIn("company import", guidance)
                self.assertNotIn("Append the core board appendix.", guidance)
                self.assertEqual(rules.read_bytes(), personal_bytes)
                self.assertEqual(installed.read_bytes(), damage)
                self.assertTrue(self.cli("company", "import", str(path))["repaired"])
                self.assertEqual(self.cli("company", "show"), bundle())
                self.assertNotIn("company_review", self.cli("align", "--status"))
                self.assertIn("Append the core board appendix.", overrides.guidance(self.work))

    def test_a_newer_source_format_survives_an_older_import(self):
        company_source.install(self.work, json.dumps(bundle()))
        path = self.work / company_source.FILE
        future = json.dumps({"format": 2, "new": "schema"}).encode("utf-8")
        path.write_bytes(future)
        with self.assertRaisesRegex(ValueError, "newer version of oryx"):
            company_source.install(self.work, json.dumps(bundle()))
        self.assertIn("Update oryx", company_source.inspection(self.root)[1])
        self.assertEqual(path.read_bytes(), future)
