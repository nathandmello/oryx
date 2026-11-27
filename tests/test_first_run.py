"""Verify workspace setup before the company walkthrough."""

import json
import os
import shutil

import git_ops
import unittest
from unittest.mock import patch

import first_run
import onboarding
import test_pm
import workspace


class FirstRunTests(unittest.TestCase):
    setUp = test_pm.HubTests.setUp

    def test_local_setup_starts_company_then_reuses_workspace(self):
        shutil.rmtree(self.work)
        with patch("sys.stdin.isatty", return_value=True), patch(
            "builtins.input", side_effect=["l", "New PM", ""]
        ), patch.object(first_run, "github") as github:
            first_run.prepare(self.root)
            github.assert_not_called()
        self.assertEqual(workspace.settings(self.root)["owner"], "New PM")
        self.assertEqual(onboarding.status(self.work)["stage"], "company")
        with patch("builtins.input") as ask:
            first_run.prepare(self.root)
            ask.assert_not_called()

    def test_shared_repository_cannot_be_selected_for_private_sync(self):
        url = "https://github.com/example/oryx.git"
        workspace.git(self.root, "remote", "add", "origin", url)
        with patch("builtins.input", return_value="example/oryx"), patch.object(
            first_run, "github"
        ) as github:
            with self.assertRaisesRegex(ValueError, "separate from the shared"):
                first_run.github_target(self.root, self.work, create=True)
            github.assert_not_called()
        self.assertIsNone(workspace.settings(self.root)["remotes"]["workspace"])

    def test_populated_destination_preserves_unconnected_local_workspace(self):
        with patch("sys.stdin.isatty", return_value=True), patch(
            "builtins.input", return_value="c"
        ), patch.object(
            first_run, "github_target", return_value=("https://github.com/example/pm.git", False)
        ):
            with self.assertRaisesRegex(ValueError, "contains history"):
                first_run.prepare(self.root, explicit=True)
        self.assertEqual(workspace.settings(self.root)["owner"], "Fixture PM")
        self.assertEqual(first_run.origin_urls(self.work), [])

    def test_external_restore_with_permissive_umask_preserves_private_access_and_review(self):
        from oryx.review.store import Workspace

        source = self.root.parent / "original"
        restored = self.root.parent / "restored"
        workspace.git(self.root, "add", "--", "AGENTS.md", "playbook", "templates")
        with patch.dict(os.environ, ORYX_WORKSPACE=str(source)):
            workspace.initialise(self.root, owner="Fixture PM", delivery_system="Fixture delivery")
            workspace.git(source, "add", "-A")
            workspace.git(source, "-c", "user.name=Fixture PM", "-c", "user.email=fixture@example.invalid",
                          "commit", "-m", "Initialize Oryx Workspace")
        with patch.dict(os.environ, ORYX_WORKSPACE=str(restored)):
            previous = os.umask(0o022)
            try:
                first_run.restore(self.root, source.as_uri())
            finally:
                os.umask(previous)
            self.assertEqual(workspace.git(restored, "rev-parse", "HEAD"), workspace.git(source, "rev-parse", "HEAD"))
            self.assertEqual((restored / ".oryx/workspace.json").read_bytes(), (source / ".oryx/workspace.json").read_bytes())
            for path in (restored, restored / ".git", restored / ".oryx", restored / "settings.json"):
                self.assertEqual(path.stat().st_mode & 0o077, 0, str(path))
            Workspace().init()

    def test_private_first_disclosure_rechecks_repository_and_pins_the_reviewed_history(self):
        from oryx.workspace.location import create_identity
        create_identity(self.work)
        url = "https://github.com/example/fictional.git"
        approved = {"id": "repo-123", "nameWithOwner": "example/fictional", "visibility": "PRIVATE",
                    "viewerPermission": "ADMIN"}
        self.commit = "a" * 40
        with patch.object(git_ops, "origin_for_push", return_value=url), patch.object(
            git_ops.workspace, "git", side_effect=lambda p, *a: "0" * 40 + "\trefs/heads/main" if a[0] == "ls-remote" else self.commit if a[0] in ("log", "rev-parse") else "100644 blob abc\tdeleted-note.md"
        ) as local_git, patch.object(first_run, "github") as api, patch(
            "oryx.review.cli.confirm_effect", return_value=True
        ) as confirm:
            api.side_effect = [json.dumps(approved), "fictional-user", json.dumps(approved), "fictional-user"]
            git_ops.reviewed_first_push(self.work, "main", url, self.commit)
            shown = confirm.call_args.args[1]
            self.assertEqual((shown["repository_id"], shown["actor"], shown["commit"]),
                             ("repo-123", "fictional-user", self.commit))
            self.assertIn("deleted-note.md", repr(shown["reachable_trees"]))
            local_git.assert_any_call(self.work, "ls-tree", "-r", self.commit)
            self.commit = "b" * 40
            api.side_effect = [json.dumps(approved), "fictional-user", json.dumps(dict(approved, visibility="PUBLIC"))]
            with self.assertRaisesRegex(ValueError, "private and writable"):
                git_ops.reviewed_first_push(self.work, "main", url, self.commit)
            confirm.return_value = False
            api.side_effect = [json.dumps(approved), "fictional-user"]
            with self.assertRaisesRegex(ValueError, "local Workspace"):
                git_ops.reviewed_first_push(self.work, "main", url, self.commit)

    def test_connection_persists_only_after_verifying_git_access(self):
        url = "https://github.com/example/private-work.git"
        git = workspace.git

        def fetch_or_git(path, *args):
            if args == ("fetch", "origin"):
                self.assertEqual(path, self.work)
                self.assertIsNone(workspace.settings(self.root)["remotes"]["workspace"])
                raise ValueError("Offline")
            return git(path, *args)

        with patch.object(workspace, "git", side_effect=fetch_or_git):
            with self.assertRaisesRegex(ValueError, "Offline"):
                first_run.connect(self.root, self.work, url)
        self.assertIsNone(workspace.settings(self.root)["remotes"]["workspace"])

        def online_git(path, *args):
            return "" if args == ("fetch", "origin") else git(path, *args)

        with patch.object(workspace, "git", side_effect=online_git):
            first_run.connect(self.root, self.work, url)
        self.assertEqual(workspace.settings(self.root)["remotes"]["workspace"], url)
        self.assertEqual(first_run.origin_urls(self.work), [url, url])
