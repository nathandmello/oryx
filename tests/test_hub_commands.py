"""Verify command discovery, compatibility, and catalog validation."""

from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import hub_commands
import pm


class HubCommandTests(unittest.TestCase):
    def cli(self, *args, expected=0):
        result = subprocess.run([sys.executable, str(pm.ROOT / "tools/pm.py"), *args],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return result.stdout

    def test_catalog_drives_all_domain_menus_and_command_descriptions(self):
        catalog = json.loads(self.cli("action", "--catalog"))
        home = self.cli("action")
        for domain in catalog["domains"]:
            self.assertIn(domain, home)
            menu = self.cli("action", domain)
            paths = [path for path in catalog["commands"] if path.startswith(domain + " ")]
            self.assertTrue(paths)
            for subject in {path.rsplit(" ", 1)[0] for path in paths}:
                self.assertIn(f"/pm {subject}", menu)
                actions = self.cli("action", *subject.split())
                for path in paths:
                    if path.startswith(subject + " "):
                        self.assertIn(f"/pm {path}", actions)
                        description = json.loads(self.cli("action", "--describe", *path.split()))
                        self.assertEqual(description["command"], path)
                        self.assertEqual(description["summary"], catalog["commands"][path]["summary"])
        self.assertIn("Unknown oryx action",
                      self.cli("action", "initiative", "record", "apply", expected=1))
        self.assertIn("Unknown oryx domain", self.cli("action", "git", "workspace", "push", expected=1))

    def test_guided_action_returns_its_shared_guide_and_treats_arguments_as_data(self):
        arguments = ["checkout", "Pilot review", "A; B"]
        text = self.cli("action", "context", "meeting", "summarize", *arguments)
        result = json.loads(text)
        self.assertEqual(result["effect"], "guided")
        self.assertEqual(result["guide"], ".agents/skills/summarize-meeting/SKILL.md")
        self.assertEqual(result["arguments"], arguments)
        self.assertIn("Provide one complete action path",
                      self.cli("action", "--describe", "context", "meeting", expected=1))

    def test_new_declaration_reuses_parser_and_accepts_compatibility_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            path = root / hub_commands.CATALOG
            path.parent.mkdir()
            catalog = {
                "domains": {"workspace": "Personal settings and diagnostics."},
                "verbs": {"check": "Check the named subject."},
                "commands": {"workspace installation check": {
                    "summary": "Check the shared installation.", "effect": "read",
                    "cli": ["check"], "example": ["--system-only"],
                }},
                "aliases": {"workspace diagnostics": "workspace installation",
                            "workspace health check": "workspace installation check"},
            }
            path.write_text(json.dumps(catalog))
            hub_commands.load(root, pm.build_parser())
            output = StringIO()
            with redirect_stdout(output):
                self.assertIsNone(hub_commands.route(root, ["workspace", "diagnostics"]))
            self.assertIn("/pm workspace installation check", output.getvalue())
            for command in ("workspace installation check", "workspace diagnostics check", "workspace health check"):
                self.assertEqual(hub_commands.route(root, [*command.split(), "--system-only"]),
                                 ["check", "--system-only"])

            entry = catalog["commands"]["workspace installation check"]
            catalog["commands"]["workspace repeated check"] = entry
            path.write_text(json.dumps(catalog))
            with self.assertRaisesRegex(ValueError, "repeats the CLI target"):
                hub_commands.load(root, pm.build_parser())
            del catalog["commands"]["workspace repeated check"]
            entry["example"] = ["--unknown-option"]
            path.write_text(json.dumps(catalog))
            with self.assertRaisesRegex(ValueError, "does not match the terminal parser"):
                hub_commands.load(root, pm.build_parser())
            catalog["commands"]["workspace installation check"] = {
                "summary": "Check the shared installation.", "guide": "studio/context/pm/context.md",
            }
            path.write_text(json.dumps(catalog))
            with self.assertRaisesRegex(ValueError, "shared playbook or canonical skill"):
                hub_commands.load(root, pm.build_parser())

    def test_base_comparison_enforces_paths_effects_and_previous_examples(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()

            def git(*args):
                return subprocess.run(
                    ["git", "-C", str(root), "-c", "user.name=Fixture PM", "-c", "user.email=pm@example.com", *args],
                    capture_output=True, text=True, check=True,
                ).stdout.strip()

            git("init", "--quiet")
            git("commit", "--quiet", "--allow-empty", "-m", "Before the command catalog")
            no_catalog = git("rev-parse", "HEAD")
            path = root / hub_commands.CATALOG
            path.parent.mkdir()
            entry = {"summary": "Check the shared installation.", "effect": "read",
                     "cli": ["check"], "example": ["--system-only"]}
            catalog = {
                "domains": {"workspace": "Personal settings and diagnostics."},
                "verbs": {"check": "Check the named subject."},
                "commands": {"workspace health check": entry},
                "aliases": {"diagnostics": "workspace health"},
            }
            path.write_text(json.dumps(catalog))
            git("add", hub_commands.CATALOG)
            git("commit", "--quiet", "-m", "Publish a workspace command")
            base = git("rev-parse", "HEAD")
            parser = pm.build_parser()

            def compare(commit=base):
                path.write_text(json.dumps(catalog))
                return hub_commands.compatibility_errors(root, commit, hub_commands.load(root, parser), parser)

            self.assertEqual(compare(no_catalog), [])
            self.assertEqual(compare(), [])
            catalog["commands"] = {"workspace installation check": entry}
            catalog["aliases"] = {}
            self.assertEqual(len(compare()), 2)
            catalog["aliases"] = {"workspace health": "workspace installation",
                                  "diagnostics": "workspace installation"}
            self.assertEqual(compare(), [])
            entry["effect"] = "local-write"
            errors = compare()
            self.assertEqual(len(errors), 2)
            self.assertTrue(all("published effect" in error for error in errors))
            entry.update(effect="read", cli=["backlog"], example=["--due"])
            errors = compare()
            self.assertEqual(len(errors), 2)
            self.assertTrue(all("previous CLI example" in error for error in errors))
