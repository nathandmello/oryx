"""Exercise the standing review gates and whole-installation recovery contract."""

import json
import os
from pathlib import Path
import subprocess
import unittest
from unittest.mock import mock_open, patch

import test_pm
import pm
import release_review
import snapshots
import upgrades


class BackupTests(unittest.TestCase):
    setUp = test_pm.HubTests.setUp

    def old(self):
        legacy = self.root / "workspace"
        self.work.rename(legacy)
        self.work = legacy
        settings = self.work / "settings.json"
        old = json.dumps(dict(json.loads(settings.read_text()), system_version="0.1.0", workspace_format=1), indent=2) + "\n"
        settings.write_text(old)
        (self.work / upgrades.LEDGER).unlink()
        return settings, old

    def test_complete_restore_preserves_private_and_shared_git_and_ignored_material(self):
        settings, old = self.old()
        for repo in (self.root, self.work):
            subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
            subprocess.run(["git", "-C", str(repo), "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                            "-c", "commit.gpgsign=false", "commit", "-qm", "Fixture baseline"], check=True)
        binary = self.work / ".env.local"
        binary.write_bytes(bytes(range(256)))
        (self.root / ".state").mkdir()
        (self.root / ".state/empty").mkdir()
        (self.root / ".state/file").write_bytes(b"local system bytes")
        if os.name == "posix":
            (self.work / "link").symlink_to("absent-outside")
        note = self.work / "context/field.md"
        note.write_text("Staged version.")
        subprocess.run(["git", "-C", str(self.work), "add", "context/field.md"], check=True)
        note.write_text("Unstaged version.")
        expected = {}
        for repo in (self.root, self.work):
            expected[repo] = subprocess.check_output(["git", "-C", str(repo), "status", "--porcelain"])
        self.assertTrue(pm.alignment(self.root)["needs_setup"])
        store = self.root / ".git/pm-hub-backups"
        self.assertFalse(store.exists())
        report = pm.alignment(self.root, True)
        archive = Path(report["installation_backup"])
        restored = self.root.parent / "restored"
        restored.mkdir(mode=0o700)
        subprocess.run(["tar", "-xpzf", str(archive), "-C", str(restored)], check=True)
        self.assertEqual((restored / "workspace/settings.json").read_text(), old)
        self.assertEqual((restored / "workspace/.env.local").read_bytes(), bytes(range(256)))
        self.assertTrue((restored / ".state/empty").is_dir())
        self.assertEqual((restored / ".state/file").read_bytes(), b"local system bytes")
        self.assertFalse((restored / ".git/pm-hub-backups").exists())
        if os.name == "posix":
            self.assertEqual(os.readlink(restored / "workspace/link"), "absent-outside")
        for repo, status in expected.items():
            copy = restored / repo.relative_to(self.root)
            subprocess.run(["git", "-C", str(copy), "fsck", "--full"], capture_output=True, check=True)
            self.assertEqual(subprocess.check_output(["git", "-C", str(copy), "status", "--porcelain"]), status)
        self.assertEqual(json.loads((self.root / "studio/settings.json").read_text())["system_version"], pm.workspace.release(self.root)["system_version"])
        pm.alignment(self.root, True)
        self.assertEqual(list(store.glob("*/hub.tar.gz")), [archive])

    def test_failure_or_changed_permissions_prevent_migration(self):
        settings, original = self.old()
        with patch.object(snapshots, "create", side_effect=OSError("out of disk")), self.assertRaises(OSError):
            pm.alignment(self.root, True)
        self.assertEqual(settings.read_text(), original)
        self.assertFalse((self.work / upgrades.LEDGER).exists())
        archive = snapshots.ensure(self.root, pm.workspace.release(self.root)["system_version"], layout_change=True)
        if os.name == "posix":
            archive.chmod(0o644)
            with self.assertRaisesRegex(ValueError, "Restrict"):
                pm.alignment(self.root, True)
            archive.chmod(0o600)
        archive.write_bytes(b"changed backup")
        with self.assertRaisesRegex(ValueError, "checksum"):
            pm.alignment(self.root, True)
        self.assertEqual(settings.read_text(), original)

    def test_orphan_archive_is_reused_when_receipt_finalisation_fails(self):
        self.old()
        real = snapshots.storage.replace_text
        def full(path, before, text):
            if before is not None and path.name.startswith("pm-hub-backup-"):
                raise OSError("disk full")
            real(path, before, text)
        with patch.object(snapshots.storage, "replace_text", side_effect=full), self.assertRaises(OSError):
            pm.alignment(self.root, True)
        store = self.root / ".git/pm-hub-backups"
        saved, = store.glob("*/hub.tar.gz")
        with patch.object(snapshots, "create", side_effect=AssertionError):
            self.assertEqual(pm.alignment(self.root, True)["installation_backup"], str(saved))

    def test_external_object_pool_stops_before_private_changes(self):
        settings, original = self.old()
        path = self.work / ".git/objects/info/alternates"
        path.write_text(str(self.root / ".git/objects") + "\n")
        with self.assertRaisesRegex(ValueError, "external object stores"):
            pm.alignment(self.root, True)
        self.assertEqual(settings.read_text(), original)

    @unittest.skipUnless(hasattr(os, "setxattr"), "extended attribute API required")
    def test_supported_extended_attributes_survive_native_restore(self):
        from shutil import which
        if not which("tar") or b"GNU tar" not in subprocess.check_output(["tar", "--version"]):
            self.skipTest("GNU tar restore options required")
        self.old()
        item = self.work / "attachment.bin"
        item.write_bytes(b"attachment")
        value = b"fixture\x00\xff"
        try:
            os.setxattr(item, "user.fixture", value)
        except OSError as exc:
            self.skipTest(str(exc))
        archive = pm.alignment(self.root, True)["installation_backup"]
        restored = self.root.parent / "restored"
        restored.mkdir(mode=0o700)
        subprocess.run(["tar", "--xattrs", "--xattrs-include=*", "-xpzf", archive, "-C", str(restored)], check=True)
        self.assertEqual(os.getxattr(restored / "workspace/attachment.bin", "user.fixture"), value)


class ReleaseReviewTests(unittest.TestCase):
    def setUp(self):
        self.head, self.merge = "a" * 40, "b" * 40
        self.pr = {"changed_files": 0, "head": {"sha": self.head}, "base": {"ref": "main"}, "merged": True, "number": 9,
                   "merge_commit_sha": self.merge, "body": """## Consumer impact and recovery
Verified fresh setup and rollback.
## Verification limits
Desktop sessions were outside this fixture.
"""}
        self.harness = "e" * 40
        self.trust = patch.dict(os.environ, ORYX_QUALIFICATION_APP_ID="321", ORYX_QUALIFICATION_COMMIT=self.harness)
        self.trust.start()
        self.addCleanup(self.trust.stop)
        self.receipt = {"schema": "oryx-qualified-archive/1", "commit": self.head, "tree": "tree",
                        "harness_commit": self.harness, "archive_sha256": "c" * 64, "report_sha256": "d" * 64,
                        "components": {k: {"passed": 2, "required": 2} for k in release_review.COMPONENT_TYPES}}
        self.archive_check = {"name": release_review.QUALIFICATION_CHECK, "head_sha": self.head,
                              "app": {"id": 321}, "status": "completed", "conclusion": "success"}
        self.state = {key: {"commit_sha": self.head, "status": "completed", "has_unresolved_findings": False}
                      for key in ("code_review", "security_review")}
        self.bot = {"id": 199175422, "login": "chatgpt-codex-connector[bot]"}
        self.responses = {"git/commits/" + self.head: {"tree": {"sha": "tree"}},
                          "git/commits/" + self.merge: {"tree": {"sha": "tree"}}}
        self.runs = [{"id": 5, "run_number": 5, "run_attempt": 2, "pull_requests": [{"number": 9}], "conclusion": "success"}]

    def api(self, path):
        if path.startswith("issues/9/comments?"):
            body = "<!-- codex-pull-request-review-summary -->\n<!-- codex-review-state:v1 " + json.dumps(self.state) + " -->"
            return [{"user": self.bot, "id": 1, "updated_at": "2026-11-19T12:00:00Z", "body": body}]
        if "check_name=Oryx+archive+qualification" in path:
            check = dict(self.archive_check, output={"summary": json.dumps(self.receipt)})
            return {"total_count": 1, "check_runs": [check]}
        if "/check-runs?" in path:
            return {"total_count": 0, "check_runs": []}
        if path.startswith("actions/workflows/review.yml/"):
            return {"workflow_runs": [dict(run, id=4) for run in self.runs]}
        if path.startswith("actions/runs/4/jobs?"):
            return {"jobs": [{"name": "review", "conclusion": "success"}]}
        if path.startswith("actions/workflows/"):
            return {"workflow_runs": self.runs}
        if path.startswith("actions/runs/5/jobs?"):
            return {"jobs": [{"name": "check", "conclusion": "success",
                              "steps": [{"name": "Tested tree tree", "conclusion": "success"}]}]}
        return self.responses[path]

    def gate(self):
        return release_review.publication(self.pr, "main", self.merge, self.api)

    def test_browser_impact_requires_an_explanation_and_a_spec_for_changed_behavior(self):
        files = "pulls/9/files?per_page=100&page=1"
        unrelated = {"filename": "tools/preferences.py", "additions": 1}
        tasks = {"filename": "tools/initiative_work.py", "additions": 1}
        spec = {"filename": "tests/browser/pm-hub.spec.js", "additions": 4}
        changed = "## Browser impact\nChanged: The task editor shows the review state.\n"
        unchanged = "## Browser impact\nUnchanged: The task result is identical in both interfaces.\n"
        cases = (
            ([unrelated], "", None),
            ([tasks], "", "Browser impact section"),
            ([{"filename": "src/oryx/adapters/browser.py", "additions": 1}], "", "Browser impact section"),
            ([tasks], "## Browser impact\nUnchanged:", "explain the result"),
            ([tasks], unchanged, None),
            ([tasks], changed, "Playwright scenario"),
            ([tasks, dict(spec, additions=0)], changed, "Playwright scenario"),
            ([tasks, spec], changed, None),
        )
        for changes, section, error in cases:
            with self.subTest(changes=changes, section=section):
                self.responses[files] = changes
                pr = dict(self.pr, changed_files=len(changes), body=self.pr["body"] + section)
                if error:
                    with self.assertRaisesRegex(ValueError, error):
                        release_review.browser_impact(pr, self.api)
                else:
                    release_review.browser_impact(pr, self.api)

    def test_qualification_requires_the_external_app_exact_build_and_an_affirmative_complete_matrix(self):
        self.gate()
        for key, value in (("app", {"id": 322}), ("head_sha", "f" * 40), ("conclusion", "skipped"),
                           ("status", "in_progress"), ("conclusion", "neutral"), ("conclusion", "cancelled")):
            with self.subTest(key=key, value=value), patch.dict(self.archive_check, {key: value}), self.assertRaises(ValueError):
                self.gate()
        for key, value in (("tree", "other"), ("commit", self.merge), ("harness_commit", "old"),
                           ("archive_sha256", "unbound"), ("report_sha256", None), ("components", {})):
            with self.subTest(key=key), patch.dict(self.receipt, {key: value}), self.assertRaises(ValueError):
                self.gate()
        for counts in ({"required": 1, "passed": 0}, {"required": 0, "passed": 0}, {"required": True, "passed": True}):
            with patch.dict(self.receipt["components"], {"skills": counts}), self.assertRaises(ValueError):
                self.gate()
        with patch.dict(os.environ, ORYX_QUALIFICATION_APP_ID=""), self.assertRaises(ValueError):
            self.gate()

    def test_browser_impact_checks_all_pages_and_previous_paths(self):
        self.responses["pulls/9/files?per_page=100&page=1"] = [
            {"filename": f"notes/{number}.md", "additions": 1} for number in range(100)
        ]
        self.responses["pulls/9/files?per_page=100&page=2"] = [
            {"filename": "tools/moved.py", "previous_filename": "tools/local_ui/app.js", "additions": 0}
        ]
        pr = dict(self.pr, changed_files=101)
        with self.assertRaisesRegex(ValueError, "Browser impact section"):
            release_review.browser_impact(pr, self.api)
        self.responses["pulls/9/files?per_page=100&page=2"] = []
        with self.assertRaisesRegex(ValueError, "verify all changed paths"):
            release_review.browser_impact(pr, self.api)

    def test_pr_review_enforces_browser_impact_using_current_description(self):
        pr = dict(self.pr, changed_files=1, base={"ref": "main", "sha": "c" * 40})
        event = json.dumps({"pull_request": pr})
        self.responses["pulls/9"] = pr
        self.responses["pulls/9/files?per_page=100&page=1"] = [
            {"filename": "templates/launch-checklist.json", "additions": 1}
        ]
        with patch.dict(os.environ, GITHUB_EVENT_PATH="fixture-event.json"), \
                patch("builtins.open", mock_open(read_data=event)), patch.object(release_review, "github", self.api):
            with self.assertRaisesRegex(ValueError, "Browser impact section"):
                release_review.main()
            pr["body"] += "## Browser impact\nUnchanged: Only the internal template description changed.\n"
            release_review.main()
            pr["head"] = {"sha": "d" * 40}
            with self.assertRaisesRegex(ValueError, "commits changed"):
                release_review.main()

    def test_checks_current_reviews_and_rejects_stale_or_missing_evidence(self):
        for key in self.state:
            original = self.state[key].copy()
            for change in ({"has_unresolved_findings": True}, {"has_unresolved_findings": None},
                           {"commit_sha": "c" * 40}, {"status": "running"}):
                self.state[key] = dict(original, **change)
                with self.assertRaises(ValueError):
                    self.gate()
            self.state[key] = original
        self.gate()
        self.bot["id"] = 1
        with self.assertRaisesRegex(ValueError, "summary"):
            self.gate()

    def test_private_security_result_requires_a_successful_codex_check(self):
        self.state["security_review"]["has_unresolved_findings"] = None
        check = {"name": "Codex Security Review", "head_sha": self.head, "conclusion": "success",
                 "app": {"slug": "chatgpt-codex-connector"}}
        def api(path):
            if "/check-runs?" in path:
                return {"total_count": 1, "check_runs": [check]}
            return self.api(path)
        release_review.review(self.pr, api)
        check["app"]["slug"] = "another-app"
        with self.assertRaisesRegex(ValueError, "confirmed passing"):
            release_review.review(self.pr, api)

    def test_combined_pass_must_follow_current_summary_and_come_from_codex(self):
        self.state["security_review"]["has_unresolved_findings"] = None
        reaction = {"content": "+1", "user": self.bot, "created_at": "2026-11-19T12:00:01Z"}
        def api(path):
            if "/reactions?" in path:
                return [reaction]
            data = self.api(path)
            if "/comments?" in path:
                data[0]["body"] += "\nCodex reacts with 👍 once all reviews finish with no findings."
            return data
        release_review.review(self.pr, api)
        for changes in ({"user": {"id": 42}}, {"created_at": "2026-11-19T11:59:59Z"}, {"content": "eyes"}):
            with patch.dict(reaction, changes), self.assertRaises(ValueError):
                release_review.review(self.pr, api)
        self.state["security_review"]["commit_sha"] = "d" * 40
        with self.assertRaises(ValueError):
            release_review.review(self.pr, api)

    def test_publication_requires_reviewed_tree_latest_green_pr_and_merge(self):
        self.gate()
        self.runs.append(dict(self.runs[0], run_number=6, conclusion="failure"))
        with self.assertRaisesRegex(ValueError, "successful"):
            self.gate()
        self.runs.pop()
        self.responses["git/commits/" + self.merge] = {"tree": {"sha": "other"}}
        with self.assertRaisesRegex(ValueError, "differs"):
            self.gate()
        self.pr["merged"] = False
        with self.assertRaisesRegex(ValueError, "merged|tip"):
            self.gate()

    def test_success_for_another_tree_or_a_skipped_receipt_cannot_publish(self):
        for name, conclusion in (("Tested tree old", "success"), ("Tested tree tree", "skipped")):
            def api(path):
                if path.startswith("actions/runs/5/"):
                    return {"jobs": [{"name": "check", "conclusion": "success",
                                      "steps": [{"name": name, "conclusion": conclusion}]}]}
                return self.api(path)
            with self.assertRaisesRegex(ValueError, "CI evidence"):
                release_review.publication(self.pr, "main", self.merge, api)

    def detached(self):
        self.pr["head"].update(ref="codex/release-fix", repo={"id": 123, "owner": {"login": "fixture"}})
        self.pr["created_at"] = "2026-04-07T10:00:00Z"
        query = "pulls?state=all&head=fixture%3Acodex%2Frelease-fix&per_page=100"
        self.responses[query] = [self.pr]
        self.runs[0].update(pull_requests=[], event="pull_request", head_sha=self.head,
                            head_branch="codex/release-fix", head_repository={"id": 123},
                            created_at="2026-04-07T10:00:00Z")
        return query

    def test_post_merge_run_without_association_requires_unique_exact_pr_head(self):
        query = self.detached()
        self.gate()

        for previous_head in (self.head, "c" * 40):
            self.responses[query] = [self.pr, {"number": 4, "head": {"sha": previous_head}}]
            with self.subTest(previous_head=previous_head), self.assertRaisesRegex(ValueError, "uniquely associate"):
                self.gate()

        self.responses[query] = [self.pr] * 100
        with self.assertRaisesRegex(ValueError, "uniquely associate"):
            self.gate()

    def test_post_merge_run_rejects_wrong_source_or_explicit_association(self):
        self.detached()
        original = self.runs[0]
        for changed in ({"head_sha": "c" * 40}, {"head_branch": "other"}, {"head_repository": {"id": 456}},
                        {"event": "push"}, {"pull_requests": [{"number": 10}]},
                        {"created_at": "2026-04-07T09:59:59Z"}, {"created_at": None}):
            with self.subTest(changed=changed):
                self.runs[0] = dict(original, **changed)
                with self.assertRaisesRegex(ValueError, "successful"):
                    self.gate()

    def test_later_detached_failure_or_pending_attempt_blocks_publication(self):
        self.detached()
        self.gate()
        self.runs.append(dict(self.runs[0], run_attempt=3, conclusion="failure"))
        self.runs[0]["pull_requests"] = [{"number": 9}]
        with self.assertRaisesRegex(ValueError, "successful"):
            self.gate()
        self.runs[-1]["conclusion"] = None
        with self.assertRaisesRegex(ValueError, "successful"):
            self.gate()
