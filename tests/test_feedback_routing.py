"""Check the installed feedback CLI against a local, recording GitHub CLI substitute."""

import json
import os
import subprocess
import sys
import unittest

import test_pm


REPOSITORY = "nathandmello/pm-hub"
RENAMED = "nathandmello/oryx"
METADATA = json.dumps({"id": 1463535158, "full_name": REPOSITORY, "owner": "nathandmello"})
RENAMED_METADATA = json.dumps({"id": 1463535158, "full_name": RENAMED, "owner": "nathandmello"})
API = "repos/" + REPOSITORY
ISSUES = "https://github.com/" + REPOSITORY + "/issues/"
HOST = ["api", "--hostname", "github.com"]
IDENTITY = [*HOST, "repositories/1463535158", "--jq", "{id, full_name, owner: .owner.login} | @json"]
PAGE = [*HOST, "--paginate", "--jq", ".[] | @json"]
ALL_ISSUES = [*PAGE, API + "/issues?state=all&per_page=100"]
SHIM = '''
import json, os, sys
from pathlib import Path
path = Path(os.environ["FIXTURE_GH"])
args = sys.argv[1:]
with (path / "calls").open("a") as log:
    log.write(json.dumps(args) + "\\n")
queue = path / "replies"
replies = json.loads(queue.read_text())
if not replies:
    sys.exit("No response configured for this test")
reply = replies.pop(0)
queue.write_text(json.dumps(replies))
if reply is None:
    sys.exit("Authentication unavailable in fixture")
if isinstance(reply, list):
    pages = reply if "--paginate" in args else reply[:1]
    for page in pages:
        for row in page:
            print(json.dumps(row, ensure_ascii=False))
else:
    print(reply)
'''


