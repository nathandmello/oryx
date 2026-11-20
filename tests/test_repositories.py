"""Verify repository routing and updates against disposable local remotes."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import unittest
import zipfile
from unittest.mock import patch

import test_pm

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import git_ops
import pm
import records
import workspace
import storage


WORK_NOTE = ("# Notes\n\n## Scope\n\nCompare fixture offers.\n\n## Evidence\n\n{}\n\n"
             "## Next action\n\nReview the offers.\n")


def next_patch(version):
    major, minor, patch_version = map(int, version.split("."))
    return f"{major}.{minor}.{patch_version + 1}"


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
        (self.work / "workspace/backlogs").mkdir(parents=True)
        (self.work / "workspace/backlogs/compare-offers.md").write_text(WORK_NOTE.format("Fictional PM fixture."))
        self.commit(self.root, "Initial shared system")
        self.commit(self.work, "Initial private fixture")
        pushed = self.cli("git", "system", "push")
        self.assertEqual(pushed.returncode, 0, pushed.stdout + pushed.stderr)
        result = self.cli("git", "workspace", "push", cwd=self.work / "context")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def contributor(self, role):
        target = self.root.parent / f"{role}-contributor"
        self.git(self.root.parent, "clone", str(self.remotes[role]), str(target))
        return target

    def test_private_work_is_ignored_by_system_and_checked_explicitly(self):
        target = records.create(self.root, "problem", "workspace/problems/example.md")
        self.assertTrue(self.git(self.root, "check-ignore", str(target)))
        self.assertNotIn("studio/", self.git(self.root, "ls-files", "--others", "--exclude-standard"))
        self.assertIn("workspace/problems/example.md", self.git(self.work, "ls-files", "--others", "--exclude-standard"))
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
        self.assertEqual(links["workspace"], self.work / "workspace/README.md")
        self.assertEqual(links["constitution"], self.root / "AGENTS.md")
        self.assertEqual(links["the working practices"], self.root / "playbook/working.md")

    def test_new_command_uses_private_destination_and_configured_owner_from_nested_cwd(self):
        result = self.cli("new", "company-context", "context/company/overview.md", "--title", "Company context",
                          cwd=self.work / "workspace")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        target = self.work / "context/company/overview.md"
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

    def test_two_private_directories_require_resolution_without_choosing_one(self):
        legacy = self.root / "workspace"
        self.git(self.root, "init", "--quiet", "--initial-branch=main", str(legacy))
        original = b"Retained original bytes.\r\n"
        (legacy / "local.txt").write_bytes(original)
        settings = (self.work / "settings.json").read_bytes()
        for command in (("align", "--status"), ("align",), ("init-workspace",), ("git", "workspace", "status")):
            result = self.cli(*command)
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual((legacy / "local.txt").read_bytes(), original)
            self.assertEqual((self.work / "settings.json").read_bytes(), settings)
        self.assertFalse((legacy / "settings.json").exists())

    def test_all_colliding_roots_and_dangling_links_require_resolution(self):
        for existing, duplicate in (("studio", "private"), ("private", "workspace"), ("studio", "workspace")):
            with self.subTest(existing=existing, duplicate=duplicate):
                current = self.root / existing
                if current != self.work:
                    self.work.rename(current)
                extra = self.root / duplicate
                extra.mkdir()
                try:
                    with self.assertRaisesRegex(ValueError, "Multiple PM repository roots"):
                        pm.alignment(self.root, prepare=True)
                    self.assertTrue((current / "settings.json").is_file())
                    self.assertFalse((extra / "settings.json").exists())
                finally:
                    extra.rmdir()
                    if current != self.work:
                        current.rename(self.work)
        if os.name == "posix":
            link = self.root / "private"
            link.symlink_to(self.root.parent / "missing", target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "Multiple PM repository roots"):
                workspace.initialise(self.root)
            self.assertTrue(link.is_symlink())

    def test_studio_setup_rejects_pm_data_left_in_the_core_index(self):
        old = self.root.parent / "saved-checkout"
        self.work.rename(old)
        leaked = self.root / "private" / "secret.txt"
        leaked.parent.mkdir()
        leaked.write_text("fixture")
        self.git(self.root, "add", "-f", "private/secret.txt")
        leaked.unlink()
        leaked.parent.rmdir()
        with self.assertRaisesRegex(ValueError, "shared Git index"):
            workspace.initialise(self.root)
        self.assertFalse(self.work.exists())

    def test_case_variant_root_respects_filesystem_identity_and_stays_out_of_core(self):
        original = self.work / "settings.json"
        before = original.read_bytes()
        # Use an intermediate name so a case-only rename works on either type of filesystem.
        transient = self.root.parent / "saved-case"
        self.work.rename(transient)
        variant = self.root / "Studio"
        transient.rename(variant)
        self.assertTrue(self.git(self.root, "check-ignore", "--", "Studio/settings.json"))
        if self.work.exists():
            self.assertTrue(self.work.samefile(variant))
            self.assertEqual(workspace.private_root(self.root), variant)
            self.assertNotIn("private_root_move", pm.alignment(self.root, prepare=True))
        else:
            for operation in (lambda: workspace.initialise(self.root), lambda: pm.alignment(self.root, True)):
                with self.assertRaisesRegex(ValueError, "lowercase"):
                    operation()
            self.assertFalse(self.work.exists())
        self.assertEqual((variant / "settings.json").read_bytes(), before)

    def test_missing_private_git_cannot_fall_back_to_system(self):
        shutil.rmtree(self.work / ".git")
        with self.assertRaisesRegex(ValueError, "own local Git"):
            git_ops.run(self.root, "workspace", "status")
        self.assertTrue(any("own local Git" in error for error in pm.check(self.root)))

    def test_force_added_private_git_link_is_rejected_without_reading_data(self):
        self.commit(self.work, "Private fixture")
        self.git(self.root, "add", "--force", "studio")
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
        self.assertNotIn("studio/", system_files)
        self.assertNotIn("workspace/backlogs/compare-offers.md", system_files)
        self.assertIn("workspace/backlogs/compare-offers.md", private_files)
        restored = self.root.parent / "restored"
        self.git(self.root.parent, "clone", str(self.remotes["system"]), str(restored))
        self.assertEqual(pm.check(restored, include_workspace=False), [])
        self.git(restored, "clone", str(self.remotes["workspace"]), str(restored / "studio"))
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
        note = (self.work / "workspace/backlogs/compare-offers.md").read_bytes()
        source = self.contributor("system")
        wire_file = source / "playbook/release.json"
        metadata = json.loads(wire_file.read_text())
        metadata["system_version"] = next_patch(metadata["system_version"])
        wire_file.write_text(json.dumps(metadata) + "\n")
        self.commit(source, "Release a compatible system update")
        self.git(source, "push", "origin", "main")
        result = self.cli("git", "system", "pull", cwd=self.work)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.git(self.work, "rev-parse", "HEAD"), private_head)
        self.assertEqual((self.work / "workspace/backlogs/compare-offers.md").read_bytes(), note)
        self.assertEqual(workspace.settings(self.root)["system_version"], metadata["system_version"])

    def test_core_pull_retires_only_a_fully_covered_override(self):
        self.connect()
        contributor = self.contributor("system")
        desired = {"scope": "Weekly reviews", "behavior": "Show decisions first, then an owner."}
        rule = self.cli("override", "set", "weekly-review-order", "--scope", desired["scope"],
                        "--behavior", desired["behavior"])
        self.assertEqual(rule.returncode, 0, rule.stdout)
        for complete in (False, True):
            default = desired if complete else dict(desired, behavior="Show decisions first.")
            (contributor / "playbook/workflow-defaults.json").write_text(json.dumps({"weekly-review-order": default}))
            self.commit(contributor, "Publish the next weekly review default")
            self.git(contributor, "push", "origin", "main")
            if complete:
                self.git(self.root, "pull", "--ff-only")
                payload = json.dumps({"hook_event_name": "SessionStart", "cwd": str(self.root)})
                result = subprocess.run(pm.CODEX_COMMAND, shell=True, cwd=self.root, input=payload,
                                        capture_output=True, text=True)
            else:
                result = self.cli("git", "system", "pull")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            state = json.loads(self.cli("override", "list").stdout)
            self.assertEqual(state["effective"]["weekly-review-order"], [desired])
            self.assertEqual("weekly-review-order" in state["rules"], not complete)
            self.assertEqual(len(state["retired"]), int(complete))

    def test_ordinary_shared_pull_aligns_forward_same_format_with_a_backup(self):
        self.connect()
        source = self.contributor("system")
        path = source / "playbook/release.json"
        release = json.loads(path.read_text())
        previous = release["system_version"]
        release["system_version"] = next_patch(previous)
        path.write_text(json.dumps(release) + "\n")
        self.commit(source, "Release a same-format patch")
        self.git(source, "push", "origin", "main")
        self.git(self.root, "pull", "--ff-only", "origin", "main")
        settings = self.work / "settings.json"
        original = settings.read_bytes()
        self.assertTrue(pm.alignment(self.root)["needs_setup"])
        self.assertEqual(settings.read_bytes(), original)
        report = pm.alignment(self.root, prepare=True)
        with tarfile.open(report["installation_backup"]) as backup:
            self.assertEqual(backup.extractfile("studio/settings.json").read(), original)
        self.assertEqual(workspace.settings(self.root)["system_version"], release["system_version"])
        (self.root / "playbook/release.json").write_text(json.dumps(dict(release, system_version=previous)))
        with self.assertRaisesRegex(ValueError, "Unsupported workspace version"):
            pm.alignment(self.root, prepare=True)
        self.assertEqual(workspace.settings(self.root, compatible=False)["system_version"], release["system_version"])

    def test_system_pull_merges_the_commit_it_inspected_after_another_fetch(self):
        self.connect()
        source = self.contributor("system")
        wire_file = source / "playbook/release.json"
        release = json.loads(wire_file.read_text())
        release["system_version"] = next_patch(release["system_version"])
        wire_file.write_text(json.dumps(release))
        self.commit(source, "Release the checked patch")
        self.git(source, "push", "origin", "main")
        expected = self.git(source, "rev-parse", "HEAD")
        previous = self.git(self.root, "rev-parse", "HEAD")

        git = workspace.git
        def another_fetch(path, *args):
            result = git(path, *args)
            if args == ("rev-parse", "FETCH_HEAD^{commit}"):
                (path / ".git/FETCH_HEAD").write_text(previous + "\n")
            return result

        with patch.object(workspace, "git", side_effect=another_fetch):
            git_ops.run(self.root, "system", "pull")
        self.assertEqual(self.git(self.root, "rev-parse", "HEAD"), expected)
        self.assertEqual(workspace.settings(self.root)["system_version"], release["system_version"])

    def test_incompatible_system_update_stops_before_any_workspace_change(self):
        self.connect()
        old_head = self.git(self.root, "rev-parse", "HEAD")
        settings = (self.work / "settings.json").read_bytes()
        source = self.contributor("system")
        format_file = source / workspace.FORMAT_FILE
        metadata = json.loads(format_file.read_text())
        metadata["workspace_format"] = 99
        format_file.write_text(json.dumps(metadata) + "\n")
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
        (source / "workspace/backlogs/compare-offers.md").write_text(WORK_NOTE.format("Updated fictional context."))
        self.commit(source, "Update private work")
        self.git(source, "push", "origin", "main")
        result = self.cli("git", "workspace", "pull")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.git(self.root, "rev-parse", "HEAD"), system_head)
        self.assertIn("Updated fictional context.", (self.work / "workspace/backlogs/compare-offers.md").read_text())

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
        note = self.work / "workspace/backlogs/compare-offers.md"
        note.write_text(WORK_NOTE.format("Uncommitted fictional context."))
        with self.assertRaisesRegex(ValueError, "preserve local changes"):
            git_ops.run(self.root, "workspace", "pull")
        self.commit(self.work, "Local change")
        source = self.contributor("workspace")
        (source / "workspace/backlogs/compare-offers.md").write_text(WORK_NOTE.format("Remote fictional context."))
        self.commit(source, "Remote change")
        self.git(source, "push", "origin", "main")
        with self.assertRaises(ValueError):
            git_ops.run(self.root, "workspace", "pull")
        self.assertIn("Uncommitted fictional context.", note.read_text())
        self.git(self.work, "config", "branch.main.merge", "refs/heads/other")
        with self.assertRaisesRegex(ValueError, "another destination"):
            git_ops.run(self.root, "workspace", "push")

    def test_shared_update_refuses_to_track_the_private_tree(self):
        self.connect()
        contributor = self.contributor("system")
        head = self.git(self.root, "rev-parse", "HEAD")
        local = self.work / "local-notes.md"
        local.write_text("Original private untracked bytes.")
        collision = contributor / "studio/local-notes.md"
        collision.parent.mkdir()
        collision.write_text("Incoming shared path")
        self.git(contributor, "add", "-f", "studio/local-notes.md")
        self.git(contributor, "commit", "-m", "Fictional accidental private-tree collision")
        self.git(contributor, "push", "origin", "main")
        with self.assertRaisesRegex(ValueError, "tracks the private workspace"):
            git_ops.run(self.root, "system", "pull")
        self.assertEqual(self.git(self.root, "rev-parse", "HEAD"), head)
        self.assertEqual(local.read_text(), "Original private untracked bytes.")

    def test_system_sync_refuses_private_history_even_when_removed_from_tip(self):
        self.connect()
        remote = self.remotes["system"]
        head = self.git(remote, "rev-parse", "main")
        contributor = self.contributor("system")
        for checkout, name in ((self.root, "PriVate"), (contributor, "STuDio")):
            fixture = checkout / name / "made-up-record.txt"
            fixture.parent.mkdir()
            fixture.write_text("Synthetic file history")
            self.git(checkout, "add", "--force", "--", fixture.relative_to(checkout).as_posix())
            self.git(checkout, "commit", "-m", "Accidental synthetic PM file")
            self.git(checkout, "rm", "--", fixture.relative_to(checkout).as_posix())
            self.git(checkout, "commit", "-m", "Remove synthetic PM file")
        with self.assertRaisesRegex(ValueError, "tracks the private workspace"):
            git_ops.run(self.root, "system", "push")
        self.assertEqual(self.git(remote, "rev-parse", "main"), head)
        # A raw Git client can publish this synthetic history to our disposable local remote.
        self.git(contributor, "push", "origin", "main")
        self.git(self.root, "reset", "--hard", head)
        with self.assertRaisesRegex(ValueError, "tracks the private workspace"):
            git_ops.run(self.root, "system", "pull")
        self.assertEqual(self.git(self.root, "rev-parse", "HEAD"), head)

    def test_official_private_push_checks_recovery_bytes_in_the_commit(self):
        import conversion
        import upgrades
        self.connect()
        archive = conversion.archive_path(self.work, "board-fold")
        archive.parent.mkdir()
        archive.write_bytes(b"Fictional recovery blob")
        ledger = self.work / upgrades.LEDGER
        state = json.loads(ledger.read_text())
        state[upgrades.TRANSACTIONS] = {"board-fold": upgrades.fingerprint(archive)}
        ledger.write_text(upgrades.encode(state))
        ignore = self.work / ".gitignore"
        ignore.write_text(ignore.read_text() + "\n*.zip\n")
        self.commit(self.work, "Save private ledger, accidentally omit recovery")
        result = self.cli("git", "workspace", "push")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("verified recovery archive in the private commit", result.stdout)
        self.git(self.work, "add", "-f", ".hub-history/board-fold.zip")
        self.git(self.work, "commit", "-m", "Preserve the private recovery blob")
        self.assertEqual(self.cli("git", "workspace", "push").returncode, 0)

    def test_second_machine_can_fast_forward_an_identical_uncommitted_layout_migration(self):
        self.connect()
        # Publish a private format-1 tree, then independently open it in two installations of the new Hub.
        test_pm.use_previous_layout(self.work)
        original = test_pm.legacy_product(self.root, self.work, "products/shop/context.md")
        original.write_text(original.read_text() + "\nA repeat customer can request a receipt.\n")
        self.commit(self.work, "Last private format-1 save")
        self.git(self.work, "push", "origin", "main")
        previous = self.git(self.work, "rev-parse", "HEAD")
        installations = []
        for name in ("first-machine", "second-machine"):
            outer = self.root.parent / name
            self.git(self.root.parent, "clone", str(self.remotes["system"]), str(outer))
            self.git(outer, "clone", str(self.remotes["workspace"]), str(outer / "workspace"))
            pm.alignment(outer, prepare=True)
            installations.append(outer / "studio")
        first, second = installations
        self.commit(first, "Save migrated private layout")
        git_ops.run(first.parent, "workspace", "push")
        target = self.git(first, "rev-parse", "HEAD")
        self.assertEqual(self.git(second, "rev-parse", "HEAD"), previous)

        path = second / "context/products/shop/overview.md"
        original = path.read_bytes()

        def refused():
            index = self.git(second, "write-tree")
            with self.assertRaisesRegex(ValueError, "preserve local changes"):
                git_ops.run(second.parent, "workspace", "pull")
            self.assertEqual(self.git(second, "write-tree"), index)
            self.assertEqual(self.git(second, "rev-parse", "HEAD"), previous)
            self.assertFalse((second / ".git" / git_ops.HANDOFF).exists())

        path.write_bytes(original + b"\nA local revision.\n")
        refused()
        self.assertTrue(path.read_bytes().endswith(b"A local revision.\n"))
        self.git(second, "add", "--", str(path))
        path.write_bytes(original)  # An exact worktree must not hide a distinct staged version.
        refused()
        self.assertIn("A local revision.", self.git(second, "show", ":context/products/shop/overview.md"))
        self.git(second, "reset", "--quiet", "HEAD", "--", str(path))
        local = second / "untracked.txt"
        local.write_text("Material from the second machine.\n")
        refused()
        self.assertTrue(local.exists())
        local.unlink()
        ignore = second / ".git/info/exclude"
        exclusions = ignore.read_bytes()
        ignore.write_bytes(exclusions + b"\n/context/products/shop/overview.md\n")
        refused()
        retired = second / "products/shop/context.md"
        retired.parent.mkdir(parents=True, exist_ok=True)
        retired.write_bytes(b"An independent copy left in an ignored directory.\n")
        ignore.write_bytes(exclusions + b"\n/products/\n")
        refused()
        self.assertTrue(retired.read_bytes().startswith(b"An independent copy"))
        retired.unlink()
        ignore.write_bytes(exclusions)

        real_git = workspace.git
        def interrupted(repo, *args):
            if args[0] == "update-ref":
                raise OSError("interrupted during fast-forward")
            return real_git(repo, *args)

        with patch.object(workspace, "git", side_effect=interrupted), self.assertRaises(OSError):
            git_ops.run(second.parent, "workspace", "pull")
        self.assertEqual(self.git(second, "rev-parse", "HEAD"), previous)
        self.assertEqual(self.git(second, "write-tree"), self.git(first, "rev-parse", "HEAD^{tree}"))
        self.assertTrue((second / ".git" / git_ops.HANDOFF).exists())
        before = {p.relative_to(second): p.read_bytes() for p in pm.inventory(second) if p.is_file()}
        git_ops.run(second.parent, "workspace", "pull")
        self.assertEqual(self.git(second, "rev-parse", "HEAD"), target)
        self.assertEqual(self.git(second, "status", "--porcelain"), "")
        self.assertFalse((second / ".git" / git_ops.HANDOFF).exists())
        self.assertEqual(before, {p.relative_to(second): p.read_bytes() for p in pm.inventory(second) if p.is_file()})
        self.assertEqual(pm.check(second.parent), [])

    def test_restored_format_two_studios_can_pull_only_an_identical_unstaged_migration(self):
        self.connect()
        legacy = ".hub-overrides.json"
        current = "customizations/rules.json"
        (self.work / legacy).write_text(json.dumps({"rules": {}, "retired": [], "reports": {},
                                                   "pending": [], "reporting": False}))
        self.commit(self.work, "Save pre-Studio layout at the same workspace format")
        self.git(self.work, "push", "origin", "main")
        old = self.git(self.work, "rev-parse", "HEAD")
        clone = self.root.parent / "second"
        self.git(self.root.parent, "clone", str(self.remotes["system"]), str(clone))
        self.git(clone, "clone", str(self.remotes["workspace"]), str(clone / "private"))
        pm.alignment(self.root, prepare=True)
        pm.alignment(clone, prepare=True)
        self.commit(self.work, "Save Studio layout")
        git_ops.run(self.root, "workspace", "push")
        second = clone / "studio"
        path = second / current
        original = path.read_bytes()
        path.write_bytes(original + b" ")
        self.git(second, "add", "--", current)
        staged = self.git(second, "write-tree")
        path.write_bytes(original)
        with self.assertRaisesRegex(ValueError, "preserve local changes"):
            git_ops.run(clone, "workspace", "pull")
        self.assertEqual(self.git(second, "write-tree"), staged)
        self.assertEqual(self.git(second, "rev-parse", "HEAD"), old)
        self.git(second, "reset", "HEAD", "--", current)
        extra = second / "local-only.dat"
        extra.write_bytes(b"untracked work")
        with self.assertRaisesRegex(ValueError, "preserve local changes"):
            git_ops.run(clone, "workspace", "pull")
        self.assertEqual(extra.read_bytes(), b"untracked work")
        extra.unlink()
        git_ops.run(clone, "workspace", "pull")
        self.assertEqual(self.git(second, "rev-parse", "HEAD"), self.git(self.work, "rev-parse", "HEAD"))
        self.assertEqual(self.git(second, "status", "--porcelain"), "")
        self.assertEqual(path.read_bytes(), original)

    def test_same_version_receipt_only_migration_can_precede_a_later_pm_commit(self):
        import upgrades
        self.connect()
        ledger = self.work / upgrades.LEDGER
        previous = json.loads(ledger.read_text())
        previous.pop(upgrades.STUDIO_GUIDES)
        ledger.write_text(upgrades.encode(previous))
        self.commit(self.work, "Pre-Studio private receipt at the same system version")
        self.git(self.work, "push", "origin", "main")
        other = self.root.parent / "restored"
        self.git(self.root.parent, "clone", str(self.remotes["system"]), str(other))
        self.git(other, "clone", str(self.remotes["workspace"]), "private")
        pm.alignment(self.root, prepare=True)
        pm.alignment(other, prepare=True)
        self.commit(self.work, "Accept Studio guide inventory")
        (self.work / "context/field-note.txt").write_text("Keep the agreed date.")
        self.commit(self.work, "Save the following PM work")
        git_ops.run(self.root, "workspace", "push")
        git_ops.run(other, "workspace", "pull")
        self.assertEqual(self.git(other / "studio", "status", "--porcelain"), "")
        self.assertEqual((other / "studio/context/field-note.txt").read_text(), "Keep the agreed date.")

    def test_second_format_two_machine_accepts_a_version_only_update(self):
        self.connect()
        settings = workspace.settings(self.root)
        (self.work / "settings.json").write_text(json.dumps(dict(settings, system_version="0.10.0")))
        self.commit(self.work, "Save a format-two workspace from the preceding release")
        self.git(self.work, "push", "origin", "main")
        clone = self.root.parent / "second"
        self.git(self.root.parent, "clone", str(self.remotes["system"]), str(clone))
        self.git(clone, "clone", str(self.remotes["workspace"]), str(clone / "private"))
        pm.alignment(self.root, prepare=True)
        pm.alignment(clone, prepare=True)
        self.commit(self.work, "Save accepted system version")
        git_ops.run(self.root, "workspace", "push")
        git_ops.run(clone, "workspace", "pull")
        second = clone / "studio"
        self.assertEqual(self.git(second, "rev-parse", "HEAD"), self.git(self.work, "rev-parse", "HEAD"))
        self.assertEqual(self.git(second, "status", "--porcelain"), "")
        self.assertEqual(workspace.settings(clone), settings)
        # An unrelated identical edit in two ordinary worktrees is outside migration handoff.
        for copy in (self.work, second):
            (copy / "local-note.txt").write_text("Matching independent work")
        self.commit(self.work, "A later ordinary change")
        git_ops.run(self.root, "workspace", "push")
        with self.assertRaisesRegex(ValueError, "preserve local changes"):
            git_ops.run(clone, "workspace", "pull")
        self.assertEqual((second / "local-note.txt").read_text(), "Matching independent work")

    def interrupt_historical_filing(self, outer, private):
        """Run the installed 0.2 converter and interrupt it after recovering the loose record."""
        import hashlib
        main = private / "context/company.md"
        loose = private / "decision-from-meeting.md"
        quote = "The original access policy applies to every region."
        loose.write_bytes((quote + "\r\n").encode())
        original = loose.read_bytes()
        plan = {"id": "recover-access", "reason": "Keep the approved scope in the existing brief.",
                "changes": [
                    {"path": "context/company.md", "before": hashlib.sha256(main.read_bytes()).hexdigest(),
                     "text": main.read_text() + "\n" + quote + "\n"},
                    {"path": loose.name, "before": hashlib.sha256(original).hexdigest(), "into": "context/company.md"}]}
        # sys.path points at the historical checkout; the new migration code has not been installed.
        script = """import json, sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, 'tools')
