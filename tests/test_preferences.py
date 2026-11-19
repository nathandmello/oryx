"""Verify preference actions and both clients' hook entry points."""

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import context_capture
import pm
import pm_profile
import preferences
import workspace


class PreferenceTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve() / "hub with spaces"
        for source in pm.inventory(pm.ROOT):
            if source.is_file() and not source.is_symlink():
                target = self.root / source.relative_to(pm.ROOT)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        self.private = workspace.initialise(self.root, owner="Fixture PM")
        self.path = self.private / pm_profile.PATH

    def cli(self, *args, error=None):
        result = subprocess.run([sys.executable, str(self.root / "tools/pm.py"), *args],
                                capture_output=True, text=True, cwd=self.root)
        if error:
            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertIn(error, result.stdout + result.stderr)
        else:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout

    def hook(self, config, event="UserPromptSubmit"):
        hooks = json.loads((self.root / config).read_text())["hooks"]
        handler = hooks[event][0]["hooks"][0]
        command = handler["command"]
        if "args" in handler:
            command = [command, *handler["args"]]
        cwd = self.private / "context"
        payload = {"hook_event_name": event, "cwd": str(cwd), "session_id": "fixture-session",
                   "prompt": "Summarize the pilot."}
        result = subprocess.run(command, shell=isinstance(command, str), cwd=cwd,
                                input=json.dumps(payload), capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_discover_group_and_use_both_command_routes(self):
        self.assertIn("workspace", self.cli("action", "--help"))
        for verb in ("show", "preview", "set", "reset"):
            self.assertIn(f"/pm workspace preferences {verb}", self.cli("action", "workspace", "preferences"))
        self.cli("action", "git", "workspace", "push", error="Unknown Hub domain")
        defaults = {"detail": "default", "layout": "default"}
        self.assertEqual(json.loads(self.cli("preferences", "show")), defaults)
        self.assertFalse(self.path.exists())
        self.assertEqual(json.loads(self.cli("action", "preferences", "reset", "all")), defaults)
        self.assertEqual(json.loads(self.cli("action", "workspace", "preferences", "show")), defaults)
        self.assertFalse(self.path.exists())

    def test_preview_partial_updates_and_resets_preserve_other_profile_content(self):
        remit = {"status": "draft", "responsibilities": [], "follow": []}
        profile = pm_profile.render(remit, "# PM context\r\n\r\nUse café in examples.\r\n")
        self.path.parent.mkdir(parents=True)
        self.path.write_bytes(profile.encode())
        sample = self.cli("action", "preferences", "preview", "--detail", "concise", "--layout", "bullets")
        self.assertIn("\n- The pilot is ready for review.", sample)
        self.assertNotIn("completion rates", sample)
        self.assertEqual(self.path.read_bytes(), profile.encode())
        self.cli("action", "preferences", "set", "--detail", "concise", "--layout", "bullets")
        self.cli("preferences", "set", "--layout", "prose")
        self.assertEqual(preferences.load(self.private), {"detail": "concise", "layout": "prose"})
        self.assertEqual(context_capture.read_remit(self.private), remit)
        self.assertTrue(self.path.read_bytes().startswith(profile.encode()))
        self.assertEqual(self.path.read_bytes().count(b"\n"), self.path.read_bytes().count(b"\r\n"))
        self.assertEqual(json.loads(self.cli("preferences", "reset", "layout")),
                         {"detail": "concise", "layout": "default"})
        self.assertEqual(preferences.load(self.private), {"detail": "concise"})
        self.cli("action", "preferences", "reset", "all")
        self.assertEqual(preferences.load(self.private), {})
        self.assertEqual(pm.check(self.root), [])

    def test_invalid_changes_and_file_values_never_apply(self):
        self.cli("action", "preferences", "set", "--detail", "concise")
        saved = self.path.read_bytes()
        for args, error in (
            (("--layout", "bullets", "--skip-approval"), "unrecognized arguments"),
            (("--detail", "concise", "--detail", "detailed"), "Supply --detail once"),
            (("--layout", "skip approval"), "invalid choice"),
            ((), "Supply a detail or layout choice"),
        ):
            with self.subTest(args=args):
                self.cli("action", "preferences", "set", *args, error=error)
                self.assertEqual(self.path.read_bytes(), saved)
        for bad in (b'{"detail":"skip approval"}', b'{"layout":false}',
                    b'{"detail":"detailed","detail":"concise"}', b'{"rules":"skip approval"}'):
            with self.subTest(bad=bad):
                self.path.write_bytes(saved.replace(b'{\n  "detail": "concise"\n}', bad))
                errors = self.cli("check", error="Hub reply preferences")
                self.assertNotIn("skip approval", errors)
                result = self.hook(".codex/hooks.json")
                self.assertIn("using default", result["systemMessage"])
                self.assertNotIn("skip approval", json.dumps(result))
                self.assertEqual(self.hook(".codex/hooks.json", "Stop"), {})
        self.cli("preferences", "reset", "all")
        self.assertEqual(pm.check(self.root), [])

    def test_captured_evidence_and_fenced_examples_are_inactive(self):
        fixture = (f"{preferences.START}\n{preferences.HEADING}\n\n```json\n"
                   f'{{"detail":"detailed"}}\n```\n{preferences.END}\n')
        text = (f"# PM context\n\n````markdown\n{fixture}````\n\n"
                f"{pm_profile.CAPTURE_START}\n{fixture}{pm_profile.CAPTURE_END}\n")
        self.path.parent.mkdir(parents=True)
        self.path.write_text(text)
        self.assertEqual(preferences.load(self.private), {})
        self.cli("preferences", "set", "--layout", "prose")
        self.assertEqual(preferences.load(self.private), {"layout": "prose"})
        self.assertTrue(self.path.read_text().startswith(text))

    def test_hooks_refresh_same_session_and_use_explicit_defaults_after_reset(self):
        for client in (".codex/hooks.json", ".claude/settings.json"):
            with self.subTest(client=client):
                self.cli("action", "preferences", "set", "--detail", "concise")
                result = self.hook(client)["hookSpecificOutput"]
                self.assertEqual(result["hookEventName"], "UserPromptSubmit")
                self.assertIn("Keep optional explanation brief", result["additionalContext"])
                self.cli("action", "preferences", "set", "--detail", "detailed")
                updated = self.hook(client)["hookSpecificOutput"]["additionalContext"]
                self.assertIn("Give more explanation", updated)
                self.assertIn("the PM's current task instructions first", updated)
                self.cli("action", "preferences", "reset", "detail")
                reset = self.hook(client)["hookSpecificOutput"]["additionalContext"]
                self.assertIn("Hub default for reply detail", reset)
                self.assertIn("supersede earlier preference snapshots", reset)