@unittest.skipUnless(os.name == "posix", "The recording executable uses a POSIX interpreter directive")
class FeedbackRoutingTests(unittest.TestCase):
    def setUp(self):
        test_pm.HubTests.setUp(self)
        control = self.root.parent / "recording-gh"
        control.mkdir()
        program = control / "gh"
        program.write_text(f"#!{sys.executable}\n" + SHIM)
        program.chmod(0o700)
        self.calls = control / "calls"
        self.calls.touch()
        self.replies = control / "replies"
        self.replies.write_text("[]")
        self.env = dict(os.environ, PATH=str(control) + os.pathsep + os.environ["PATH"],
                        FIXTURE_GH=str(control), GH_REPO="elsewhere/another-project", GH_HOST="enterprise.invalid")
        for repo, remote in ((self.root, "https://github.com/fixture-fork/pm-hub.git"),
                             (self.work, "https://enterprise.invalid/field-team/private-studio.git")):
            subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", remote], check=True)
        self.send = ["report", "private-agenda", "--title", "Review format", "--body", "Offer a decision summary."]
        self.run_cli("set", "private-agenda", "--scope", "Confidential pilot", "--behavior", "Open with Project Ivory.")

    def run_cli(self, *args, replies=(), error=None):
        self.replies.write_text(json.dumps(replies))
        self.calls.write_text("")
        result = subprocess.run([sys.executable, str(self.root / "tools/pm.py"), "override", *args],
                                cwd=self.work / "context", env=self.env, capture_output=True, text=True)
        self.assertEqual(json.loads(self.replies.read_text()), [], result.stdout + result.stderr)
        if error:
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(error, result.stdout)
            return
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def recorded(self):
        return [json.loads(line) for line in self.calls.read_text().splitlines()]

    def test_create_select_another_issue_and_recover_a_lost_comment_receipt(self):
        self.run_cli(*self.send, "--approved", error="Enable")
        self.assertEqual(self.recorded(), [])
        self.run_cli("reporting", "on")
        self.run_cli(*self.send, error="Approve")
        self.assertEqual(self.recorded(), [])
        self.run_cli(*self.send, "--issue", "0", "--approved", error="positive")
        self.assertEqual(self.recorded(), [])
        created = self.run_cli(*self.send, "--approved", replies=[METADATA, [[]], ISSUES + "21"])
        self.assertEqual(created, {"url": ISSUES + "21"})
        identity, issues, post = self.recorded()
        self.assertEqual((identity, issues), (IDENTITY, ALL_ISSUES))
        body = next(arg for arg in post if arg.startswith("body="))
        self.assertEqual(post, [*HOST, API + "/issues", "--method", "POST", "-f", "title=Review format",
                                "-f", body, "--jq", ".html_url"])
        self.assertTrue(body.startswith("body=Offer a decision summary.\n\n<!-- pm-hub-feedback:"))
        self.assertNotIn("Ivory", repr(self.recorded()))
        self.assertNotIn("private-agenda", repr(self.recorded()))
        original = {"number": 21, "state": "open", "title": "Review format", "body": body[5:], "html_url": ISSUES + "21"}
        target = {"number": 42, "state": "open", "title": "Quarterly feedback", "body": "Summary\u2028from the PM.",
                  "html_url": ISSUES + "42"}
        comment = ISSUES + "42#issuecomment-513"
        send = [*self.send, "--issue", "42", "--approved"]
        response = self.run_cli(*send, replies=[METADATA, [[original], [target]], [[{"body": None}], []], comment])
        self.assertEqual(response, {"url": comment})
        comments = [*PAGE, API + "/issues/42/comments?per_page=100"]
        self.assertEqual(self.recorded(), [IDENTITY, ALL_ISSUES, comments,
                         [*HOST, API + "/issues/42/comments", "--method", "POST", "-f", body, "--jq", ".html_url"]])
        self.assertEqual(self.run_cli(*send), {"url": comment})
        self.assertEqual(self.recorded(), [])
        self.assertEqual(self.run_cli(*self.send, "--approved", "--issue", "21"), created)
        self.assertEqual(self.recorded(), [])

        ledger = self.work / "customizations/rules.json"
        saved = json.loads(ledger.read_text())
        saved["reports"] = {}
        ledger.write_text(json.dumps(saved))
        target.update(state="closed", title="Completed", html_url=f"https://github.com/{RENAMED}/issues/42")
        renamed_comment = target["html_url"] + "#issuecomment-513"
        late_comment = {"body": body[5:], "html_url": renamed_comment}
        self.assertEqual(self.run_cli(*send, replies=[RENAMED_METADATA, [[original], [target]], [[], [late_comment]]]),
                         {"url": renamed_comment})
        self.assertEqual(self.recorded(), [IDENTITY, [*PAGE, f"repos/{RENAMED}/issues?state=all&per_page=100"],
                                          [*PAGE, f"repos/{RENAMED}/issues/42/comments?per_page=100"]])

    def test_auth_redirect_and_pull_request_leave_the_report_pending(self):
        self.run_cli("reporting", "on")
        reply = self.run_cli(*self.send, "--issue", "15", "--approved", replies=[None])
        self.assertIn("authentication", reply["report_pending"])
        self.assertEqual(self.recorded(), [IDENTITY])
        legitimate = json.loads(RENAMED_METADATA)
        for redirected in (dict(legitimate, full_name="transferred/oryx", owner="transferred"),
                           dict(legitimate, full_name="nathandmello/unrelated"),
                           dict(legitimate, owner="transferred"), dict(legitimate, id=12),
                           dict(legitimate, id=12, full_name=REPOSITORY)):
            with self.subTest(redirected=redirected):
                reply = self.run_cli("sync", replies=[json.dumps(redirected)])
                self.assertIn("feedback destination", reply["report_pending"])
                self.assertEqual(self.recorded(), [IDENTITY])
        pull = {"number": 15, "state": "open", "title": "Review format", "pull_request": {}}
        reply = self.run_cli("sync", replies=[METADATA, [[pull]]])
        self.assertIn("matching issue", reply["report_pending"])
        self.assertEqual(self.recorded(), [IDENTITY, ALL_ISSUES])
        self.run_cli("reporting", "off")
        self.run_cli("sync", error="Enable")
        self.assertEqual(self.recorded(), [])
        self.assertEqual(self.run_cli("list")["pending"][0]["issue"], 15)

    def test_offline_reports_keep_each_approved_issue_through_partial_sync(self):
        self.run_cli("reporting", "on")
        send = [*self.send, "--approved"]
        self.run_cli(*send, replies=[None])
        self.assertEqual([row["issue"] for row in self.run_cli("list")["pending"]], [None])
        for number in (21, 42, 21):
            self.run_cli(*send, "--issue", str(number), replies=[None])
        self.assertEqual([row["issue"] for row in self.run_cli("list")["pending"]], [21, 42])

        issues = [{"number": number, "state": "open", "title": f"Report {number}",
                   "body": "", "html_url": ISSUES + str(number)} for number in (21, 42)]
        for number in (21, 42):
            url = f"{ISSUES}{number}#issuecomment-{number}"
            replies = [METADATA, [issues], [[]], url]
            if number == 21:
                replies.append(None)  # The connection drops again before the second report.
            result = self.run_cli("sync", replies=replies)
            self.assertEqual(result["urls"], [url])
            posts = [args for args in self.recorded() if "POST" in args]
            self.assertEqual([args[3] for args in posts], [f"{API}/issues/{number}/comments"])
            if number == 21:
                self.assertIn("authentication", result["report_pending"])
                self.assertEqual([row["issue"] for row in self.run_cli("list")["pending"]], [42])
        self.assertEqual(self.run_cli("list")["pending"], [])
        for number in (21, 42):
            self.assertEqual(self.run_cli(*send, "--issue", str(number)),
                             {"url": f"{ISSUES}{number}#issuecomment-{number}"})
            self.assertEqual(self.recorded(), [])

    def test_auto_report_recovers_closed_issue_on_later_page_after_a_lost_response(self):
        known = ["set", "weekly-review-order", "--scope", "Weekly reviews", "--behavior", "Put pending decisions first."]
        self.run_cli(*known)
        self.assertEqual(self.recorded(), [])
        self.run_cli("reporting", "on")
        reply = self.run_cli(*known, replies=[METADATA, [[]], None])
        self.assertIn("report_pending", reply)
        post = self.recorded()[-1]
        self.assertEqual(post[:6], [*HOST, API + "/issues", "--method", "POST"])
        self.assertIn("title=Configurable weekly review order", post)
        public_body = next(arg[5:] for arg in post if arg.startswith("body="))
        issue = {"number": 89, "state": "closed", "title": "Renamed after review",
                 "body": public_body, "html_url": f"https://github.com/{RENAMED}/issues/89"}
        response = self.run_cli("sync", replies=[RENAMED_METADATA, [[], [issue]]])
        self.assertEqual(response["urls"], [issue["html_url"]])
        self.assertEqual(self.recorded(), [IDENTITY, [*PAGE, f"repos/{RENAMED}/issues?state=all&per_page=100"]])
        self.assertFalse(self.run_cli("list")["pending"])

    def test_renamed_repository_accepts_historical_receipts_and_delivers_new_comments(self):
        self.run_cli("reporting", "on")
        old_receipt = ISSUES + "21"
        self.run_cli(*self.send, "--approved", replies=[METADATA, [[]], old_receipt])
        new_url = f"https://github.com/{RENAMED}/issues/42"
        new_receipt = new_url + "#issuecomment-913"
        issue = {"number": 42, "state": "open", "title": "Another topic", "body": "", "html_url": new_url}
        send = [*self.send, "--issue", "42", "--approved"]
        created = self.run_cli(*send, replies=[RENAMED_METADATA, [[issue]], [[]], new_receipt])
        self.assertEqual(created, {"url": new_receipt})
        identity, issues, comments, post = self.recorded()
        endpoint = f"repos/{RENAMED}/issues/42/comments"
        self.assertEqual(identity, IDENTITY)
        self.assertEqual(issues, [*PAGE, f"repos/{RENAMED}/issues?state=all&per_page=100"])
        self.assertEqual(comments, [*PAGE, endpoint + "?per_page=100"])
        self.assertEqual(post[:6], [*HOST, endpoint, "--method", "POST"])
        self.assertEqual(self.run_cli(*self.send, "--issue", "21", "--approved"), {"url": old_receipt})
        self.assertEqual(self.recorded(), [])
        self.assertEqual(self.run_cli(*send), {"url": new_receipt})
        self.assertEqual(self.recorded(), [])

    def test_unconfirmed_live_and_saved_urls_do_not_become_receipts(self):
        self.run_cli("reporting", "on")
        new_url = f"https://github.com/{RENAMED}/issues/32"
        reply = self.run_cli(*self.send, "--approved", replies=[RENAMED_METADATA, [[]], ISSUES + "32"])
        self.assertIn("confirm a receipt", reply["report_pending"])
        self.assertEqual(self.recorded()[-1][:6], [*HOST, f"repos/{RENAMED}/issues", "--method", "POST"])
        body = next(arg[5:] for arg in self.recorded()[-1] if arg.startswith("body="))
        row = {"number": 32, "state": "open", "title": "Review format", "body": body, "html_url": new_url}
        for wrong in (ISSUES + "32", "https://github.com/another/oryx/issues/32", new_url + "0",
                      new_url + "/more", new_url + "#issuecomment-19"):
            with self.subTest(wrong=wrong):
                reply = self.run_cli("sync", replies=[RENAMED_METADATA, [[dict(row, html_url=wrong)]]])
                self.assertIn("confirm a receipt", reply["report_pending"])
                self.assertEqual(len(self.recorded()), 2)
        self.assertEqual(self.run_cli("sync", replies=[RENAMED_METADATA, [[row]]])["urls"], [new_url])
        ledger = self.work / "customizations/rules.json"
        state = json.loads(ledger.read_text())
        receipts = state["reports"]["private-agenda"]
        receipts[next(iter(receipts))] = "https://github.com/unrelated/oryx/issues/32"
        ledger.write_text(json.dumps(state))
        self.assertEqual(self.run_cli(*self.send, "--approved", replies=[RENAMED_METADATA, [[row]]]), {"url": new_url})
        self.assertEqual(len(self.recorded()), 2)
