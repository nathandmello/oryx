"""Exercise the installed command catalog and first writes after a Studio upgrade."""

from datetime import date, timedelta
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

import test_opportunities
import test_pm
from onboarding_fixtures import reviewed_setup


def git(repository, *args):
    return subprocess.check_output(["git", "-C", str(repository), "-c", "user.name=Fixture PM",
                                    "-c", "user.email=pm@example.invalid", *args], text=True).strip()


def saved_checkout(studio):
    git(studio, "add", "--all")
    git(studio, "commit", "-qm", "Save Studio fixture")
    source = studio.parent.parent / "Saved Studio"
    studio.rename(source)
    return source


class StudioContractTests(unittest.TestCase):
    def command(self, *args, payload=None, cwd=None, reject=False):
        result = subprocess.run([sys.executable, str(self.root / "tools/pm.py"), *args],
                                cwd=cwd or self.root, env=self.env, capture_output=True, text=True, timeout=45,
                                input="" if payload is None else json.dumps(payload))
        if reject:
            self.assertNotEqual(result.returncode, 0, args)
            return result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, f"{args}\n{result.stdout}\n{result.stderr}")
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            return result.stdout.strip()

    def test_first_write_after_a_direct_core_update(self):
        reviewed_setup(self)
        self.env = os.environ.copy()
        record = "workspace/goals/renewals.md"
        self.command("new", "goal", record)
        receipt = self.command("conversation", "checkpoint", "preview", record, payload={"mode": "quiet"})
        schema = self.command("customize", "show")
        patch = {"revision": schema["revision"], "config": {"fields": {"x-region": {"label": "Region", "type": "text"}}}}
        company = {"format": 1, "id": "finance", "revision": 1, "rules": {}}
        (self.work / "context/sources").mkdir(exist_ok=True)
        (self.work / "context/sources/finance.json").write_text(json.dumps(company))
        settings = self.work / "settings.json"
        values = json.loads(settings.read_text())
        values["system_version"] = "0.10.0"
        settings.write_text(json.dumps(values))
        source = saved_checkout(self.work)
        legacy = self.root / "private"
        cases = [
            (["override", "set", "board", "--scope", "Board reviews", "--behavior", "Lead with churn."],
             None, "customizations/rules.json", "Lead with churn."),
            (["company", "import", str(legacy / "context/sources/finance.json")],
             None, "customizations/company.json", "finance"),
            (["customize", "apply"], patch, "customizations/settings.json", "x-region"),
            (["action", "workspace", "checkpoint", "apply", record], receipt, record, "| Mode | quiet |"),
        ]
        for args, data, changed, expected in cases:
            with self.subTest(command=args[:2]):
                git(self.root, "clone", "-q", "--no-local", str(source), str(legacy))
                self.command(*args, payload=data, cwd=legacy / "context")
                self.assertFalse(legacy.exists())
                self.assertIn(expected, (self.work / changed).read_text())
                self.assertEqual(git(self.work, "rev-parse", "HEAD"), git(source, "rev-parse", "HEAD"))
                self.assertEqual(self.command("align", "--status")["studio_moves"], {})
                self.work.rename(self.root.parent / ("Result " + args[0]))

    def test_shared_checker_does_not_read_a_case_variant_pm_directory(self):
        test_pm.HubTests.setUp(self)
        other = self.root / "Studio"
        if other.exists():
            self.skipTest("Volume resolves case variants to the same root")
        other.mkdir()
        document = other / "PM notes.md"
        document.write_text("Synthetic private material")
        git(self.root, "add", "--force", "--", document.relative_to(self.root))
        original_read = Path.read_text
        def guard(path, *args, **kwargs):
            if path == document:
                self.fail("System check opened a PM record")
            return original_read(path, *args, **kwargs)
        with patch.object(Path, "read_text", guard):
            errors = test_pm.pm.check(self.root, include_workspace=False)
        self.assertTrue(any("Studio/" in error for error in errors), errors)

    def test_core_only_reads_do_not_trust_an_uninstalled_studio(self):
        test_pm.HubTests.setUp(self)
        self.env = os.environ.copy()
        self.work.rename(self.root.parent / "Original Studio")
        self.assertIn("logo-churn", self.command("metric", "list"))
        self.assertEqual(self.command("customize", "show")["config"], {})
        self.assertFalse(self.work.exists())

        (self.work / "customizations").mkdir(parents=True)
        (self.work / "customizations/settings.json").write_text("Unreadable fixture sentinel")
        calls = [
            (["customize", "show"], None), (["metric", "list"], None),
            (["check-metric"], {"metric": "logo-churn"}), (["route-context"], {"sources": []}),
        ]
        for args, payload in calls:
            with self.subTest(command=args):
                message = self.command(*args, payload=payload, reject=True)
                self.assertIn("expected its own local Git repository", message)
                self.assertNotIn("fixture sentinel", message)

    def test_incompatible_checkout_refuses_new_customization_writes(self):
        reviewed_setup(self)
        self.env = os.environ.copy()
        settings = self.work / "settings.json"
        values = json.loads(settings.read_text())
        values["system_version"] = "999.0.0"
        settings.write_text(json.dumps(values))
        for args in (["override", "set", "board", "--scope", "Planning", "--behavior", "Show churn."],
                     ["company", "remove"], ["customize", "apply"]):
            with self.subTest(command=args):
                message = self.command(*args, reject=True)
                self.assertIn("Unsupported workspace version", message)
        self.assertEqual(list((self.work / "customizations").iterdir()), [])
        self.assertEqual(json.loads(settings.read_text())["system_version"], "999.0.0")

    def test_every_published_action_in_a_restored_studio(self):
        hub = test_opportunities.InitiativeTests()
        self.addCleanup(hub.doCleanups)
        hub.setUp()
        self.root, self.work, self.env = hub.root, hub.work, hub.env
        hub.submit(hub.setup_event(), hub.capture(), hub.describe(), hub.metric(), hub.target(),
                   hub.decision("evaluate"), hub.decision("defer", revisit="Interview panel reopens."))
        signed = hub.ledger.read_bytes()
        source = saved_checkout(self.work)
        git(self.root, "clone", "-q", "--no-local", str(source), str(self.work))
        self.assertFalse((self.work / "customizations").exists())  # Git omits empty directories.
        self.command("align", cwd=self.work / "context")

        catalog = self.command("action", "--catalog")["commands"]
        exercised = set()
        def action(name, *arguments, payload=None):
            result = self.command("action", *name.split(), *arguments, payload=payload, cwd=self.work / "context")
            exercised.add(name)
            return result

        rule = "Open with the PM's pending commitments."
        company = {"format": 1, "id": "review-ops", "revision": 1, "rules": {"weekly-review-order": {
            "scope": "Weekly reviews", "behavior": "Start with the company summary."}}}
        policy = self.root.parent / "Company workflow.json"
        policy.write_text(json.dumps(company))
        onboarding = action("context company show")
        self.assertEqual(onboarding["revision"], 0)
        self.assertIsNone(onboarding["pending"])
        self.assertFalse((self.work / "workspace/onboarding/company.json").exists())
        self.assertIsNone(action("workspace company show"))
        self.assertTrue(action("workspace company apply", str(policy))["changed"])
        self.command("override", "set", "weekly-review-order", "--scope", "Weekly reviews", "--behavior", rule)
        for name, entry in catalog.items():
            if "guide" in entry:
                with self.subTest(guided=name):
                    result = action(name, *(["weekly-review-order"] if name == "workspace workflow open" else []))
                    self.assertIn(rule, result["workflow_guidance"])
                    self.assertNotIn("Start with the company summary.", result["workflow_guidance"])
                    self.assertTrue((self.root / result["guide"]).is_file())
        self.assertTrue(action("workspace company reset")["removed"])

        self.assertIn("north", str(action("context area show", "example", "north")))
        goal = "workspace/goals/renewals.md"
        for name, path in (("strategy goal draft", goal), ("strategy brief draft", "workspace/strategies/renewals.md")):
            action(name, path)
            self.assertTrue((self.work / path).is_file())
        self.assertIn("id", action("workspace checkpoint show", goal))
        checkpoint = action("workspace checkpoint preview", goal, payload={"mode": "quiet"})
        action("workspace checkpoint apply", goal, payload=checkpoint)
        self.assertEqual(action("workspace checkpoint show", goal)["work_state"]["Mode"], "quiet")

        self.assertEqual(action("initiative record show", "example", hub.i)["initiative"]["title"], "Renewal delays")
        draft = action("discovery experiment draft", "example", hub.i, "renewal-rate")
        self.assertTrue((self.work / draft).is_file())
        for name in ("portfolio backlog show", "portfolio roadmap show", "portfolio decisions review"):
            with self.subTest(consumer=name):
                self.assertIsInstance(action(name, "--product", "example"), (dict, list))
        decision = action("review decision show", "--product", "example")[0]["decision"]
        self.assertEqual(action("review forecast show", "--product", "example"), [])
        forecast = action("review forecast preview", payload={
            "operation": "create", "decision": decision, "event": "Renewal pilot expands", "probability": 65,
            "made_on": date.today().isoformat(), "resolve_on": (date.today() + timedelta(days=7)).isoformat(),
            "criterion": "Five pilot customers sign renewals."})
        identifier = action("review forecast apply", payload=forecast)["id"]
        self.assertEqual(action("review forecast show", "--product", "example")[0]["id"], identifier)

        original = action("workspace preferences show")
        action("workspace preferences preview", "--layout", "prose")
        self.assertEqual(action("workspace preferences set", "--layout", "prose")["layout"], "prose")
        self.assertEqual(action("workspace preferences reset", "layout"), original)
        self.assertIn("PASS", action("workspace health check"))
        self.check_browser_action()
        exercised.add("workspace browser open")
        self.assertEqual(exercised, set(catalog))
        self.assertEqual(hub.ledger.read_bytes(), signed)
        self.assertEqual(git(self.root, "ls-files", "--others", "--exclude-standard", "--", "studio"), "")
        self.assertFalse(any((self.root / name).exists() for name in ("private", "workspace")))

    def check_browser_action(self):
        cmd = [sys.executable, str(self.root / "tools/pm.py"), "action", "workspace", "browser", "open", "--no-open"]
        with subprocess.Popen(cmd, cwd=self.work / "context", env=self.env,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) as app:
            try:
                url = urlsplit(app.stdout.readline().strip().partition(" at ")[2])
                self.assertEqual(url.hostname, "127.0.0.1")
                origin = f"http://{url.netloc}"
                request = Request(origin + "/api/catalog", data=b"{}", headers={
                    "Origin": origin, "X-PM-Hub-Token": url.fragment, "Content-Type": "application/json"})
                with urlopen(request, timeout=5) as response:
                    self.assertIn("example", response.read().decode())
            finally:
                app.terminate()
