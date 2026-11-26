"""Verify workspace setup before the company walkthrough."""

import shutil
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
