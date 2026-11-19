"""Exercise PM task and launch workflows with fictional rollout records."""

from datetime import date
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import pm


class InitiativeWorkTests(unittest.TestCase):
    product = "billing"
    initiative = "renewal-rollout"

    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve() / "hub"
        for source in pm.inventory(pm.ROOT):
            if source.is_file():
                target = self.root / source.relative_to(pm.ROOT)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
        subprocess.run(["git", "init", "--quiet", "--initial-branch=main", str(self.root)], check=True)
        self.private = self.root / "private"
        self.env = dict(os.environ)
        self.env.pop("PM_HUB_SHARED_GROUP", None)
        self.cli("init-workspace", "--owner", "Fixture PM")
        company = "context/company/overview.md"
        product = f"context/products/{self.product}/overview.md"
        self.cli("new", "company-context", company)
        self.cli("new", "product-context", product)
        self.cli("new", "initiative-context", f"context/initiatives/{self.initiative}/overview.md", "--parent", product)
        self.work = self.private / "workspace" / "initiatives" / self.product / self.initiative

    def cli(self, *args, value=None, error=None):
        result = subprocess.run(
            [sys.executable, "-B", str(self.root / "tools" / "pm.py"), *args], cwd=self.root,
            env=self.env, capture_output=True, text=True, input=json.dumps(value) if value is not None else "",
        )
        if error is None:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn(error, result.stdout)
        return result.stdout

    def operation(self, kind, method, *args, value=None, error=None):
        output = self.cli(kind, method, self.product, self.initiative, *args, value=value, error=error)
        return None if error else json.loads(output)

    def change(self, kind, revision, *changes, error=None, preview=False):
        options = ("--revision", revision, "--preview") if preview else ("--revision", revision)
        return self.operation(kind, "apply", *options, value=changes, error=error)

    @staticmethod
    def add_task(identifier, **values):
        return {
            "action": "add", "id": identifier,
            "fields": {"title": f"Coordinate {identifier}", "completion_criteria": "The named team confirms receipt.", **values},
        }

    @staticmethod
    def update(identifier, **values):
        return {"action": "update", "id": identifier, "fields": values}

    def test_launch_readiness_requires_its_own_evidence_and_keeps_follow_through(self):
        # Based on Kubernetes production-readiness practices for rollout, rollback and monitoring.
        checklist = "launch-checklist"
        starter = self.operation(checklist, "init", "--preview")
        self.assertEqual({row["phase"] for row in starter["checkpoints"]}, {"upstream", "launch", "downstream"})
        self.assertEqual(starter["revision"], "absent")
        self.assertFalse(self.work.exists())
        saved = self.operation(checklist, "init")
        checkpoint_file = self.work / "launch-checklist.json"
        before = checkpoint_file.read_bytes()
        self.assertEqual(self.operation(checklist, "init"), saved)
        self.assertEqual(checkpoint_file.read_bytes(), before)

        tasks = self.change("task", "absent",
                            self.add_task("test-alert", owner="Fixture PM", priority="high"),
                            self.add_task("support-demo", depends_on=["test-alert"]))
        self.assertEqual(tasks["tasks"][1]["unfinished_dependencies"], ["test-alert"])
        linked = self.change(checklist, saved["revision"],
                             self.update("launch-monitoring", owner="On-call lead", tasks=["test-alert"]))
        tasks = self.change("task", tasks["revision"],
                            self.update("test-alert", status="done", resolution="On-call lead received the test alert."))
        self.assertEqual(tasks["tasks"][1]["unfinished_dependencies"], [])
        after = self.operation(checklist, "list")
        monitoring = next(row for row in after["checkpoints"] if row["id"] == "launch-monitoring")
        self.assertEqual(monitoring["task_status"], {"test-alert": "done"})
        self.assertEqual(monitoring["status"], "pending")
        self.assertEqual(after["launch_readiness"], "pending")

        before = checkpoint_file.read_bytes()
        self.change(checklist, linked["revision"], self.update("launch-monitoring", status="verified"),
                    error="Required fields")
        self.assertEqual(checkpoint_file.read_bytes(), before)
        day = date.today().isoformat()
        checks = []
        for row in after["checkpoints"]:
            if row["phase"] == "upstream":
                checks.append(self.update(row["id"], status="waived",
                                          waiver={"reason": "Internal billing drill only.", "by": "Fixture PM", "on": day}))
            elif row["phase"] == "launch":
                checks.append(self.update(
                    row["id"], owner="On-call lead", status="verified",
                    verification={"evidence": "Drill report, alert and rollback test results", "by": "On-call lead", "on": day},
                ))
        verified = self.change(checklist, linked["revision"], *checks)
        self.assertEqual(verified["launch_readiness"], "ready for launch decision")
        self.assertTrue(all(row["status"] == "pending" for row in verified["checkpoints"] if row["phase"] == "downstream"))
        self.change(checklist, verified["revision"], self.update("launch-monitoring", criterion="Verify a second region."),
                    error="Refresh verification")
        report = self.cli(checklist, "list", self.product, self.initiative, "--format", "markdown")
        self.assertIn("Drill report", report)
        self.assertIn("Confirm support handoff", report)
        self.assertIn("PASS", self.cli("check"))

    def test_dependent_task_edits_are_atomic_for_a_200_task_list(self):
        # Follows issue trackers that distinguish blocked-by links from status.
        edits = [self.add_task(f"follow-up-{number}") for number in range(200)]
        preview = self.change("task", "absent", *edits, preview=True)
        self.assertEqual(len(preview["tasks"]), 200)
        self.assertFalse(self.work.exists())
        saved = self.change("task", "absent", *edits)
        task_file = self.work / "tasks.json"
        self.assertEqual([path.name for path in self.work.iterdir()], ["tasks.json"])
        self.assertEqual(len(json.loads(task_file.read_text())["tasks"]), 200)
        before = task_file.read_bytes()

        self.change("task", saved["revision"],
                    self.update("follow-up-0", depends_on=["follow-up-1"]),
                    self.update("follow-up-1", depends_on=["follow-up-0"]), error="dependency cycle")
        self.change("task", saved["revision"], self.update("follow-up-0", depends_on=["other-initiative-task"]),
                    error="unknown task IDs")
        self.change("task", saved["revision"], self.update("follow-up-0", status="done", resolution="Received."),
                    error="owner needs")
        self.assertEqual(task_file.read_bytes(), before)
        revised = self.change("task", saved["revision"], self.update("follow-up-0", depends_on=["follow-up-1"]))
        self.assertNotEqual(revised["revision"], saved["revision"])
        self.change("task", saved["revision"], self.update("follow-up-1", owner="Other editor"), error="list changed")
        self.assertIn("PASS", self.cli("check"))

        # A merge can introduce inconsistent references even when both writers used the CLI.
        payload = json.loads(task_file.read_text())
        payload["tasks"]["follow-up-1"]["depends_on"] = ["follow-up-0"]
        task_file.write_text(json.dumps(payload), encoding="utf-8")
        self.cli("check", error="dependency cycle")

    def test_ownership_and_private_git_visibility(self):
        self.cli("task", "list", self.product, "unknown-initiative", error="existing initiative")
        self.cli("launch-checklist", "init", "other-product", self.initiative, error="existing initiative")
        self.assertFalse(self.work.exists())
        product = "context/products/retail/overview.md"
        self.cli("new", "product-context", product)
        self.cli("new", "initiative-context", f"context/products/retail/initiatives/{self.initiative}/overview.md", "--parent", product)
        retail = json.loads(self.cli("launch-checklist", "init", "retail", self.initiative))
        own = self.operation("launch-checklist", "list")
        self.assertTrue(retail["checkpoints"])
        self.assertEqual(own["checkpoints"], [])
        path = retail["path"]
        context = json.loads(self.cli("task-context", f"Compare billing handoff with private/{path}"))
        self.assertEqual(context["scope"]["product"], "retail")
        self.assertEqual(context["scope"]["initiative"], self.initiative)
        exclusion = self.private / ".git/info/exclude"
        with exclusion.open("a", encoding="utf-8") as stream:
            stream.write("\n**/tasks.json\n**/launch-checklist.json\n")
        self.change("task", "absent", self.add_task("test-alert"), error="ignores", preview=True)
        self.change("task", "absent", self.add_task("test-alert"), error="ignores")
        self.operation("launch-checklist", "init", "--preview", error="ignores")
        self.operation("launch-checklist", "init", error="ignores")
        self.assertFalse(self.work.exists())
