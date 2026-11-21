"""Exercise the loopback interface against disposable signed PM workspaces."""

import json
import os
import subprocess
import sys
from threading import Thread
import unittest
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request, urlopen

import test_opportunities
from test_opportunities import pm
import local_ui


class LocalUITests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_opportunities.InitiativeTests()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        self.addCleanup(self.restore_signers)
        self.signers = os.environ.get("PM_HUB_ALLOWED_SIGNERS")
        os.environ["PM_HUB_ALLOWED_SIGNERS"] = self.fixture.env["PM_HUB_ALLOWED_SIGNERS"]
        self.approve = False
        self.reviewed = []
        app = local_ui.App(self.fixture.root, self.fixture.key, pm.prepare_private_write,
                           pm.run_initiative_work, self.confirm)
        self.server = local_ui.make_server(app)
        self.addCleanup(self.server.server_close)
        self.thread = Thread(target=self.server.serve_forever)
        self.thread.start()
        self.addCleanup(self.thread.join)
        self.addCleanup(self.server.shutdown)

    def restore_signers(self):
        if self.signers is None:
            os.environ.pop("PM_HUB_ALLOWED_SIGNERS", None)
        else:
            os.environ["PM_HUB_ALLOWED_SIGNERS"] = self.signers

    def confirm(self, root, review):
        self.assertEqual(root, self.fixture.root)
        self.reviewed.append(review)
        return self.approve

    def call(self, route, data, *, headers=None, failure=None):
        request = Request(self.server.origin + "/api/" + route, data=json.dumps(data).encode(),
                          headers={"Origin": self.server.origin, "Content-Type": "application/json",
                                   "X-PM-Hub-Token": self.server.token, **(headers or {})})
        if failure:
            with self.assertRaises(HTTPError) as error:
                urlopen(request, timeout=15)
            with error.exception as response:
                self.assertIn(failure, json.load(response)["error"])
            return
        with urlopen(request, timeout=15) as response:
            return json.load(response)

    def approve_candidate(self):
        fixture = self.fixture
        fixture.submit(fixture.setup_event(), fixture.capture(), fixture.describe(), fixture.metric(),
                       fixture.decision("evaluate"), fixture.decision("prepare-brief"))
        fixture.brief_ready()
        fixture.submit(fixture.target(), fixture.decision("approve-initiative"))

    def test_private_work_api_uses_cli_revision_and_validation(self):
        fixture = self.fixture
        fixture.submit(fixture.setup_event(), fixture.capture())
        scope = {"product": "example", "initiative": "renewal"}
        with urlopen(self.server.origin, timeout=5) as response:
            self.assertIn(b"oryx", response.read())
            self.assertIn("frame-ancestors 'none'", response.headers["Content-Security-Policy"])
        with self.assertRaises(HTTPError) as error:
            urlopen(self.server.origin + "/studio/settings.json", timeout=5)
        self.assertEqual(error.exception.code, 404)
        self.call("catalog", {}, headers={"Origin": "http://elsewhere.invalid"}, failure="launcher")
        self.call("catalog", {}, headers={"X-PM-Hub-Token": "invalid"}, failure="launcher")
        self.assertIn("renewal", self.call("catalog", {})["products"][0]["initiatives"])

        task = {"command": "task", "operation": "apply", "revision": "absent", **scope,
                "changes": [{"id": "handoff", "action": "add", "fields": {
                    "title": "Coordinate support handoff", "completion_criteria": "Support acknowledges receipt.",
                }}]}
        preview = self.call("work", task)
        self.assertEqual(preview["revision"], "absent")
        saved = self.call("work", {**task, "save": True})
        self.assertEqual(json.loads(fixture.cli("task", "list", "example", "renewal")), saved)
        self.call("work", {**task, "save": True}, failure="The list changed")
        checklist = {"command": "launch-checklist", "operation": "init", **scope}
        preview = self.call("work", checklist)
        self.assertEqual(preview["revision"], "absent")
        saved = self.call("work", {**checklist, "revision": preview["revision"], "save": True})
        self.assertEqual(json.loads(fixture.cli("launch-checklist", "list", "example", "renewal")), saved)
        self.call("work", {**checklist, "revision": preview["revision"], "save": True}, failure="The list changed")

    def test_slash_action_opens_the_selected_browser_screen(self):
        fixture = self.fixture
        action = ("workspace", "browser", "open")
        description = json.loads(fixture.cli("action", "--describe", *action))
        self.assertEqual(description["cli"], ["ui"])
        self.assertEqual(description["effect"], "read")
        command = [sys.executable, str(fixture.root / "tools/pm.py"), "action", *action, "--no-open"]
        for screen in ("roadmap", "tasks", "launch-checklists"):
            with self.subTest(screen=screen), subprocess.Popen(
                [*command, "--screen", screen], cwd=fixture.root, env=fixture.env,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            ) as process:
                try:
                    line = process.stdout.readline()
                    self.assertIn("oryx is open at ", line)
                    url = line.strip().removeprefix("oryx is open at ")
                    address = urlsplit(url)
                    self.assertEqual(address.hostname, "127.0.0.1")
                    self.assertEqual(parse_qs(address.query), {"screen": [screen]})
                    self.assertTrue(address.fragment)
                    with urlopen(url, timeout=5) as response:
                        self.assertIn(b"<title>oryx</title>", response.read())
                finally:
                    process.terminate()
                    process.wait(timeout=5)
        rejected = subprocess.run([*command, "--screen", "other"], cwd=fixture.root, env=fixture.env,
                                  capture_output=True, text=True, timeout=5)
        self.assertEqual(rejected.returncode, 2)
        self.assertIn("invalid choice", rejected.stderr)

    def test_unreviewed_studio_routes_api_reads_and_writes_to_agent_setup(self):
        fixture = self.fixture
        self.assertIn("products", self.call("catalog", {}))
        fixture.work.rename(fixture.parent / "reviewed-studio")
        fixture.cli("init-workspace", "--owner", "Fixture PM")
        before = {path: path.read_bytes() for path in pm.inventory(fixture.work) if path.is_file()}
        for endpoint, body in (
            ("catalog", {}),
            ("roadmap", {"product": "example"}),
            ("roadmap-preview", {"mode": "new", "product": "example"}),
            ("approve", {"id": "earlier-review"}),
            ("work", {"product": "example", "command": "task", "operation": "apply", "save": True}),
        ):
            with self.subTest(endpoint=endpoint), self.assertRaises(HTTPError) as error:
                self.call(endpoint, body)
            with error.exception as response:
                self.assertEqual(response.code, 409)
                result = json.load(response)
                self.assertEqual(result["status"], "onboarding_required")
                self.assertEqual(result["onboarding"]["stage"], "company")
                self.assertEqual(set(result["onboarding"]), {"stage", "stage_available", "prompt"})
        self.assertEqual(before, {path: path.read_bytes() for path in pm.inventory(fixture.work) if path.is_file()})

    def test_open_session_keeps_roadmap_exports_fields_and_starters_across_studio_upgrade(self):
        fixture = self.fixture
        self.approve_candidate()
        fixture.submit(fixture.cycle(), fixture.plan())
        signed = fixture.ledger.read_bytes()
        old = fixture.root / "private"
        fixture.work.rename(old)
        pages = old / "workspace/.views"
        pages.mkdir()
        (pages / "review.html").write_text("<title>Renewals review</title><!-- pm:roadmap-data -->")
        config = {"fields": {"x-score": {"type": "number", "label": "Pilot score"}},
                  "views": {"review": {"title": "Renewals review", "layout": "table", "page": "review",
                                       "columns": ["title", "x-score"]}},
                  "products": {"example": {"default_view": "review",
                                           "templates": {"prioritization": {"Sponsors": {
                                               "before": "Capacity constraints", "prompt": "Who approves the budget?"}}},
                                           "checkpoints": {"enablement": {"title": "Coach the renewal team"}}}}}
        (old / ".hub-customizations.json").write_text(json.dumps({
            "version": 1, "config": config, "values": {"example": {fixture.i: {"x-score": 0}}},
            "retired": [], "field_contracts": {}}, indent=2) + "\n")
        scope = {"product": "example"}
        board = self.call("roadmap", scope)
        view = board["presentation"]
        self.assertEqual(view["name"], "review")
        self.assertEqual(board["rows"][0]["x-score"], 0)
        comparison = self.call("comparison-template", scope)
        sections = list(comparison["sections"])
        self.assertEqual(sections[sections.index("Capacity constraints") - 1], "Sponsors")
        checklist = {**scope, "initiative": "renewal", "command": "launch-checklist", "operation": "init"}
        preview = self.call("work", checklist)
        self.assertIn("Coach the renewal team", [row["title"] for row in preview["checkpoints"]])
        self.assertFalse(fixture.work.exists())

        # The old client is still open when core updates. Saving the displayed
        # value is the first write; its template, page and register bytes match.
        settings_path = old / "settings.json"
        installed = json.loads(settings_path.read_text())
        installed["system_version"] = "0.10.0"
        settings_path.write_text(json.dumps(installed))
        self.call("roadmap-fields", {**scope, "id": fixture.i, "revision": view["revision"], "values": {"x-score": 0}})
        self.assertTrue(fixture.work.is_dir())
        self.assertEqual(self.call("comparison-template", scope), comparison)
        export = {**scope, "view": view["name"], "cycle": "quarter-two", "board_revision": board["revision"],
                  "revision": view["revision"], "page_revision": view["page_revision"]}
        html = self.call("roadmap-export", export)["html"]
        self.assertIn("<title>Renewals review</title>", html)
        self.assertIn('"x-score": 0', html)
        self.assertNotIn('"effort"', html)
        saved = self.call("work", {**checklist, "save": True, "revision": preview["revision"],
                                   "starter_revision": preview["starter_revision"]})
        self.assertEqual(saved["checkpoints"], preview["checkpoints"])
        self.call("roadmap-fields", {**scope, "id": fixture.i, "revision": view["revision"], "values": {"x-score": 17}})
        self.call("roadmap-export", export, failure="view changed")
        cli = json.loads(fixture.cli("roadmap", "--product", "example"))
        self.assertEqual(cli, [{"title": "Renewal delays", "x-score": 17}])
        self.assertEqual(fixture.ledger.read_bytes(), signed)

    def test_roadmap_cycle_and_reorder_need_the_reviewed_signature(self):
        self.approve_candidate()
        fixture = self.fixture
        board = self.call("roadmap", {"product": "example"})
        original = fixture.ledger.read_bytes()
        cycle = "renewal-planning"
        data = {
            "mode": "new", "product": "example", "cycle": cycle, "revision": board["revision"],
            "comparison_revision": "absent", "options": [fixture.i], "starts_on": fixture.today,
            "ends_on": fixture.today, "capacity": 2, "unit": "engineer-days",
            "sections": {"Objectives and obligations": "Improve the on-time renewal rate.",
                         "Capacity constraints": "Two engineer-days remain after scheduled maintenance.",
                         "Comparison": f"| Initiative ID | Assessment |\n| --- | --- |\n"
                                       f"| {fixture.i} | Addresses the late notices found in renewal reports. |\n\n"
                                       "Keeping capacity free would delay relief for the pilot group.",
                         "Sources": "Renewal cohort report and the reviewed Initiative Brief."},
            "placements": [{"initiative": fixture.i, "rank": 1, "effort": 2, "horizon": "now"}],
            "reason": "Release a small renewal pilot within available capacity.", "source": "Planning meeting minutes",
        }
        review = self.call("roadmap-preview", data)
        self.assertEqual(fixture.ledger.read_bytes(), original)
        comparison = self.call("comparison", {"product": "example", "cycle": cycle})
        self.assertEqual(review["documents"][0]["text"], comparison["text"])
        self.assertFalse(comparison["signed"])
        self.assertTrue(self.call("approve", {"id": review["id"]})["cancelled"])
        self.assertEqual(fixture.ledger.read_bytes(), original)

        self.approve = True
        self.call("approve", {"id": review["id"]})
        self.assertEqual(self.reviewed[-1], review)
        board = self.call("roadmap", {"product": "example"})
        self.assertEqual(board["rows"], json.loads(fixture.cli("roadmap", "--product", "example")))
        self.assertTrue(self.call("comparison", {"product": "example", "cycle": cycle})["signed"])

        edit = {"mode": "edit", "product": "example", "cycle": cycle, "revision": board["revision"],
                "order": {"now": [], "next": [fixture.i], "later": []}, "effort": {},
                "reason": "Move the pilot after the maintenance window.", "source": "PM planning review"}
        review = self.call("roadmap-preview", edit)
        self.assertEqual([event["action"] for event in review["changes"]], ["unplan", "plan"])
        self.call("approve", {"id": review["id"]})
        self.assertEqual(json.loads(fixture.cli("roadmap"))[0]["horizon"], "next")
        self.call("roadmap-preview", edit, failure="The roadmap changed")
        self.assertIn("PASS", fixture.cli("check"))


if __name__ == "__main__":
    unittest.main()
