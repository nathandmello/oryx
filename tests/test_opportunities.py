"""Exercise reviewed initiative relationships and generated views through pm.py."""

import csv
from datetime import date, timedelta
import errno
import hashlib
from io import StringIO
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import pm
import records
from onboarding_fixtures import reviewed_studio


class InitiativeTests(unittest.TestCase):
    product_context = "context/products/example/overview.md"
    company = "context/company/overview.md"
    discovery = "workspace/initiatives/example/renewal/discovery-brief.md"
    brief = "workspace/initiatives/example/renewal/initiative-brief.md"
    planning = "workspace/roadmaps/example/quarter-two.md"
    today = date.today().isoformat()

    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.parent = Path(temporary.name).resolve()
        self.root = self.parent / "hub with spaces"
        for source in pm.inventory(pm.ROOT):
            if source.is_file():
                target = self.root / source.relative_to(pm.ROOT)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
        subprocess.run(["git", "init", "--quiet", "--initial-branch=main", str(self.root)], check=True)
        self.env = os.environ.copy()
        self.env.pop("PM_HUB_ALLOWED_SIGNERS", None)
        self.env.pop("PM_HUB_SHARED_GROUP", None)
        self.work = self.root / "studio"
        self.ledger = self.work / "workspace/backlogs/example/initiatives.json"
        self.cli("init-workspace", "--owner", "Fixture PM", "--delivery-system", "Fixture delivery")
        reviewed_studio(self.root, self.work)
        self.cli("new", "company-context", self.company)
        self.cli("new", "product-context", self.product_context)
        self.product_id = records.work_state((self.work / self.product_context).read_text())[0]["ID"]
        self.i = f"{self.product_id}/renewal"

    def write_legacy_register(self, record):
        """Reproduce a historical OpenSSH register and its original public trust configuration."""
        (self.work / ".oryx-approvals" / "example.json").unlink(missing_ok=True)
        key = self.parent / "legacy-key"
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)], check=True)
        signers = self.parent / "legacy-signers"
        signers.write_text("pm-hub-pm " + key.with_suffix(".pub").read_text())
        self.env["PM_HUB_ALLOWED_SIGNERS"] = str(signers)
        contents = json.dumps(record, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        signature = subprocess.check_output(["ssh-keygen", "-Y", "sign", "-f", str(key), "-n", "pm-hub-initiatives"],
                                            input=contents, stderr=subprocess.DEVNULL).decode("ascii")
        self.ledger.write_text(json.dumps({"record": record, "signature": signature}) + "\n")
        key.unlink()

    def test_initiative_work_resolves_approved_initiatives_without_changing_the_register(self):
        self.submit(self.setup_event())
        self.submit(self.capture())
        self.submit(self.capture(f"{self.product_id}/sources", "Follow billing handoffs", "Planning notes, item 9"))
        original = self.ledger.read_bytes()
        result = json.loads(self.cli("launch-checklist", "init", "example", "renewal"))
        self.assertEqual(result["launch_readiness"], "pending")
        self.cli("launch-checklist", "init", "example", "sources", error="reserved sources and secrets paths")
        self.assertEqual(self.ledger.read_bytes(), original)
        self.assertIn("PASS", self.cli("check"))

    def cli(self, *args, value=None, error=None, capture_result=False):
        result = subprocess.run(
            [sys.executable, str(self.root / "tools/pm.py"), *args], env=self.env,
            cwd=self.work if self.work.exists() else self.root, capture_output=True, text=True,
            input=json.dumps(value) if value is not None else "",
        )

        if error is None:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn(error, result.stdout)
        return result if capture_result else result.stdout

    def preview(self, *events, error=None):
        output = self.cli("initiative", "propose", "example", value=events, error=error)
        return json.loads(output) if error is None else output

    def apply(self, proposal, *, error=None):
        before = self.ledger.read_bytes() if self.ledger.exists() else None
        confirmations = []
        for identifier in proposal.get("intake_reviews", {}):
            confirmations.extend(("--confirm-distinct", identifier))
        self.cli("initiative", "apply", "example", "--approve", proposal["revision"], *confirmations,
                 value=proposal, error=error)
        if error is not None:
            self.assertEqual(self.ledger.read_bytes() if self.ledger.exists() else None, before)

    def submit(self, *events):
        self.apply(self.preview(*events))

    def setup_event(self, max_open=4, max_discovery=2):
        return {"type": "setup", "company": self.company, "product_context": self.product_context,
                "max_open": max_open, "max_discovery": max_discovery}

    def capture(self, identifier=None, title="Renewal delays", source="Support ticket #12"):
        return {"type": "capture", "initiative": identifier or self.i, "title": title, "source": source,
                "observed_on": self.today, "summary": "A buyer reported missing a renewal date."}

    def describe(self, identifier=None, problem="How to see upcoming renewals"):
        return {"type": "describe", "initiative": identifier or self.i, "problem": problem,
                "audience": "Multi-seat customers", "outcome": "Raise the on-time renewal rate",
                "source": "Interview notes, item 2"}

    def decision(self, action, identifier=None, **values):
        if action == "evaluate":
            values.setdefault("evaluation", {"value": "Reduce customer friction", "strategic_fit": "Supports retention",
                                            "urgency": None, "sources": [], "unknowns": "Timing needs confirmation"})
        return {"type": "decision", "initiative": identifier or self.i, "action": action, "on": self.today,
                "reason": "The PM confirmed the trade-off.", "source": "Product review notes", **values}

    def ship_without_checklist(self, **values):
        return self.decision("ship", review_on=self.today, exceptions={
            "missing:checklist": {"authority": "Fixture incident PM",
                                  "reason": "The incident commander verified rollback during the emergency drill."}
        }, **values)

    def metric(self):
        return {"type": "metric", "metric": "renewal-rate", "name": "On-time renewal rate",
                "definition": "Renewals on schedule divided by eligible renewals", "unit": "percent",
                "source": "Metric catalogue entry R-12"}

    def target(self, identifier=None):
        return {"type": "target", "initiative": identifier or self.i, "metric": "renewal-rate",
                "baseline": "70 percent", "target": "85 percent", "due": self.today,
                "guardrails": "Track unsubscribe rate", "source": "Renewal cohort report"}

    def evidence(self):
        return [
            {"type": "hypothesis", "initiative": self.i, "hypothesis": "timing",
             "statement": "Reminders help administrators act on time", "risk": "value", "source": "Research notes"},
            {"type": "experiment", "initiative": self.i, "experiment": "notification-pilot", "hypothesis": "timing",
             "metric": "renewal-rate", "method": "Offer a pilot to 20 accounts", "criterion": "Improve by ten points",
             "planned_on": self.today, "source": "Pilot protocol"},
            {"type": "result", "initiative": self.i, "result": "pilot-report", "experiment": "notification-pilot",
             "observation": "Eight more accounts renewed on time", "conclusion": "supported",
             "observed_on": self.today, "source": "Pilot data sheet"},
            {"type": "assess", "initiative": self.i, "hypothesis": "timing", "confidence": 8,
             "evidence": "Pilot data sheet, tab 2", "limits": "Small pilot in one segment"},
        ]

    def new(self, kind, path, error=None):
        self.cli("new", kind, path, error=error)

    def fill(self, path, sections, complete=True):
        target = self.work / path
        text = target.read_text()
        for section, body in sections.items():
            current = records.section(text, section)
            self.assertIsNotNone(current, section)
            index = text.index(current, text.index(f"## {section}\n"))
            text = text[:index] + body + "\n\n" + text[index + len(current):]
        if complete:
            text = text.replace("| State | draft |", "| State | complete |")
            text = text.replace("{{one concrete step}}", "None")
        target.write_text(text)

    def brief_ready(self, path=None):
        path = path or self.brief
        self.new("initiative-brief", path)
        self.fill(path, {
            "Proposal": "Send account reminders.",
            "Value and alignment": "Earlier action supports retention.",
            "Approach and scope": "Pilot reminders for multi-seat accounts.",
            "Delivery and launch": "Brief Support before expanding the pilot.",
            "Assumptions and risks": "Check opt-out rates and account constraints.",
            "Sources": "Fixture research summary and Engineering estimate.",
        })

    def cycle(self, capacity=4, options=None):
        options = options or [self.i]
        comparison = ["| Initiative ID | Assessment |", "| --- | --- |"]
        comparison.extend(f"| {identifier} | Pilot evidence supports the proposed scope. |" for identifier in options)
        comparison.append("\nDelivery capacity already covers maintenance.")
        self.new("prioritization", self.planning)
        self.fill(self.planning, {
            "Objectives and obligations": "Improve on-time renewal.",
            "Capacity constraints": "Budget the remaining engineer-days after maintenance.",
            "Comparison": "\n".join(comparison),
            "Sources": "Planning notes and tracker estimates.",
        })
        return {"type": "cycle", "cycle": "quarter-two", "capacity": capacity, "unit": "engineer-days",
                "starts_on": self.today, "ends_on": self.today, "options": options}

    def plan(self, identifier=None, rank=1, effort=3):
        return self.decision("plan", identifier, cycle="quarter-two", rank=rank, horizon="now", effort=effort)

    def trace(self):
        return json.loads(self.cli("initiative", "show", "example", self.i))

    def test_filing_preview_preserves_an_approved_brief(self):
        self.submit(self.setup_event(), self.capture(), self.describe(), self.metric(), self.decision("evaluate"))
        self.submit(self.decision("prepare-brief"))
        self.brief_ready()
        self.submit(self.target(), self.decision("approve-initiative"))
        path = self.work / self.brief
        original = path.read_bytes()
        text = path.read_text().replace("Send account reminders.\n", "Send account reminders.\nReview the pilot result.\n")
        plan = {"id": "brief-format-review", "reason": "Improve the proposed briefing language.",
                "changes": [{"path": self.brief, "before": hashlib.sha256(original).hexdigest(), "text": text}]}
        self.cli("align", "--preview-plan", value=plan, error="binds approved evidence")
        self.assertEqual(path.read_bytes(), original)

    def test_one_id_through_discovery_delivery_and_measured_outcomes(self):
        self.submit(self.setup_event(), self.capture(), self.describe(), self.metric(),
                    self.decision("evaluate"))
        self.assertEqual(json.loads(self.cli("backlog", "--phase", "under consideration"))[0]["id"], self.i)
        start = self.decision("start-discovery", review_on=self.today)
        self.preview(start, error="Required discovery-brief record is missing")
        self.assertEqual(self.trace()["files"]["discovery-brief"], {"path": self.discovery, "present": False})
        self.new("discovery-brief", self.discovery)
        self.assertEqual(self.trace()["files"]["discovery-brief"], {"path": self.discovery, "present": True})
        self.fill(self.discovery, {
            "Known, assumed, and unknown": "Three renewals missed their dates. The rate is unclear.",
            "Learning goals and exit criteria": "Check reminder effectiveness and revisit the decision.",
            "Approach and timebox": "Test reminder timing this week.",
            "Capacity and review": "Research has one week. Review on Friday.",
            "Sources": "Fixture research outline.",
        }, complete=False)
        hypothesis, test, result, assessment = self.evidence()
        self.preview(start, error="decision-critical hypotheses")
        self.submit(hypothesis, start, test)
        self.assertEqual(json.loads(self.cli("backlog", "--due"))[0]["phase"], "in discovery")
        self.preview({**result, "experiment": "unknown"}, error="Unknown experiment in this initiative")
        self.preview({**result, "observed_on": "2020-01-01"}, error="follow their test plan")
        self.preview({**assessment, "confidence": 11}, error="needs confidence")
        self.fill(self.discovery, {"Findings and recommendation": "The pilot supports preparing a proposal."})
        finish = self.decision("prepare-brief")
        self.preview(finish, error="Assess each decision-critical hypothesis")
        self.submit(result, assessment, finish)
        self.brief_ready()
        self.preview(self.decision("approve-initiative"), error="linked success metric")
        self.submit(self.target(), self.decision("approve-initiative"))
        candidates = json.loads(self.cli("backlog", "--phase", "candidate"))
        self.assertEqual(candidates[0]["id"], self.i)
        self.assertEqual(json.loads(self.cli("roadmap")), [])
        self.submit(self.cycle(), self.plan())
        roadmap = json.loads(self.cli("roadmap", "--cycle", "quarter-two"))
        self.assertEqual(roadmap[0]["id"], self.i)
        self.assertEqual(roadmap[0]["outcome"], "Raise the on-time renewal rate")
        self.assertEqual(roadmap[0]["rank"], 1)
        self.assertEqual(roadmap[0]["success_metrics"], ["renewal-rate"])
        self.assertEqual(roadmap[0]["planning_record"], self.planning)
        self.assertEqual(self.trace()["files"]["planning_comparison"], self.planning)
        self.assertEqual(self.trace()["files"]["register"], self.ledger.relative_to(self.work).as_posix())
        roadmap_csv = self.cli("roadmap", "--format", "csv")
        backlog_markdown = self.cli("backlog", "--format", "markdown")
        register = self.ledger.read_bytes()
        self.cli("action", "workspace", "preferences", "set", "--detail", "concise", "--layout", "bullets")
        self.assertEqual(self.cli("action", "portfolio", "roadmap", "show", "--format", "csv"), roadmap_csv)
        self.assertEqual(self.cli("action", "portfolio", "backlog", "show", "--format", "markdown"), backlog_markdown)
        self.assertEqual(json.loads(self.cli("action", "initiative", "record", "show", "example", self.i)), self.trace())
        self.assertEqual(self.ledger.read_bytes(), register)
        csv_row = next(csv.DictReader(StringIO(roadmap_csv)))
        self.assertEqual(csv_row["id"], self.i)
        self.assertIn("| Initiative ID |", backlog_markdown)
        self.new("roadmap", "workspace/roadmaps/standalone.md")
        self.assertEqual(len(json.loads(self.cli("roadmap"))), 1)
        delivery = "https://example.com/tracker/DEL-12"
        measure = {"type": "measurement", "initiative": self.i, "measurement": "release-review",
                   "metric": "renewal-rate", "value": "87 percent", "observed_on": self.today, "source": "Dashboard"}
        self.preview(measure, error="follow the verified release")
        self.submit(self.decision("start-delivery", delivery=delivery), self.ship_without_checklist(), measure)
        report = self.trace()
        item = report["initiative"]
        self.assertEqual(item["id"], self.i)
        self.preview(self.decision("unplan"), error="Cannot unplan from shipped")
        self.assertEqual(item["delivery"], delivery)
        self.assertEqual(item["experiment_drafts"], {})
        self.assertEqual(item["results"]["pilot-report"]["experiment"], "notification-pilot")
        self.assertEqual(item["experiments"]["notification-pilot"]["hypothesis"], "timing")
        self.assertEqual(item["experiments"]["notification-pilot"]["metric"],
                         item["measurements"]["release-review"]["metric"])
        self.assertEqual(report["metric_definitions"]["renewal-rate"]["unit"], "percent")
        self.assertEqual(report["context"]["company"]["path"], self.company)
        self.assertEqual(report["context"]["product"]["id"], self.product_id)
        self.cli("check")

    def test_metric_creates_one_named_draft_and_preserves_edits_until_approved(self):
        metric = "renewal-rate"
        approval = {"type": "approve-experiment", "initiative": self.i, "metric": metric}
        hypothesis, plan, result, _ = self.evidence()
        self.submit(self.setup_event(), self.capture(), self.metric())
        target = self.preview(self.target())
        self.assertEqual(self.trace()["initiative"]["experiment_drafts"], {})
        self.apply(target)
        draft = self.trace()["initiative"]["experiment_drafts"][metric]
        path = self.work / draft["path"]
        self.assertEqual(path.name, "experiment.renewal-rate.draft.json")
        if os.name == "posix":
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(self.ledger.stat().st_mode), 0o600)
        self.assertEqual(path.parent, self.work / "workspace/experiments/example/renewal")
        self.assertEqual(draft["initiative"], self.i)
        self.assertEqual(set(draft["missing"]), {"hypothesis", "method", "criterion", "planned_on", "source"})
        saved = json.loads(path.read_text())
        self.assertIsNone(saved["criterion"])
        self.assertNotIn("baseline", saved)
        self.assertNotIn("guardrails", saved)
        self.preview(approval, error="complete hypothesis, method, criterion, planned_on, source")
        experiment_id = saved["experiment"]
        self.preview({**result, "experiment": experiment_id}, error="Unknown experiment")
        saved["method"] = "Test the agreed renewal reminders"
        path.write_text(json.dumps(saved))
        self.submit(hypothesis, {**self.target(), "target": "86 percent"})
        self.cli("initiative", "sync-drafts", "example")
        self.assertEqual(json.loads(path.read_text()), saved)
        self.assertEqual(len(list(path.parent.glob("*.draft.json"))), 1)
        self.assertEqual(self.trace()["initiative"]["targets"][metric]["target"], "86 percent")
        self.cli("check")
        for key in ("hypothesis", "criterion", "planned_on", "source"):
            saved[key] = plan[key]
        path.write_text(json.dumps(saved))
        ready = self.preview(approval)
        self.assertEqual(ready["reviewed_transactions"], [{"type": "experiment", **saved}])
        self.assertTrue(path.exists())
        self.preview({**plan, "experiment": experiment_id}, error="Use approve-experiment")
        saved["criterion"] = "Increase the on-time renewal rate by eight points"
        path.write_text(json.dumps(saved))
        self.apply(ready, error="stale or was modified")
        self.assertTrue(path.exists())
        self.submit(approval)
        self.assertFalse(path.exists())
        self.submit({**result, "experiment": experiment_id})
        self.cli("initiative", "sync-drafts", "example")
        item = self.trace()["initiative"]
        self.assertEqual(item["experiment_drafts"], {})
        self.assertEqual(item["experiments"][experiment_id]["criterion"], saved["criterion"])
        self.assertEqual(item["results"]["pilot-report"]["experiment"], experiment_id)
        self.cli("check")

    def test_experiment_approval_precedes_test_and_result(self):
        hypothesis, plan, result, _ = self.evidence()
        self.submit(self.setup_event(), self.capture(), self.metric(), hypothesis, self.target())
        before = self.ledger.read_bytes()
        self.preview(plan, result, error="Apply the experiment approval before proposing its results")
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        self.preview({**plan, "planned_on": yesterday}, error="approval date or later")
        self.preview({**plan, "planned_on": (date.today() + timedelta(days=1)).isoformat()})

        draft = self.trace()["initiative"]["experiment_drafts"]["renewal-rate"]
        path = self.work / draft["path"]
        contents = json.loads(path.read_text())
        contents.update({key: plan[key] for key in draft["missing"]})
        contents["planned_on"] = yesterday
        path.write_text(json.dumps(contents))
        approval = {"type": "approve-experiment", "initiative": self.i, "metric": "renewal-rate"}
        self.preview(approval, error="approval date or later")
        contents["planned_on"] = self.today
        path.write_text(json.dumps(contents))
        result = {**result, "experiment": contents["experiment"]}
        self.preview(approval, result, error="Apply the experiment approval before proposing its results")
        self.assertEqual(self.ledger.read_bytes(), before)
        self.submit(approval)
        self.preview({**result, "observed_on": yesterday}, error="follow their test plan")
        self.submit(result)

    @unittest.skipUnless(os.name == "posix", "POSIX group permissions")
    def test_shared_writes_reject_directories_without_setgid(self):
        import grp
        self.submit(self.setup_event(), self.capture(), self.metric())
        self.assertEqual(stat.S_IMODE(self.ledger.stat().st_mode), 0o600)
        self.env["PM_HUB_SHARED_GROUP"] = grp.getgrgid(self.ledger.parent.stat().st_gid).gr_name
        self.ledger.parent.chmod(0o750)
        self.apply(self.preview(self.describe()), error="mode 2750")

        home = self.work / "workspace/experiments/example/renewal"
        home.mkdir(parents=True)
        home.chmod(0o770)
        self.cli("initiative", "draft-experiment", "example", self.i, "renewal-rate", error="mode 2770")
        self.assertEqual(list(home.iterdir()), [])

    @unittest.skipUnless(os.name == "posix", "POSIX group permissions")
    def test_opt_in_group_access_for_register_and_drafts(self):
        import grp

        def provision(directory, mode):
            ordinary_mode = mode & ~stat.S_ISGID
            try:
                directory.chmod(mode)
            except OSError as exc:
                if exc.errno not in {errno.EPERM, errno.EACCES, errno.ENOTSUP}:
                    raise
                directory.chmod(ordinary_mode)
                self.assertEqual(stat.S_IMODE(directory.stat().st_mode), ordinary_mode)
                self.skipTest(f"Optional two-account sharing: test directory rejects setgid ({exc.strerror})")
            actual = stat.S_IMODE(directory.stat().st_mode)
            if actual == ordinary_mode:
                self.skipTest("Optional two-account sharing: test directory strips setgid")
            self.assertEqual(actual, mode)

        self.ledger.parent.mkdir(parents=True, exist_ok=True)
        self.env["PM_HUB_SHARED_GROUP"] = grp.getgrgid(self.ledger.parent.stat().st_gid).gr_name
        lock = self.work / ".git" / "pm-hub-writer.lock"
        lock.chmod(0o440)
        provision(self.ledger.parent, 0o2770)
        proposal = self.preview(self.setup_event(), self.capture(), self.metric())
        self.apply(proposal, error="mode 2750")
        provision(self.ledger.parent, 0o2750)
        approvals = self.work / ".oryx-approvals"
        approvals.mkdir(exist_ok=True)
        provision(approvals, 0o2750)
        self.apply(proposal)
        self.assertEqual(stat.S_IMODE(self.ledger.stat().st_mode), 0o640)
        before = self.ledger.read_bytes()
        self.apply(self.preview(self.target()), error="mode 2770")
        self.assertEqual(self.ledger.read_bytes(), before)
        home = self.work / "workspace/experiments/example/renewal"
        home.mkdir(parents=True)
        provision(home, 0o2770)
        self.submit(self.target())
        path = self.work / self.trace()["initiative"]["experiment_drafts"]["renewal-rate"]["path"]
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o660)
        self.assertEqual(path.stat().st_gid, home.stat().st_gid)
        self.assertEqual(stat.S_IMODE(self.ledger.stat().st_mode), 0o640)
        self.assertEqual(self.ledger.stat().st_gid, self.ledger.parent.stat().st_gid)
        self.assertEqual(stat.S_IMODE(lock.stat().st_mode), 0o440)
        self.cli("initiative", "draft-experiment", "example", self.i, "renewal-rate")

    def test_prior_signed_experiment_dates_remain_readable(self):
        hypothesis, plan, result, _ = self.evidence()
        past = "2020-01-01"
        self.submit(self.setup_event(), {**self.capture(), "observed_on": past}, self.metric(), hypothesis)
        envelope = json.loads(self.ledger.read_text())
        envelope["record"]["events"].extend([{**plan, "planned_on": past}, {**result, "observed_on": past}])
        self.write_legacy_register(envelope["record"])
        self.assertEqual(self.trace()["initiative"]["results"][result["result"]]["observed_on"], past)
        self.submit(self.target())
        self.assertEqual(self.trace()["initiative"]["experiments"][plan["experiment"]]["planned_on"], past)

    def test_early_draft_identity_naming_and_recovery(self):
        self.submit(self.setup_event(), self.capture(), self.metric())
        before = self.ledger.read_bytes()
        cmd = ("initiative", "draft-experiment", "example", self.i)
        self.cli(*cmd, "missing", error="Unknown product metric")
        path = self.work / self.cli(*cmd, "renewal-rate").strip()
        initial = path.read_text()
        self.assertEqual(self.cli(*cmd, "renewal-rate").strip(), path.relative_to(self.work).as_posix())
        self.assertEqual(self.ledger.read_bytes(), before)
        self.assertEqual(self.trace()["metric_definitions"]["renewal-rate"]["unit"], "percent")
        self.submit(self.target())
        self.assertEqual(path.read_text(), initial)
        approval = {"type": "approve-experiment", "initiative": self.i, "metric": "renewal-rate"}
        wrong = {**json.loads(initial), "initiative": self.product_id + "/elsewhere"}
        path.write_text(json.dumps(wrong))
        self.cli("check", error="keep the original initiative")
        self.preview(approval, error="keep the original initiative")
        path.write_text(json.dumps({**json.loads(initial), "hypothesis": "absent"}))
        self.cli("check", error="Unknown hypothesis in this initiative")
        path.write_text(initial)
        wrong_name = path.with_name("experiment.renewal-rate.v2.draft.json")
        path.rename(wrong_name)
        self.cli("check", error="use experiment.<metric-id>.draft.json")
        wrong_name.unlink()
        self.cli("check", error="missing file")
        self.cli("initiative", "sync-drafts", "example")
        self.assertEqual(path.read_text(), initial)
        misplaced = path.parent.parent / path.name
        misplaced.write_text(initial)
        self.cli("check", error="place the draft in its registered initiative's experiment folder")
        misplaced.unlink()
        self.cli("check")

    def test_draft_errors_only_block_changes_to_the_affected_initiative_metric(self):
        self.submit(self.setup_event(), self.capture(), self.metric(), self.target())
        original = self.trace()["initiative"]["experiment_drafts"]["renewal-rate"]
        path = self.work / original["path"]
        invalid = json.loads(path.read_text())
        invalid["method"] = 17
        path.write_text(json.dumps(invalid))

        second = self.product_id + "/renewal-support"
        self.submit(self.capture(second, "Renewal support", "Support ticket 20"))
        self.submit(self.target(second))
        sibling = json.loads(self.cli("initiative", "show", "example", second))["initiative"]
        self.assertTrue((self.work / sibling["experiment_drafts"]["renewal-rate"]["path"]).is_file())
        self.submit({**self.metric(), "metric": "unsubscribe-rate", "name": "Unsubscribe rate"},
                    {**self.target(), "metric": "unsubscribe-rate"})
        self.assertTrue(path.with_name("experiment.unsubscribe-rate.draft.json").is_file())
        self.assertEqual(json.loads(path.read_text()), invalid)

        self.apply(self.preview({**self.target(), "target": "89 percent"}), error="invalid method")
        self.cli("check", error="invalid method")
        self.cli("initiative", "sync-drafts", "example", error="invalid method")

    def test_shared_metric_keeps_initiative_drafts_and_results_separate(self):
        second = self.product_id + "/renewal-support"
        self.submit(self.setup_event(), self.capture(), self.capture(second, "Renewal support", "Support ticket 20"),
                    self.metric(), self.target(), self.target(second))
        first = self.trace()["initiative"]["experiment_drafts"]["renewal-rate"]
        sibling = json.loads(self.cli("initiative", "show", "example", second))["initiative"]
        other = sibling["experiment_drafts"]["renewal-rate"]
        self.assertNotEqual(first["path"], other["path"])
        second_file = self.work / other["path"]
        before = second_file.read_bytes()
        hypothesis, plan, result, _ = self.evidence()
        self.submit(hypothesis, plan)
        self.assertFalse((self.work / first["path"]).exists())
        self.assertEqual(second_file.read_bytes(), before)
        self.preview({**result, "initiative": second}, error="Unknown experiment in this initiative")
        self.cli("check")

    def test_products_share_local_names_without_sharing_initiatives_or_drafts(self):
        other_context = "context/products/service/overview.md"
        self.new("product-context", other_context)
        other_id = records.work_state((self.work / other_context).read_text())[0]["ID"] + "/renewal"
        self.submit(self.setup_event(), self.capture(), self.metric(), self.target())
        setup = {**self.setup_event(), "product_context": other_context}
        changes = [setup, self.capture(other_id), self.metric(), self.target(other_id)]
        proposal = json.loads(self.cli("initiative", "propose", "service", value=changes))
        self.cli("initiative", "apply", "service", "--approve", proposal["revision"], value=proposal)

        first = self.trace()["initiative"]
        other = json.loads(self.cli("initiative", "show", "service", other_id))["initiative"]
        paths = [item["experiment_drafts"]["renewal-rate"]["path"] for item in (first, other)]
        self.assertEqual(paths, [f"workspace/experiments/{product}/renewal/experiment.renewal-rate.draft.json"
                                 for product in ("example", "service")])
        visible = subprocess.run(["git", "ls-files", "--others", "--exclude-standard", "--", *paths],
                                 cwd=self.work, text=True, capture_output=True, check=True)
        self.assertEqual(set(visible.stdout.splitlines()), set(paths))
        files = [self.work / path for path in paths]
        self.assertEqual([json.loads(path.read_text())["initiative"] for path in files], [self.i, other_id])
        second_before = files[1].read_bytes()
        hypothesis, experiment, _, _ = self.evidence()
        self.submit(hypothesis, experiment)
        self.assertFalse(files[0].exists())
        self.assertEqual(files[1].read_bytes(), second_before)
        self.cli("initiative", "show", "service", self.i, error="Unknown initiative")
        self.new("initiative-brief", self.brief)
        self.new("initiative-brief", "workspace/initiatives/service/renewal/initiative-brief.md")
        self.assertEqual({row["id"] for row in json.loads(self.cli("backlog"))}, {self.i, other_id})
        self.cli("check")

    def test_ignored_drafts_cannot_be_created_by_hand_or_by_an_approved_target(self):
        self.submit(self.setup_event(), self.capture(), self.metric())
        path = "workspace/experiments/example/renewal/experiment.renewal-rate.draft.json"
        with (self.work / ".git/info/exclude").open("a") as output:
            output.write(f"\n/{path}\n")
        self.cli("initiative", "draft-experiment", "example", self.i, "renewal-rate", error="private repository ignores")
        self.apply(self.preview(self.target()), error="private repository ignores")
        self.assertFalse((self.work / path).exists())

    def test_interrupted_publication_retries_only_the_exact_reviewed_batch(self):
        self.submit(self.setup_event(), self.capture())
        before = self.ledger.read_bytes()
        proposal = self.preview(self.describe())
        other = self.preview(self.describe(problem="Renewal notices reach the wrong team"))
        store = pm.initiative_store
        replace = store.storage.replace_text

        def interrupt_register_write(target, *args, **kwargs):
            if target == self.ledger:
                raise OSError("Interrupted register write")
            return replace(target, *args, **kwargs)

        with patch.object(store.storage, "replace_text", interrupt_register_write):
            with self.assertRaisesRegex((ValueError, OSError), "Interrupted register write"):
                store.apply(self.root, "example", proposal, approved_revision=proposal["revision"])
        self.assertEqual(self.ledger.read_bytes(), before)
        self.apply(other, error="does not match the reviewed revision")
        self.assertEqual(self.ledger.read_bytes(), before)
        self.ledger.write_bytes(before.replace(b"Renewal delays", b"Changed title"))
        self.apply(proposal, error="does not match the reviewed revision")
        self.ledger.write_bytes(before)
        self.apply(proposal)
        saved = json.loads(self.ledger.read_bytes())["record"]["events"]
        self.assertEqual(saved, json.loads(before)["record"]["events"] + proposal["reviewed_transactions"])
        next_proposal = self.preview(self.metric())
        with patch.object(store.storage, "replace_text", interrupt_register_write):
            with self.assertRaisesRegex((ValueError, OSError), "Interrupted register write"):
                store.apply(self.root, "example", next_proposal, approved_revision=next_proposal["revision"])
        self.assertIn(next_proposal["revision"], self.cli("initiative", "recover", "example"))
        recovered = self.ledger.read_bytes()
        self.assertEqual(json.loads(recovered)["record"]["events"], saved + next_proposal["reviewed_transactions"])
        self.cli("initiative", "recover", "example")
        self.assertEqual(self.ledger.read_bytes(), recovered)
        self.cli("check")

    def test_existing_approval_requires_its_receipt_and_blocks_protected_agent_apply(self):
        self.submit(self.setup_event(), self.capture())
        original = self.ledger.read_bytes()
        proposal = self.preview(self.describe())
        self.env["PM_HUB_PROTECTED_ROOT"] = str(self.root)
        self.apply(proposal, error="protected")
        self.assertEqual(self.ledger.read_bytes(), original)
        del self.env["PM_HUB_PROTECTED_ROOT"]
        receipt = self.work / ".oryx-approvals" / "example.json"
        saved = receipt.read_bytes()
        receipt.unlink()
        self.cli("initiative", "show", "example", error="missing PM approval receipt")
        self.apply(proposal, error="missing PM approval receipt")
        self.assertFalse(receipt.exists())
        receipt.write_bytes(saved)
        self.assertEqual(self.ledger.read_bytes(), original)
        self.apply(proposal)

    def test_verified_legacy_history_carries_forward_without_private_signing_material(self):
        initial = self.preview(self.setup_event(), self.capture())
        record = {"version": 1, "product": "example", "events": initial["reviewed_transactions"]}
        self.ledger.parent.mkdir(parents=True, exist_ok=True)
        self.write_legacy_register(record)
        original = self.ledger.read_bytes()
        signers = self.env.pop("PM_HUB_ALLOWED_SIGNERS")
        self.cli("initiative", "show", "example", error="PM_HUB_ALLOWED_SIGNERS")
        self.env["PM_HUB_ALLOWED_SIGNERS"] = signers
        self.ledger.write_bytes(original.replace(b"Renewal delays", b"Changed title"))
        self.cli("initiative", "show", "example", error="signature")
        self.ledger.write_bytes(original)
        self.assertEqual(self.trace()["initiative"]["id"], self.i)
        self.assertEqual(self.ledger.read_bytes(), original)

        proposal = self.preview(self.describe())
        self.apply(proposal)
        current = self.ledger.read_bytes()
        envelope = json.loads(current)
        self.assertEqual(envelope["record"]["events"][:-1], record["events"])
        legacy, approved = envelope["approvals"]
        self.assertEqual(legacy["signature"], json.loads(original)["signature"])
        self.assertEqual(legacy["through"], len(record["events"]))
        self.assertEqual(approved["owner"], "Fixture PM")
        self.assertEqual(approved["revision"], proposal["revision"])
        self.assertEqual(approved["through"], len(envelope["record"]["events"]))
        self.assertTrue(approved["approved_at"])
        self.ledger.write_bytes(original)
        self.cli("initiative", "show", "example", error="does not match the reviewed revision")
        self.ledger.write_bytes(current)
        del self.env["PM_HUB_ALLOWED_SIGNERS"]
        Path(signers).unlink()
        self.assertEqual(self.trace()["initiative"]["description"]["problem"], self.describe()["problem"])
        self.cli("check")

    def test_explicit_approval_and_stale_reviews(self):
        proposal = self.preview(self.setup_event(), self.capture(), self.describe(),
                                self.decision("evaluate"),
                                self.decision("prepare-brief"))
        self.cli("initiative", "apply", "example", "--approve", "0" * 64, value=proposal, error="revision")
        self.assertFalse(self.ledger.exists())
        self.apply(proposal)
        self.apply(proposal, error="one setup")
        self.brief_ready()
        self.submit(self.metric(), self.target())
        ready = self.preview(self.decision("approve-initiative"))
        path = self.work / self.brief
        original = path.read_text()
        path.write_text(original.replace("account reminders", "billing reminders"))
        self.apply(ready, error="proposal is stale")
        path.write_text(original)
        self.apply(ready)
        self.submit(self.cycle(), self.plan())
        original = path.read_text()
        path.write_text(original.replace("account reminders", "billing reminders"))
        self.cli("check", error="differs from the reviewed revision")
        self.cli("roadmap", error="differs from the reviewed revision")
        self.preview(self.decision("start-delivery", delivery="https://example.com/one"),
                     self.ship_without_checklist(), error="differs from the reviewed revision")
        self.assertTrue(self.trace()["review_issues"])
        self.submit(self.decision("reopen"))
        self.assertEqual(self.trace()["initiative"]["phase"], "under consideration")
        self.assertEqual(json.loads(self.cli("roadmap")), [])
        signed_text = self.ledger.read_text()
        self.ledger.write_text(signed_text.replace("Renewal delays", "Direct write attempt"))
        self.cli("backlog", error="does not match the reviewed revision")
        self.cli("check", error="does not match the reviewed revision")
        self.ledger.write_text(signed_text)
        self.cli("check")

    def test_due_backlog_reports_stale_approval_and_keeps_unrelated_reminder(self):
        renewals = "product/example/area/renewals"
        imports = "product/example/area/imports"
        incident = f"{self.product_id}/incident-retry"
        self.cli("set-remit", value={"status": "confirmed", "responsibilities": [], "follow": [renewals, imports]})
        self.submit(self.setup_event(), {**self.capture(), "areas": [renewals]}, self.describe(),
                    self.decision("evaluate"), self.decision("prepare-brief"))
        self.brief_ready()
        self.submit(self.metric(), self.target(), self.decision("approve-initiative"))
        self.submit(self.cycle(), self.plan())
        self.submit({**self.capture(incident, "Restore import retries", "Incident bridge log, entry 7"),
                     "summary": "New uploads stalled after a vendor outage.", "areas": [imports]},
                    self.decision("expedite", incident, delivery="https://example.com/delivery/42",
                                  owner="Support lead", obligation="Restore account imports", deadline=self.today,
                                  scope="Restore stalled vendor retries", review_on=self.today),
                    {"type": "signal", "initiative": incident, "source": "Incident bridge log, entry 8",
                     "observed_on": self.today, "summary": "Upload retries still fail for accounts in one region."})

        due = ("--product", "example", "--due")
        outputs = {}
        for style in ("json", "csv", "markdown"):
            clean = self.cli("backlog", *due, "--format", style, capture_result=True)
            self.assertIn(incident, clean.stdout)
            self.assertIn("needs-triage: Incident bridge log, entry 8", clean.stdout)
            self.assertEqual(clean.stderr, "")
            outputs[style] = clean.stdout
        self.assertEqual([row["id"] for row in json.loads(outputs["json"])], [incident])

        advance = self.decision("start-delivery", delivery="https://example.com/delivery/43")
        proposal = self.preview(advance)
        signed = self.ledger.read_bytes()
        path = self.work / self.brief
        original = path.read_text()
        path.write_text(original.replace("account reminders", "billing reminders"))
        stale = "differs from the reviewed revision"
        issue = f"Review issue: {self.i}: {self.brief} {stale}\n"

        for command in (("backlog",), ("action", "portfolio", "backlog", "show")):
            for style, expected in outputs.items():
                with self.subTest(command=command, style=style):
                    result = self.cli(*command, *due, "--format", style, capture_result=True)
                    self.assertEqual(result.stdout, expected)
                    self.assertEqual(result.stderr, issue)

        other_area = self.cli("backlog", *due, "--area", "imports", capture_result=True)
        self.assertEqual((other_area.stdout, other_area.stderr), (outputs["json"], ""))
        affected_area = self.cli("backlog", "--due", "--area", renewals, capture_result=True)
        self.assertEqual((json.loads(affected_area.stdout), affected_area.stderr), ([], issue))
        self.cli("action", "portfolio", "roadmap", "show", "--product", "example", error=stale)
        self.cli("backlog", "--product", "example", error=stale)
        self.cli("check", error=stale)
        self.preview(advance, error=stale)
        self.apply(proposal, error=stale)
        self.assertEqual(self.ledger.read_bytes(), signed)

        path.write_text(original)
        restored = self.cli("backlog", *due, capture_result=True)
        self.assertEqual((restored.stdout, restored.stderr), (outputs["json"], ""))
        self.ledger.write_bytes(signed.replace(b"Renewal delays", b"Direct write attempt"))
        self.cli("backlog", *due, error="does not match the reviewed revision")

    def test_duplicates_backlog_limits_and_review_triggers(self):
        self.new("discovery-brief", self.discovery, error="Register the initiative")
        self.submit(self.setup_event(max_open=1, max_discovery=0), self.capture())
        alternate = f"{self.product_id}/exports"
        self.preview(self.capture(alternate, title="Renewal delays!"), error="Possible duplicate title")
        self.preview(self.capture(alternate, title="Exports"), error="Source already captured")
        self.preview(self.capture(alternate, title="Exports", source="Different source"), error="Open backlog limit exceeded")
        self.submit(self.decision("defer", revisit=self.today))
        self.assertEqual(json.loads(self.cli("backlog", "--due"))[0]["id"], self.i)
        self.assertEqual(json.loads(self.cli("backlog")), [])
        self.assertEqual(json.loads(self.cli("backlog", "--all-phases"))[0]["id"], self.i)
        self.assertEqual(json.loads(self.cli("backlog", "--phase", "deferred"))[0]["id"], self.i)
        self.submit(self.capture(alternate, title="Exports", source="Different source"))
        self.preview(self.decision("reopen"), error="Open backlog limit exceeded")
        self.submit(self.decision("decline", alternate), self.decision("reopen"), self.describe())
        self.new("discovery-brief", self.discovery)
        self.fill(self.discovery, {
            "Known, assumed, and unknown": "The reminder process is unclear.",
            "Learning goals and exit criteria": "Find the timing issue.",
            "Approach and timebox": "Run interviews this week.",
            "Capacity and review": "Review the next decision with the PM.",
            "Sources": "Research outline.",
        }, complete=False)
        self.preview(self.evidence()[0], self.decision("start-discovery", review_on=self.today), error="Active discovery limit")
        self.submit(self.decision("defer", revisit="When the EU pilot opens"))
        self.assertEqual(self.trace()["initiative"]["phase"], "deferred")
        self.assertEqual(json.loads(self.cli("backlog", "--due")), [])
        self.cli("check")

    def test_evaluate_cites_existing_signals_and_accepts_explicit_unknowns(self):
        self.submit(self.setup_event(), self.capture())
        schema = json.loads(self.cli("initiative", "schema"))
        evaluate = self.decision("evaluate")
        self.assertEqual(set(evaluate["evaluation"]), set(schema["evaluation_fields"]))
        field_types = set(schema["formats"]) | set(schema["allowed_values"]) | {"evaluation"}
        for sections in ("fields_by_type", "extra_fields_by_decision"):
            for fields in schema[sections].values():
                self.assertFalse(set(fields.values()) - field_types)
        assessment = {**evaluate["evaluation"], "sources": ["Support ticket #12"]}
        self.preview({**evaluate, "evaluation": "Looks promising"}, error="evaluation needs")
        self.preview({**evaluate, "evaluation": {**assessment, "unknowns": None}}, error="missing evidence or assessment")
        self.preview({**evaluate, "evaluation": {**assessment, "sources": ["Other initiative"]}},
                     error="Unknown signal source in this initiative")
        self.submit({**evaluate, "evaluation": assessment})
        signal = {"type": "signal", "initiative": self.i, "source": "Renewal audit, row 3",
                  "observed_on": self.today, "summary": "The missed renewal falls in the current quarter."}
        updated = {**assessment, "urgency": "Renewal falls this quarter", "unknowns": None,
                   "sources": [*assessment["sources"], signal["source"]]}
        self.submit(signal, {**evaluate, "evaluation": updated})
        decisions = self.trace()["initiative"]["decisions"]
        self.assertEqual([d["evaluation"] for d in decisions], [assessment, updated])
        self.assertEqual(len(json.loads(self.cli("backlog"))), 1)

    def test_signed_legacy_evaluation_can_be_reassessed(self):
        self.submit(self.setup_event(), self.capture())
        old = self.decision("evaluate", evaluation="Review the value of earlier reminders.")
        envelope = json.loads(self.ledger.read_text())
        envelope["record"]["events"].append(old)
        self.write_legacy_register(envelope["record"])
        self.assertEqual(self.trace()["initiative"]["decisions"], [old])
        self.submit(self.decision("evaluate"))
        self.assertEqual(self.trace()["initiative"]["decisions"][0], old)

    def test_changing_a_teams_working_fields_preserves_the_approved_plan(self):
        self.submit(self.setup_event(), self.capture(), self.describe(), self.metric(), self.target(),
                    self.decision("evaluate"), self.decision("prepare-brief"))
        self.brief_ready()
        self.submit(self.decision("approve-initiative"))
        self.submit(self.cycle(), self.plan())
        originals = {p: p.read_bytes() for p in (self.ledger, self.work / self.planning, self.work / self.brief)}
        def change(config, values, error=None):
            current = json.loads(self.cli("customize", "show"))
            return self.cli("customize", "apply", value={"revision": current["revision"], "config": config,
                            "values": [{"product": "example", "id": self.i, "field": k, "value": v}
                                       for k, v in values.items()]}, error=error)
        def field(label, kind, **options):
            return {"label": label, "type": kind, **options}
        fields = {
            "x-confidence": field("Confidence", "choice", choices=["High", "Low"]),
            "x-priority": field("MoSCoW", "choice", choices=["Must", "Could", "Won’t this time"]),
            "x-size": field("Story points", "number"), "x-votes": field("Votes", "number"),
            "x-milestone": field("Contract date", "date"), "x-teams": field("Dependencies", "multiple", choices=["Billing", "Mobile"]),
            "x-notes": field("What we heard", "text"), "x-rollout": field("Rollout percentage", "number")}
        change({"fields": fields, "views": {"internal": {"columns": ["rank", "effort", "horizon", *fields]},
                                            "customer": {"columns": ["title", "x-milestone"]}}},
               {"x-confidence": "Low", "x-priority": "Won’t this time", "x-size": 8, "x-votes": 0,
                "x-rollout": 0, "x-teams": ["Mobile", "Billing"], "x-notes": "Signal | A\n二次確認"})
        def row(name):
            return json.loads(self.cli("roadmap", "--product", "example", "--view", name))[0]
        initial = row("internal")
        self.assertEqual((initial["rank"], initial["effort"], initial["horizon"]), (1, 3, "now"))
        self.assertEqual((initial["x-size"], initial["x-votes"], initial["x-milestone"]), (8, 0, None))
        self.assertEqual(initial["x-teams"], ["Mobile", "Billing"])
        self.assertEqual(initial["x-notes"], "Signal | A\n二次確認")
        change({}, {"x-votes": None})
        self.assertIsNone(row("internal")["x-votes"])
        change({}, {"x-votes": 0, "x-rollout": 0})
        health = {"x-health": field("Health", "choice", choices=["On track", "At risk", "Off track"])}
        change({"fields": health}, {"x-health": "On track"})
        prior = json.loads(self.cli("customize", "show"))["revision"]
        change({}, {"x-health": "At risk"})
        self.cli("customize", "apply", value={"revision": prior, "values": [
            {"product": "example", "id": self.i, "field": "x-health", "value": "Off track"}]}, error="Reload")
        self.assertEqual(json.loads(self.cli("customize", "show"))["values"]["example"][self.i]["x-health"], "At risk")
        # A change in scoring model must convert existing data in the same transaction.
        original_state = (self.work / "customizations/settings.json").read_bytes()
        change({"fields": {"x-confidence": {"type": "number"}}}, {}, error="Invalid number value")
        self.assertEqual((self.work / "customizations/settings.json").read_bytes(), original_state)
        change({"fields": {"x-confidence": {"type": "number"}}},
               {"x-confidence": 50, "x-rollout": 25, "x-milestone": "2028-02-29"})
        change({}, {"x-milestone": "2027-02-29", "x-rollout": 100}, error="Invalid date value for Contract date")
        self.assertEqual(row("internal")["x-rollout"], 25)
        self.assertEqual(row("customer"), {"title": "Renewal delays", "x-milestone": "2028-02-29"})
        self.assertEqual(row("internal")["x-confidence"], 50)
        self.assertEqual({p: p.read_bytes() for p in originals}, originals)

    def test_planning_checks_rank_and_capacity_across_initiatives(self):
        other_id = f"{self.product_id}/exports"
        self.submit(self.setup_event(), self.metric())
        for identifier, title in [(self.i, "Renewals"), (other_id, "Exports")]:
            self.submit(self.capture(identifier, title=title, source=f"Source for {title}"),
                        self.describe(identifier, problem=f"Blocked workflow for {title}"),
                        self.target(identifier), self.decision("evaluate", identifier),
                        self.decision("prepare-brief", identifier))
            subject = identifier.split("/")[1]
            self.brief_ready(f"workspace/initiatives/example/{subject}/initiative-brief.md")
            self.submit(self.decision("approve-initiative", identifier))
        cycle = self.cycle(capacity=4, options=[self.i, other_id])
        one_option = {**cycle, "options": [self.i]}
        self.preview(one_option, self.plan(other_id, rank=1), error="each cycle option exactly once")
        comparison = records.section((self.work / self.planning).read_text(), "Comparison")
        self.fill(self.planning, {"Comparison": "\n".join(line for line in comparison.splitlines() if other_id not in line)})
        self.preview(one_option, self.plan(other_id, rank=1), error="did not compare this initiative")
        self.fill(self.planning, {"Comparison": comparison})
        self.submit(cycle, self.plan())
        self.preview(self.plan(other_id, rank=1, effort=1), error="rank is already occupied")
        self.preview(self.plan(other_id, rank=2, effort=2), error="capacity exceeded")
        previous_approval = self.trace()["initiative"]["initiative_brief"]
        self.submit(self.decision("unplan"), self.plan(other_id, rank=1, effort=4))
        self.assertEqual(self.trace()["initiative"]["phase"], "candidate")
        self.assertEqual(self.trace()["initiative"]["initiative_brief"], previous_approval)
        self.assertEqual([row["id"] for row in json.loads(self.cli("backlog"))], [self.i])
        self.assertEqual(len(json.loads(self.cli("backlog", "--all-phases"))), 2)
        self.submit(self.decision("unplan", other_id), self.plan())
        self.assertEqual(json.loads(self.cli("roadmap"))[0]["id"], self.i)
        self.submit(self.decision("defer", revisit="When capacity opens"), self.plan(other_id, rank=1, effort=4))
        self.assertEqual(json.loads(self.cli("roadmap"))[0]["id"], other_id)
        self.cli("check")

    def test_brief_parent_is_automatic_and_swapped_or_unbound_briefs_fail_review(self):
        other = self.product_id + "/secondary"
        self.submit(self.setup_event(), self.capture(), self.capture(other, "Secondary problem", "Support 25"),
                    self.describe(), self.metric(), self.target(), self.evidence()[0], self.decision("evaluate"))
        first = self.work / self.discovery
        second_path = self.discovery.replace("/renewal/", "/secondary/")
        self.new("discovery-brief", self.discovery)
        self.new("discovery-brief", second_path)
        second = self.work / second_path
        self.assertEqual(records.section(first.read_text(), "Parent initiative").strip(), self.i)
        self.assertEqual(records.section(second.read_text(), "Parent initiative").strip(), other)
        self.assertNotEqual(records.work_state(first.read_text())[0]["ID"], self.i)
        self.fill(self.discovery, {
            "Known, assumed, and unknown": "Renewal delays are reported. Frequency is unknown.",
            "Learning goals and exit criteria": "Determine whether reminders affect renewal timing.",
            "Approach and timebox": "Pilot notifications with two consenting customers this week.",
            "Capacity and review": "Research reviews the results on Friday.",
            "Sources": "Support ticket 12",
        }, complete=False)
        start = self.decision("start-discovery", review_on=self.today)
        original, sibling = first.read_text(), second.read_text()
        first.write_text(sibling)
        second.write_text(original)
        self.cli("check", error="set the '## Parent initiative' section")
        self.preview(start, error=f"registered ID {self.i}")
        first.write_text(original)
        second.write_text(sibling)
        self.preview(start)

        self.submit(self.decision("prepare-brief"))
        self.brief_ready()
        brief = self.work / self.brief
        original = brief.read_text()
        self.assertEqual(records.section(original, "Parent initiative").strip(), self.i)
        brief.write_text(original.replace("## Parent initiative\n\n" + self.i + "\n", ""))
        approval = self.decision("approve-initiative")
        self.preview(approval, error=f"set the '## Parent initiative' section to the registered ID {self.i}")
        brief.write_text(original)
        self.submit(approval)
        brief.write_text(original.replace(self.i, other))
        self.assertTrue(any("Parent initiative" in issue for issue in self.trace()["review_issues"]))

    def test_rejects_wrong_relationships_and_forged_writes_in_hooks(self):
        (self.work / self.product_context).write_text(
            (self.work / self.product_context).read_text().replace("company/overview.md", "company/missing.md")
        )
        self.preview(self.setup_event(), error="must link to the registered company")
        (self.work / self.product_context).write_text(
            (self.work / self.product_context).read_text().replace("company/missing.md", "company/overview.md")
        )
        self.submit(self.setup_event())
        self.preview(self.capture("product-context-different/renewal"), error="registered product context ID")
        self.submit(self.capture())
        for config_path in (".codex/hooks.json", ".claude/settings.json"):
            with self.subTest(config=config_path):
                config = json.loads((self.root / config_path).read_text())
                command = config["hooks"]["PreToolUse"][0]["hooks"][0]
                args = command["command"] if "args" not in command else [command["command"], *command["args"]]
                for path in ("workspace/backlogs/example/initiatives.json", ".oryx-approvals/example.json"):
                    with self.subTest(path=path):
                        payload = {"hook_event_name": "PreToolUse", "cwd": str(self.work),
                                   "tool_name": "apply_patch", "tool_input": {
                                       "command": f"*** Begin Patch\n*** Update File: {path}\n*** End Patch"}}
                        result = subprocess.run(args, shell=isinstance(args, str), cwd=self.work, env=self.env,
                                                input=json.dumps(payload), capture_output=True, text=True)
                        self.assertEqual(result.returncode, 0, result.stderr)
                        guidance = json.loads(result.stdout)["hookSpecificOutput"]
                        self.assertEqual(guidance["permissionDecision"], "deny")
                        self.assertIn("initiative propose", guidance["permissionDecisionReason"])
        self.cli("check")

    def test_urgent_delivery_still_requires_explicit_evidence_and_approval(self):
        self.submit(self.setup_event(max_discovery=0), self.capture())
        urgent = self.decision("expedite", delivery="https://example.com/incident", owner="Incident commander",
                               obligation="Sustained service outage", deadline=self.today,
                               scope="Restore availability", review_on=self.today)
        self.preview({**urgent, "owner": "unknown"}, error="decision.owner needs text")
        proposal = self.preview(urgent)
        self.assertEqual(self.trace()["initiative"]["phase"], "inbox")
        self.apply(proposal)
        self.assertEqual(self.trace()["initiative"]["phase"], "delivery")
        self.assertEqual(json.loads(self.cli("roadmap")), [])
        self.submit(self.ship_without_checklist())
        self.cli("check")

    def test_system_check_catches_drift_in_sourced_view_template(self):
        template = self.root / "templates/views/roadmap.json"
        data = json.loads(template.read_text())
        del data["columns"]["horizon"]
        template.write_text(json.dumps(data))
        self.cli("check", "--system-only", error="Invalid roadmap view template")

    def test_close_obsolete_deferred_work_with_a_full_backlog(self):
        other = f"{self.product_id}/billing"
        self.submit(self.setup_event(max_open=1, max_discovery=0), self.capture(),
                    self.decision("defer", revisit=self.today),
                    self.capture(other, "Billing errors", "Support ticket B-12"))
        self.submit(self.decision("decline", reason="The customer retired the legacy renewal process."))
        item = self.trace()["initiative"]
        self.assertEqual(item["phase"], "declined")
        self.assertEqual([entry["action"] for entry in item["decisions"]], ["defer", "decline"])
        self.assertEqual(json.loads(self.cli("backlog", "--due")), [])
        self.assertEqual(json.loads(self.cli("backlog", "--phase", "inbox"))[0]["id"], other)

    def test_cycle_requires_the_reviewed_candidates_and_their_current_approval(self):
        self.submit(self.setup_event(), self.capture(), self.describe(), self.metric(), self.target())
        cycle = self.cycle()
        self.preview(cycle, error="must be an approved candidate")
        self.submit(self.decision("evaluate"), self.decision("prepare-brief"))
        self.brief_ready()
        self.submit(self.decision("approve-initiative"))
        table = "| Initiative ID | Assessment |\n| --- | --- |\n"
        row = f"| {self.i} | Renewals would benefit before year-end. |\n"
        for body, error in [
            ("Adopt the new workflow.", "table columns must be"),
            (table + row + row, "each cycle option exactly once"),
            (table + row.replace(self.i, self.product_id + "/different"), "each cycle option exactly once"),
            (table + f"| {self.i} | TBD |", "Add an assessment"),
        ]:
            with self.subTest(error=error):
                self.fill(self.planning, {"Comparison": body})
                self.preview(cycle, error=error)
        self.fill(self.planning, {"Comparison": table + row + "\nExisting support commitments consume one week."})
        self.submit(cycle)
        self.submit(self.decision("reopen"), self.decision("prepare-brief"))
        self.fill(self.brief, {"Approach and scope": "Expand the pilot to every account."})
        self.submit(self.decision("approve-initiative"))
        self.preview(self.plan(), error="new comparison for the current Initiative Brief")
        self.assertEqual(self.trace()["initiative"]["phase"], "candidate")

    def test_approved_comparison_recovers_with_its_register(self):
        self.submit(self.setup_event(), self.capture(), self.describe(), self.metric(), self.target())
        self.submit(self.decision("evaluate"), self.decision("prepare-brief"))
        self.brief_ready()
        self.submit(self.decision("approve-initiative"))
        cycle = self.cycle()
        comparison = self.work / self.planning
        text = comparison.read_text(encoding="utf-8")
        comparison.unlink()
        store = pm.initiative_store
        changes = [cycle, self.plan()]
        proposal, _, _, _ = store.prepare(
            self.root, "example", changes, comparison_drafts={self.planning: text})
        self.assertFalse(comparison.exists())
        replace = store.storage.replace_text

        def interrupted(target, *args, **kwargs):
            if target == comparison:
                raise OSError("Interrupted comparison before publication")
            return replace(target, *args, **kwargs)

        with patch.object(store.storage, "replace_text", interrupted):
            with self.assertRaisesRegex(ValueError, "Interrupted comparison"):
                store.apply(self.root, "example", proposal, approved_revision=proposal["revision"],
                            comparison=(comparison, None, text))
        self.assertFalse(comparison.exists())
        comparison.write_text("Intervening PM edit\n")
        self.cli("initiative", "recover", "example", error="comparison changed")
        self.assertEqual(comparison.read_text(), "Intervening PM edit\n")
        comparison.unlink()
        self.cli("initiative", "recover", "example")
        self.assertEqual(comparison.read_text(), text)
        self.assertEqual(len(json.loads(self.cli("roadmap", "--cycle", "quarter-two"))), 1)
        self.cli("initiative", "recover", "example")
        self.assertEqual(comparison.read_text(), text)

    def test_replay_prior_signed_cycle_with_a_narrative_comparison(self):
        self.submit(self.setup_event(), self.capture())
        cycle = self.cycle()
        self.fill(self.planning, {"Comparison": "Explore renewal timing ahead of regional expansion."})
        reference = pm.initiative_store.doc_reference(self.root, self.planning, "prioritization")
        envelope = json.loads(self.ledger.read_text())
        envelope["record"]["events"].append({**cycle, "references": reference})
        self.write_legacy_register(envelope["record"])
        self.assertEqual(json.loads(self.cli("initiative", "show", "example"))["cycles"], ["quarter-two"])
        self.cli("check")