import conversion, pm, storage, upgrades
private = Path('workspace').resolve()
write = storage.replace_text
def interrupted(target, *args):
    if target == private / upgrades.LEDGER:
        raise OSError('simulated interrupted ledger write')
    return write(target, *args)
with storage.writer_lock(private), patch.object(storage, 'replace_text', side_effect=interrupted):
    try:
        conversion.apply(private, json.load(sys.stdin), pm.filing_validator(private.parent), pm.LINK)
    except OSError as exc:
        assert str(exc) == 'simulated interrupted ledger write'
    else:
        raise AssertionError('expected interruption after applying the historical plan')
"""
        proc = subprocess.run([sys.executable, "-c", script], cwd=outer, input=json.dumps(plan),
                              text=True, capture_output=True)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertTrue((private / ".hub-filing-pending.json").is_file())
        self.assertFalse(loose.exists())
        return loose.name, original, quote

    def preceding_release_remote(self):
        prior = "a3f09f76eb158e5f9637f4afb056be22f361d043"  # Released 0.10.0 wrapper.
        base = self.root.parent
        publisher = base / "publisher"
        self.git(base, "clone", "--quiet", "--no-local", "--no-checkout", str(pm.ROOT), str(publisher))
        self.git(publisher, "checkout", "--quiet", "-B", "main", prior)
        self.git(publisher, "rm", "-qr", ".")
        for path in pm.inventory(pm.ROOT):
            if path.is_file():
                destination = publisher / path.relative_to(pm.ROOT)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, destination)
        self.commit(publisher, "Current Hub candidate")
        origin = base / "candidate.git"
        self.git(base, "clone", "--quiet", "--bare", str(publisher), str(origin))
        return prior, origin

    def test_released_original_and_restored_studios_adopt_only_verified_private_work(self):
        self.verify_released_studio_restore(custom_guide=False)

    def test_released_studios_with_a_committed_custom_guide_converge(self):
        self.verify_released_studio_restore(custom_guide=True)

    def verify_released_studio_restore(self, *, custom_guide):
        prior, origin = self.preceding_release_remote()
        base = self.root.parent
        machines = [base / name for name in ("primary", "restored", "delayed", "edited")]
        primary, restored, delayed, edited = machines
        private_remote = base / "pm.git"

        def command(machine, *args, success=True):
            result = subprocess.run([sys.executable, "-B", str(machine / "tools/pm.py"), *args],
                                    cwd=machine, text=True, capture_output=True)
            self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)
            return result.stdout

        for machine in machines:
            self.git(base, "clone", "--quiet", str(origin), str(machine))
            self.git(machine, "reset", "--hard", prior)
        command(primary, "init-workspace", "--owner", "Fixture PM")
        command(primary, "new", "goal", "workspace/goals/launch.md")
        old = primary / "private"
        old_readme = (old / "README.md").read_bytes()
        if custom_guide:
            old_readme += b"\nBring the signed dates to the Friday review.\n"
            (old / "README.md").write_bytes(old_readme)
        settings = json.loads((old / "settings.json").read_text())
        settings["remotes"] = {"system": str(origin), "workspace": str(private_remote)}
        (old / "settings.json").write_text(json.dumps(settings, indent=2) + "\n")
        self.commit(old, "Released PM workspace")
        self.git(base, "clone", "--quiet", "--bare", str(old), str(private_remote))
        self.git(old, "remote", "add", "origin", str(private_remote))
        for machine in machines[1:]:
            self.git(machine, "clone", "--quiet", str(private_remote), "private")
        edited_guide = edited / "private/README.md"
        edited_guide.write_bytes(old_readme + b"\nUse the Friday review.\n")
        self.git(edited / "private", "add", "--", "README.md")
        staged = self.git(edited / "private", "rev-parse", ":README.md")
        working = edited_guide.read_bytes() + b"\nReview signed dates.\n"
        edited_guide.write_bytes(working)
        for machine in machines:
            command(machine, "git", "system", "pull")
        for machine in (primary, restored, delayed):
            self.assertEqual((machine / "studio/README.md").read_bytes(), old_readme)
            self.assertEqual((machine / "studio/.hub-upgrades.json").read_bytes(),
                             (primary / "studio/.hub-upgrades.json").read_bytes())
        primary_reviews = json.loads((primary / "studio/.hub-upgrades.json").read_text())["record-filing-0.2"]
        self.assertEqual("README.md" in primary_reviews, custom_guide)
        if custom_guide:
            self.assertEqual(primary_reviews["README.md"]["status"], "pending")
        self.assertIn("README.md", json.loads((edited / "studio/.hub-upgrades.json").read_text())["record-filing-0.2"])
        self.commit(primary / "studio", "Save verified migration")
        command(primary, "git", "workspace", "push")
        command(restored, "git", "workspace", "pull")
        self.assertEqual(self.git(restored / "studio", "status", "--porcelain"), "")
        command(primary, "override", "set", "contract-review", "--scope", "Contract review",
                "--behavior", "Name the renewal owner.")
        self.commit(primary / "studio", "Continue work after migration")
        command(primary, "git", "workspace", "push")
        command(delayed, "git", "workspace", "pull")
        self.assertEqual(self.git(delayed / "studio", "rev-parse", "HEAD"),
                         self.git(primary / "studio", "rev-parse", "HEAD"))
        self.assertEqual(self.git(delayed / "studio", "status", "--porcelain"), "")
        self.assertIn("preserve local changes", command(edited, "git", "workspace", "pull", success=False))
        self.assertEqual((edited / "studio/README.md").read_bytes(), working)
        self.assertEqual(self.git(edited / "studio", "rev-parse", ":README.md"), staged)

    def test_fresh_studio_restore_keeps_current_handoffs_and_discovers_other_unfiled_work(self):
        self.connect()
        guides = ("README.md", "workspace/README.md", "context/README.md")
        guide_bytes = {}
        for name in guides:
            path = self.work / name
            guide_bytes[name] = path.read_bytes() + b"\nUse Friday for our planning review.\n"
            path.write_bytes(guide_bytes[name])
        self.commit(self.work, "Save PM-authored handoffs after Studio setup")
        self.git(self.work, "push", "origin", "main")
        target = self.root.parent / "restored-current"
        self.git(self.root.parent, "clone", str(self.remotes["system"]), str(target))
        self.git(target, "clone", str(self.remotes["workspace"]), "studio")
        private = target / "studio"
        self.assertEqual(pm.alignment(target, True)["outstanding"], [])
        self.assertEqual(self.git(private, "status", "--porcelain"), "")
        for name in guides:
            self.assertEqual((private / name).read_bytes(), guide_bytes[name])
        # A different restoration also brings a loose PM record which still needs filing review.
        other = self.root.parent / "restored-with-notes"
        self.git(self.root.parent, "clone", str(self.remotes["system"]), str(other))
        self.git(other, "clone", str(self.remotes["workspace"]), "studio")
        (other / "studio/negotiation-notes.md").write_text("# Negotiation notes\n")
        outstanding = pm.alignment(other, True)["outstanding"]
        self.assertEqual([item["path"] for item in outstanding], ["negotiation-notes.md"])

    def test_last_private_release_updates_to_studio_by_wrapper_and_direct_pull(self):
        prior, origin = self.preceding_release_remote()
        base = self.root.parent
        for method in ("wrapper", "direct"):
            with self.subTest(method=method):
                consumer = base / method
                self.git(base, "clone", "--quiet", str(origin), str(consumer))
                self.git(consumer, "reset", "--hard", prior)

                def command(*args):
                    result = subprocess.run([sys.executable, "-B", str(consumer / "tools/pm.py"), *args],
                                            cwd=consumer, text=True, capture_output=True)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    return result.stdout
                command("init-workspace", "--owner", "Fixture PM")
                old = consumer / "private"
                settings = json.loads((old / "settings.json").read_text())
                settings["remotes"]["system"] = str(origin)
                (old / "settings.json").write_text(json.dumps(settings))
                tracked = Path("context/sources/a PM's notes.txt")
                (old / tracked).parent.mkdir(exist_ok=True)
                (old / tracked).write_bytes(b"committed\r\n")
                self.commit(old, "Private fixture history")
                private_head = self.git(old, "rev-parse", "HEAD")
                (old / tracked).write_bytes(b"staged\r\n")
                self.git(old, "add", "--", str(tracked))
                staged_blob = self.git(old, "rev-parse", ":" + tracked.as_posix())
                (old / tracked).write_bytes(b"working\r\n")
                (old / ".env.local").write_bytes(b"ignored\x00bytes")
                loose = Path("context/sources/untracked.dat")
                (old / loose).write_bytes(b"untracked\x00bytes")
                if method == "wrapper":
                    command("git", "system", "pull")
                else:
                    self.git(consumer, "pull", "--ff-only")
                    self.assertEqual(json.loads(command("align", "--status"))["private_root_move"],
                                     {"from": "private", "to": "studio"})
                    self.assertTrue(old.is_dir())
                    command("align")
                studio = consumer / "studio"
                self.assertFalse(old.exists())
                self.assertEqual(self.git(studio, "rev-parse", "HEAD"), private_head)
                self.assertEqual(self.git(studio, "rev-parse", ":" + tracked.as_posix()), staged_blob)
                self.assertEqual((studio / tracked).read_bytes(), b"working\r\n")
                self.assertEqual((studio / loose).read_bytes(), b"untracked\x00bytes")
                self.assertEqual((studio / ".env.local").read_bytes(), b"ignored\x00bytes")
                self.assertEqual(self.git(consumer, "status", "--porcelain"), "")
                with self.assertRaisesRegex(ValueError, "repository moved"):
                    with storage.writer_lock(old):
                        self.fail("Writer received a lock on the retired path")
                self.assertNotIn("private_root_move", json.loads(command("align")))
                self.assertIn("PASS", command("check"))

    def test_published_updaters_reach_the_new_layout_and_preserve_private_history(self):
        revisions = {"0.1.0": "315e31ab6ed46bf72ef72faa8e18225b7d091093",
                     "0.2.0": "bcf127d23698b8002d5e898a84d7a506289add98"}
        missing = [sha for sha in revisions.values() if subprocess.run(
            ["git", "-C", str(pm.ROOT), "cat-file", "-e", f"{sha}^{{commit}}"], capture_output=True).returncode]
        if missing:
            if os.environ.get("GITHUB_ACTIONS") == "true":
                self.fail("Full published Git history is required for consumer update checks")
            self.skipTest("Historical updater verification requires the published Git history")

        current = workspace.release(pm.ROOT)["system_version"]
        for version, interrupted, target_version in (("0.1.0", False, current), ("0.2.0", False, current),
                                                     ("0.2.0", True, current), ("0.2.0", False, next_patch(current))):
            with self.subTest(version=version, interrupted=interrupted, target_version=target_version):
                sha = revisions[version]
                fixture = f"{version}-to-{target_version}" + ("-interrupted" if interrupted else "")
                outer = self.root.parent / f"consumer-{fixture}"
                self.git(self.root.parent, "clone", "--quiet", "--no-checkout", "--no-local", str(pm.ROOT), str(outer))
                self.git(outer, "checkout", "--quiet", "-B", "main", sha)
                origin = self.root.parent / f"system-{fixture}.git"
                self.git(self.root.parent, "init", "--bare", "--initial-branch=main", str(origin))
                self.git(outer, "remote", "set-url", "origin", str(origin))
                self.git(outer, "push", "--set-upstream", "origin", "main")

                def command(*args):
                    result = subprocess.run([sys.executable, str(outer / "tools/pm.py"), *args], cwd=outer,
                                            text=True, capture_output=True)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    return result.stdout

                command("init-workspace", "--owner", "Fixture PM")
                command("new", "company-context", "context/company.md", "--title", "Standing guidance")
                legacy = outer / "workspace"
                settings_file = legacy / "settings.json"
                settings = json.loads(settings_file.read_text())
                self.assertEqual((settings["workspace_format"], settings["system_version"]), (1, version))
                settings["remotes"]["system"] = str(origin)
                settings_file.write_text(json.dumps(settings))
                evidence = legacy / "context/company.md"
                text = evidence.read_text()
                before_id = records.work_state(text)[0]["ID"]
                evidence.write_text(text.replace("## Sources", "## Earlier evidence\n\nA signed policy is available.\n\n## Sources", 1))
                self.commit(legacy, "Initial private records")
                private_head = self.git(legacy, "rev-parse", "HEAD")
                local_data = "Untracked field evidence – São Paulo.\r\n".encode("utf-8")
                (legacy / "context/sources").mkdir(exist_ok=True)
                (legacy / "context/sources/field.txt").write_bytes(local_data)

                if interrupted:
                    loose, original, quote = self.interrupt_historical_filing(outer, legacy)

                publisher = self.root.parent / f"publisher-{fixture}"
                self.git(self.root.parent, "clone", "--quiet", str(origin), str(publisher))
                self.git(publisher, "rm", "-qr", ".")
                for path in pm.inventory(pm.ROOT):
                    if path.is_file():
                        target = publisher / path.relative_to(pm.ROOT)
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(path, target)
                if target_version != current:
                    wire = publisher / "playbook/release.json"
                    wire.write_text(json.dumps(dict(json.loads(wire.read_text()), system_version=target_version)) + "\n")
                self.commit(publisher, "Current release fixture")
                self.git(publisher, "push", "origin", "main")
                command("git", "system", "pull")
                # The old 0.1 wrapper calls the newly installed check. Session start then runs align.
                command("align")
                private = outer / "studio"
                self.assertFalse(legacy.exists())
                self.assertEqual(self.git(private, "rev-parse", "HEAD"), private_head)
                installed = json.loads((private / "settings.json").read_text())
                self.assertEqual((installed["workspace_format"], installed["system_version"]), (2, target_version))
                brief = (private / "context/company/overview.md").read_text()
                self.assertEqual(records.work_state(brief)[0]["ID"], before_id)
                self.assertIn("A signed policy is available.", brief)
                if interrupted:
                    self.assertIn(quote, brief)
                    self.assertFalse((private / ".hub-filing-pending.json").exists())
                    with zipfile.ZipFile(private / ".hub-history/recover-access.zip") as saved:
                        self.assertEqual(saved.read("original/" + loose), original)
                self.assertEqual((private / "context/sources/field.txt").read_bytes(), local_data)
                # The layout snapshot contains the installed migrator and the old private work.
                receipt = json.loads((private / f".git/pm-hub-backup-{target_version}-layout-2.json").read_text())
                archive = outer / ".git/pm-hub-backups" / receipt["id"] / "hub.tar.gz"
                with tarfile.open(archive) as backup:
                    before = json.load(backup.extractfile("workspace/settings.json"))
                    self.assertEqual((before["workspace_format"], before["system_version"]), (1, target_version))
                    self.assertIn(workspace.FORMAT_FILE, backup.getnames())
                    self.assertEqual(backup.extractfile("workspace/context/sources/field.txt").read(), local_data)
                before = {p.relative_to(private): p.read_bytes() for p in pm.inventory(private) if p.is_file()}
                command("align")
                self.assertEqual(before, {p.relative_to(private): p.read_bytes() for p in pm.inventory(private) if p.is_file()})
                command("check")

    def test_ordinary_shared_git_pull_preserves_modified_and_untracked_private_files(self):
        self.connect()
        local = self.work / "product-peculiar.md"
        local.write_bytes(b"Private untracked work\r\n")
        tracked = self.work / "workspace/backlogs/compare-offers.md"
        tracked.write_bytes(b"Uncommitted private changes\r\n")
        other = self.contributor("system")
        guide = other / "README.md"
        guide.write_text(guide.read_text() + "\nShared fixture update.\n")
        self.commit(other, "Shared-only update")
        self.git(other, "push", "origin", "main")
        self.git(self.root, "pull", "--ff-only", "origin", "main")
        self.assertEqual(local.read_bytes(), b"Private untracked work\r\n")
        self.assertEqual(tracked.read_bytes(), b"Uncommitted private changes\r\n")


if __name__ == "__main__":
    unittest.main()
