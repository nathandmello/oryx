"""Exercise the standing review gates and whole-installation recovery contract."""

import json
import os
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

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
        self.assertEqual(json.loads((self.root / "private/settings.json").read_text())["system_version"], pm.workspace.release(self.root)["system_version"])
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
        self.pr = {"head": {"sha": self.head}, "base": {"ref": "main"}, "merged": True, "number": 9,
                   "merge_commit_sha": self.merge, "body": f"""Reviewed commit: `{self.head}`

## Engineering review
Reviewer: Engineering reviewer
Decision: pass
Evidence: Verified backup integrity on interruption.
## Quality review
Reviewer: QA reviewer
Decision: pass
Evidence: Restored an installation with untracked work.
## Consumer impact and recovery
Verified fresh setup and rollback.
## Verification limits
Desktop sessions were outside this fixture.
"""}
        self.responses = {"git/commits/" + self.head: {"tree": {"sha": "tree"}},
                          "git/commits/" + self.merge: {"tree": {"sha": "tree"}}}
        self.runs = [{"id": 5, "run_number": 5, "run_attempt": 2, "pull_requests": [{"number": 9}], "conclusion": "success"}]

    def api(self, path):
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

    def test_checks_current_reviews_and_rejects_stale_or_missing_evidence(self):
        body = self.pr["body"]
        for before, after in ((self.head, "c" * 40), ("QA reviewer", "Engineering reviewer"),
                              ("Decision: pass", "Decision: outstanding"), ("Evidence: Verified", "<!-- Evidence: Verified")):
            self.pr["body"] = body.replace(before, after, 1)
            with self.assertRaises(ValueError):
                self.gate()
        self.pr["body"] = body
        self.gate()

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
