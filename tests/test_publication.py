"""Exercise release selection and retries using disposable Git history and a release API fixture."""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError

import test_pm
import publish_release as publisher
import release_candidate as candidate


class CandidateTests(unittest.TestCase):
    def test_native_paths_and_routine_changes(self):
        self.assertFalse(candidate.needs_native(["README.md", "playbook/release.json", "playbook/updates.md", "templates/brief.md"]))
        for path in ("tools/snapshots.py", "tools/workspace.py", "tools/git_ops.py", "tools/storage.py",
                     "tools/release_candidate.py", ".github/workflows/check.yml", "tests/test_layout_upgrade.py",
                     "src/oryx/workspace/location.py", "src/oryx/review/store.py", "bin/oryx",
                     "tools/studio_layout.py", "tools/company_source.py", "tests/test_studio_contract.py"):
            with self.subTest(path=path):
                self.assertTrue(candidate.needs_native(["playbook/release.json", path]))

    def test_push_and_retry_in_first_parent_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            previous = Path.cwd()
            self.addCleanup(os.chdir, previous)
            os.chdir(root)
            def git(*args):
                return subprocess.check_output(["git", "-c", "user.name=Fixture", "-c", "user.email=test@example.invalid",
                                                "-c", "commit.gpgsign=false", *args], text=True).strip()
            git("init", "-q", "-b", "main")
            (root / "playbook").mkdir()
            def commit(version):
                (root / candidate.METADATA).write_text(json.dumps({"workspace_format": 1, "system_version": version}))
                git("add", candidate.METADATA)
                git("commit", "-qm", version)
                return git("rev-parse", "HEAD")
            before = commit("0.3.5")
            first = commit("0.3.6")
            second = commit("0.3.7")
            pr = {"number": 11, "commits": 1, "base": {"ref": "main"}, "merge_commit_sha": first}
            responses = {"branches/main": {"protected": True}, "pulls/11": pr,
                         f"commits/{first}/pulls?per_page=100": [pr]}
            api = responses.__getitem__
            event = {"repository": {"default_branch": "main"}, "before": before, "after": first}
            with patch.object(publisher, "publication") as verify:
                self.assertEqual(publisher.select_candidate(event, "refs/heads/main", first, api), (pr, first, "0.3.6", verify.return_value))
                retry = {"repository": event["repository"], "inputs": {"release_pr": "11"}}
                self.assertEqual(publisher.select_candidate(retry, "refs/heads/main", second, api), (pr, first, "0.3.6", verify.return_value))
                self.assertEqual(verify.call_count, 2)
                for changed in (dict(event, forced=True), dict(event, before=second)):
                    with self.assertRaises(ValueError):
                        publisher.select_candidate(changed, "refs/heads/main", first, api)
                with self.assertRaisesRegex(ValueError, "first-parent"):
                    publisher.select_candidate(retry, "refs/heads/main", before, api)
                responses["branches/main"] = {"protected": False}
                with self.assertRaisesRegex(ValueError, "protections"):
                    publisher.select_candidate(retry, "refs/heads/main", second, api)
            # A rebased PR can bump its version before its final commit.
            git("commit", "--allow-empty", "-qm", "Finish reviewed docs")
            tip = git("rev-parse", "HEAD")
            source = [{"parents": [{"sha": git("rev-parse", sha + "^1")}],
                       "commit": {"tree": {"sha": git("rev-parse", sha + "^{tree}")}}} for sha in (second, tip)]
            responses["pulls/11/commits?per_page=100&page=1"] = source
            responses["git/commits/" + first] = {"tree": {"sha": git("rev-parse", first + "^{tree}")}}
            pr.update(commits=2, merge_commit_sha=tip)
            self.assertEqual(publisher.release_base(pr, tip, first, api), first)
            self.assertEqual(publisher.release_base(pr, tip, None, api), first)
            source[0]["commit"]["tree"]["sha"] = "unrelated"
            self.assertEqual(publisher.release_base(pr, tip, first, api), second)
            with self.assertRaisesRegex(ValueError, "Increase"):
                candidate.candidate_version(first, first)
            os.chdir(previous)


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.responses = {}
        self.releases = []
        self.pr = {"number": 11, "title": "Improve publication", "html_url": "https://example.invalid/pr/11",
                   "body": "## Change\nShip tags.\n## Consumer impact and recovery\nUse backup.\n## Verification limits\nLinux."}

    def api(self, path, method="GET", data=None):
        if path == "git/tags" and method == "POST":
            oid = data["object"] + "-tag"
            self.responses["git/tags/" + oid] = {"tag": data["tag"], "object": {"type": "commit", "sha": data["object"]}}
            return {"sha": oid}
        if path == "git/refs" and method == "POST":
            self.responses["git/ref/" + data["ref"][5:]] = {"object": {"type": "tag", "sha": data["sha"]}}
            return {}
        if method == "PATCH":
            latest = next(r for r in self.releases if path == f"releases/{r['id']}")
            self.responses["releases/latest"] = latest
            return latest
        if path == "releases?per_page=100&page=1":
            return self.releases
        if path not in self.responses:
            raise HTTPError(path, 404, "Missing", {}, None)
        return self.responses[path]

    def create(self, tag, notes):
        self.assertIn("Use backup.", notes)
        self.assertIn("Ship tags.", notes)
        release = {"id": len(self.releases) + 1, "tag_name": tag, "html_url": "https://example.invalid/" + tag,
                   "draft": False, "prerelease": False, "body": notes}
        self.releases.append(release)
        self.responses["releases/tags/" + tag] = release

    def test_release_label_and_existing_version_tag(self):
        api = Mock(side_effect=self.api)
        publisher.ensure_tag("v1.2.3", "first", api)
        annotation = next(call.args[2] for call in api.call_args_list if call.args[:2] == ("git/tags", "POST"))
        self.assertEqual(annotation["message"], "oryx v1.2.3")
        with patch.dict(os.environ, GITHUB_REPOSITORY="fixture/product"), patch.object(
                subprocess, "run", return_value=subprocess.CompletedProcess([], 0)) as gh:
            publisher.create_release("v1.2.3", "Product update")
        command = gh.call_args.args[0]
        self.assertEqual(command[3], "v1.2.3")
        self.assertEqual(command[command.index("--title") + 1], "oryx v1.2.3")

        self.responses["git/tags/first-tag"]["message"] = "PM Hub v1.2.3"
        api.reset_mock()
        publisher.ensure_tag("v1.2.3", "first", api)
        self.assertTrue(all(len(call.args) == 1 for call in api.call_args_list))

    def test_published_tag_reports_the_qualified_digest_on_creation_and_retry(self):
        proof = {"archive_sha256": "c" * 64}
        publisher.publish(self.pr, "first", "0.3.6", self.api, self.create, qualification=proof)
        publisher.publish(self.pr, "first", "0.3.6", self.api, self.create, qualification=proof)
        self.assertEqual(len(self.releases), 1)
        with self.assertRaisesRegex(ValueError, "qualified archive"):
            publisher.publish(self.pr, "first", "0.3.6", self.api, self.create,
                              qualification={"archive_sha256": "e" * 64})

    def test_partial_failure_and_delayed_retry_preserve_all_releases_and_latest(self):
        with self.assertRaises(OSError):
            publisher.publish(self.pr, "first", "0.3.6", self.api, Mock(side_effect=OSError("interrupted")))
        self.assertIn("git/ref/tags/v0.3.6", self.responses)
        for sha, version in (("second", "0.3.7"), ("first", "0.3.6"), ("second", "0.3.7")):
            self.assertTrue(publisher.publish(self.pr, sha, version, self.api, self.create).endswith("v" + version))
        self.assertEqual(len(self.releases), 2)
        self.assertEqual(self.responses["releases/latest"]["tag_name"], "v0.3.7")

    def test_temporary_response_after_creation_recovers_without_a_second_release(self):
        def interrupted(tag, notes):
            self.create(tag, notes)
            raise HTTPError("release", 503, "unavailable", {}, None)
        create = Mock(side_effect=interrupted)
        wait = Mock()
        url = publisher.retry_publication(lambda: publisher.publish(self.pr, "first", "0.3.6", self.api, create), wait)
        self.assertTrue(url.endswith("v0.3.6"))
        self.assertEqual(len(self.releases), 1)
        create.assert_called_once()
        wait.assert_called_once_with(5)

    def test_permanent_errors_stop_and_temporary_errors_have_bounded_retries(self):
        for error in (ValueError("tag conflict"), HTTPError("rules", 403, "forbidden", {}, None)):
            operation = Mock(side_effect=error)
            wait = Mock()
            with self.assertRaises(type(error)):
                publisher.retry_publication(operation, wait)
            operation.assert_called_once()
            wait.assert_not_called()
        wait = Mock()
        operation = Mock(side_effect=TimeoutError("temporary"))
        with self.assertRaisesRegex(ValueError, "retries exhausted"):
            publisher.retry_publication(operation, wait)
        self.assertEqual(operation.call_count, 3)
        self.assertEqual([call.args[0] for call in wait.call_args_list], [5, 15])

    def test_conflicting_tag_and_draft_fail_closed(self):
        publisher.ensure_tag("v0.3.6", "other", self.api)
        with self.assertRaisesRegex(ValueError, "Existing tag"):
            publisher.publish(self.pr, "target", "0.3.6", self.api, self.create)
        self.assertEqual(self.releases, [])
        self.create("v0.3.6", publisher.release_notes(self.pr))
        self.releases[0]["draft"] = True
        with self.assertRaisesRegex(ValueError, "published stable"):
            publisher.publish(self.pr, "other", "0.3.6", self.api, self.create)
