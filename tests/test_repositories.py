"""Verify repository routing and updates against disposable local remotes."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
from unittest.mock import patch

import test_pm

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import git_ops
import pm
import records
import workspace


class RepositoryTests(unittest.TestCase):
    def setUp(self):
        environment = patch.dict(os.environ, {
            "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,
            "GIT_AUTHOR_NAME": "Fixture PM", "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
            "GIT_COMMITTER_NAME": "Fixture PM", "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
        })
        environment.start()
        self.addCleanup(environment.stop)
        test_pm.HubTests.setUp(self)

    def git(self, path, *args):
        return workspace.git(path, "-c", "commit.gpgsign=false", *args)

    def cli(self, *args, cwd=None):
        return subprocess.run([sys.executable, str(self.root / "tools/pm.py"), *args],
                              cwd=cwd or self.root, capture_output=True, text=True)

    def commit(self, path, message):
        self.git(path, "add", ".")
        self.git(path, "commit", "-m", message)

    def connect(self):
        settings = workspace.settings(self.root)
        self.remotes = {}
        for role, path in (("system", self.root), ("workspace", self.work)):
            remote = self.root.parent / f"{role}.git"
            self.git(self.root.parent, "init", "--bare", "--initial-branch=main", str(remote))
            self.git(path, "remote", "add", "origin", str(remote))
            settings["remotes"][role] = str(remote)
            self.remotes[role] = remote
        (self.work / "settings.json").write_text(json.dumps(settings, indent=2) + "\n")
        (self.work / "context/notes.md").write_text("# Notes\n\nFictional PM fixture.\n")
        self.commit(self.root, "Initial shared system")
        self.commit(self.work, "Initial private fixture")
        self.assertEqual(self.cli("git", "system", "push").returncode, 0)
        result = self.cli("git", "workspace", "push", cwd=self.work / "context")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def contributor(self, role):
        target = self.root.parent / f"{role}-contributor"
        self.git(self.root.parent, "clone", str(self.remotes[role]), str(target))
        return target

    def test_private_work_is_ignored_by_system_and_checked_explicitly(self):
        target = records.create(self.root, "problem", "products/example/problem.md")
        self.assertTrue(self.git(self.root, "check-ignore", str(target)))
        self.assertNotIn("workspace/", self.git(self.root, "ls-files", "--others", "--exclude-standard"))
        self.assertIn("products/example/problem.md", self.git(self.work, "ls-files", "--others", "--exclude-standard"))
        target.write_text(target.read_text().replace("| Mode | thought-partner |", "| Mode | invalid |"))
        self.assertTrue(any("Mode must" in error for error in pm.check(self.root)))
        self.assertEqual(pm.check(self.root, include_workspace=False), [])

    def test_setup_preserves_an_existing_workspace_and_never_adds_remotes(self):
        original = (self.work / "settings.json").read_bytes()
        with self.assertRaisesRegex(ValueError, "already exists"):
            workspace.initialise(self.root, owner="Someone else")
        self.assertEqual((self.work / "settings.json").read_bytes(), original)
        self.assertEqual(self.git(self.work, "remote"), "")
        self.assertEqual(self.git(self.root, "remote"), "")

    def test_workspace_navigation_opens_private_files_and_shared_rules(self):
        links = {match[1]: (self.work / match[2]).resolve()
                 for match in pm.LINK.finditer((self.work / "README.md").read_text())}
        self.assertEqual(links["context"], self.work / "context/README.md")
        self.assertEqual(links["products"], self.work / "products/README.md")
        self.assertEqual(links["constitution"], self.root / "AGENTS.md")
        self.assertEqual(links["the working practices"], self.root / "playbook/working.md")

    def test_new_command_uses_private_destination_and_configured_owner_from_nested_cwd(self):
        result = self.cli("new", "company-context", "context/company.md", "--title", "Company context",
                          cwd=self.work / "products")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        target = self.work / "context/company.md"
        self.assertIn("| Maintainer | Fixture PM |", target.read_text())
        self.assertTrue(self.git(self.root, "check-ignore", str(target)))
        self.assertEqual(pm.check(self.root), [])

    def test_private_secret_is_rejected_without_reading_its_contents(self):
        secret = self.work / ".env"
        secret.write_text("FICTIONAL_SECRET=fixture\n")
        self.git(self.work, "add", "--force", ".env")
        original = Path.read_text

        def read(path, *args, **kwargs):
            if path == secret:
                raise AssertionError("Private secret was read")
            return original(path, *args, **kwargs)

        with patch.object(Path, "read_text", read):
            self.assertTrue(any("private file" in error for error in pm.check(self.root)))

    def test_missing_private_git_cannot_fall_back_to_system(self):
        shutil.rmtree(self.work / ".git")
        with self.assertRaisesRegex(ValueError, "own local Git"):
            git_ops.run(self.root, "workspace", "status")
        self.assertTrue(any("own local Git" in error for error in pm.check(self.root)))

    def test_force_added_private_git_link_is_rejected_without_reading_data(self):
        self.commit(self.work, "Private fixture")
        self.git(self.root, "add", "--force", "workspace")
        original = Path.read_text

        def read(path, *args, **kwargs):
            if self.work in path.parents:
                raise AssertionError("Shared-only check read private data")
            return original(path, *args, **kwargs)

        with patch.object(Path, "read_text", read):
            errors = pm.check(self.root, include_workspace=False)
        self.assertTrue(any("must never be tracked" in error for error in errors))

    def test_both_native_hook_commands_work_from_private_context(self):
        payload = json.dumps({"hook_event_name": "Stop", "cwd": str(self.work / "context")})
        codex = subprocess.run(pm.CODEX_COMMAND, shell=True, cwd=self.work / "context", input=payload,
                               text=True, capture_output=True)
        config = json.loads((self.root / ".claude/settings.json").read_text())
        handler = config["hooks"]["Stop"][0]["hooks"][0]
        claude = subprocess.run([handler["command"], *handler["args"]], cwd=self.work / "context",
                                input=payload, text=True, capture_output=True)
        for result in (codex, claude):
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), {})

    def test_push_targets_separate_remotes_and_a_fresh_machine_restores_both(self):
        self.connect()
        system_files = self.git(self.remotes["system"], "ls-tree", "-r", "--name-only", "main")
        private_files = self.git(self.remotes["workspace"], "ls-tree", "-r", "--name-only", "main")
        self.assertNotIn("workspace/", system_files)
        self.assertNotIn("context/notes.md", system_files)
        self.assertIn("context/notes.md", private_files)
        restored = self.root.parent / "restored"
        self.git(self.root.parent, "clone", str(self.remotes["system"]), str(restored))
        self.assertEqual(pm.check(restored, include_workspace=False), [])
        self.git(restored, "clone", str(self.remotes["workspace"]), str(restored / "workspace"))
        self.assertEqual(pm.check(restored), [])

    def test_network_operations_require_confirmed_remote_and_detect_push_url_mismatch(self):
        with self.assertRaisesRegex(ValueError, "confirm the repository URL"):
            git_ops.run(self.root, "workspace", "fetch")
        self.connect()
        self.git(self.work, "remote", "set-url", "--push", "origin", str(self.remotes["system"]))
        with self.assertRaisesRegex(ValueError, "origin differs"):
            git_ops.run(self.root, "workspace", "push")

    def test_same_repository_cannot_serve_as_system_and_workspace(self):
        self.connect()
        settings = workspace.settings(self.root)
        settings["remotes"]["workspace"] = settings["remotes"]["system"]
        (self.work / "settings.json").write_text(json.dumps(settings))
        self.git(self.work, "remote", "set-url", "origin", str(self.remotes["system"]))
        with self.assertRaisesRegex(ValueError, "different remote"):
            git_ops.run(self.root, "workspace", "fetch")
        self.assertEqual(git_ops.identity("git@github.com:Example/Hub.git"),
                         git_ops.identity("https://github.com/example/hub"))

    def test_system_update_preserves_private_history_and_records_accepted_version(self):
        self.connect()
        private_head = self.git(self.work, "rev-parse", "HEAD")
        note = (self.work / "context/notes.md").read_bytes()
        source = self.contributor("system")
        metadata = workspace.release(source)
        metadata["system_version"] = "0.2.0"
        (source / "playbook/release.json").write_text(json.dumps(metadata) + "\n")
        self.commit(source, "Release a compatible system update")
        self.git(source, "push", "origin", "main")
        result = self.cli("git", "system", "pull", cwd=self.work)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.git(self.work, "rev-parse", "HEAD"), private_head)
        self.assertEqual((self.work / "context/notes.md").read_bytes(), note)
        self.assertEqual(workspace.settings(self.root)["system_version"], "0.2.0")

    def test_incompatible_system_update_stops_before_any_workspace_change(self):
        self.connect()
        old_head = self.git(self.root, "rev-parse", "HEAD")
        settings = (self.work / "settings.json").read_bytes()
        source = self.contributor("system")
        metadata = workspace.release(source)
        metadata["workspace_format"] = 2
        (source / "playbook/release.json").write_text(json.dumps(metadata) + "\n")
        self.commit(source, "Release an incompatible workspace format")
        self.git(source, "push", "origin", "main")
        with self.assertRaisesRegex(ValueError, "review a migration"):
            git_ops.run(self.root, "system", "pull")
        self.assertEqual(self.git(self.root, "rev-parse", "HEAD"), old_head)
        self.assertEqual((self.work / "settings.json").read_bytes(), settings)

    def test_workspace_pull_changes_only_private_repository(self):
        self.connect()
        system_head = self.git(self.root, "rev-parse", "HEAD")
        source = self.contributor("workspace")
        (source / "context/notes.md").write_text("# Notes\n\nUpdated fictional context.\n")
        self.commit(source, "Update private work")
        self.git(source, "push", "origin", "main")
        result = self.cli("git", "workspace", "pull")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.git(self.root, "rev-parse", "HEAD"), system_head)
        self.assertIn("Updated fictional context.", (self.work / "context/notes.md").read_text())

    def test_workspace_pull_cannot_silently_change_destinations(self):
        self.connect()
        old_head = self.git(self.work, "rev-parse", "HEAD")
        source = self.contributor("workspace")
        path = source / "settings.json"
        incoming = json.loads(path.read_text())
        incoming["remotes"]["workspace"] = "https://github.com/example/another-workspace.git"
        path.write_text(json.dumps(incoming))
        self.commit(source, "Change the expected destination")
        self.git(source, "push", "origin", "main")
        with self.assertRaisesRegex(ValueError, "review them before updating"):
            git_ops.run(self.root, "workspace", "pull")
        self.assertEqual(self.git(self.work, "rev-parse", "HEAD"), old_head)

    def test_push_ignores_follow_tags_and_refuses_mirror_configuration(self):
        self.connect()
        self.git(self.root, "config", "push.followTags", "true")
        self.git(self.root, "tag", "--no-sign", "--annotate", "fixture-tag", "--message", "Fixture tag")
        self.assertIn("Pushed system", git_ops.run(self.root, "system", "push"))
        self.assertEqual(self.git(self.remotes["system"], "tag"), "")
        self.git(self.root, "config", "remote.origin.mirror", "true")
        with self.assertRaisesRegex(ValueError, "Mirror remotes"):
            git_ops.run(self.root, "system", "push")

    def test_dirty_divergent_and_misdirected_tracking_stop_updates(self):
        self.connect()
        note = self.work / "context/notes.md"
        note.write_text("# Notes\n\nUncommitted fictional context.\n")
        with self.assertRaisesRegex(ValueError, "preserve local changes"):
            git_ops.run(self.root, "workspace", "pull")
        self.commit(self.work, "Local change")
        source = self.contributor("workspace")
        (source / "context/notes.md").write_text("# Notes\n\nRemote fictional context.\n")
        self.commit(source, "Remote change")
        self.git(source, "push", "origin", "main")
        with self.assertRaises(ValueError):
            git_ops.run(self.root, "workspace", "pull")
        self.assertIn("Uncommitted fictional context.", note.read_text())
        self.git(self.work, "config", "branch.main.merge", "refs/heads/other")
        with self.assertRaisesRegex(ValueError, "another destination"):
            git_ops.run(self.root, "workspace", "push")


if __name__ == "__main__":
    unittest.main()
