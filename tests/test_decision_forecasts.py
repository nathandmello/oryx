"""Forecast ownership, dated evidence and retry behavior in disposable private workspaces."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import date, timedelta
import json
import os
import subprocess
import sys
from unittest.mock import patch
import unittest

import test_pm
from onboarding_fixtures import reviewed_studio
import test_opportunities
import decision_authority
import decision_forecasts as forecasts
import initiative_events


class ForecastTests(unittest.TestCase):
    def setUp(self):
        hub = test_pm.HubTests()
        self.addCleanup(hub.doCleanups)
        hub.setUp()
        self.root, self.private = hub.root, hub.work
        reviewed_studio(self.root, self.private)
        self.name = "context/products/billing/overview.md"
        hub.context_record()
        self.record = hub.context_record("product-context", self.name, "[Company](../../company/overview.md)")
        self.today = date.today().isoformat()
        self.tomorrow = (date.today() + timedelta(days=1)).isoformat()
        self.later = (date.today() + timedelta(days=3)).isoformat()
        self.source = self.record.parent / "sources" / "minutes.txt"
        self.source.parent.mkdir(exist_ok=True)
        self.source.write_text("Renewal reminders stay manual until the pilot ends.\n")
        self.row = f"| Who sends reminders? | Billing pilot | Mira, {self.today} | Keep manual reminders. [S1] | Measure renewal rate. |"
        content = self.record.read_text().replace("Fixture PM, fixture discussion", "[Pilot minutes](sources/minutes.txt)")
        heading = "## Decisions already closed\n\n| Question | Scope | Person and date | Evidence | Next step |\n"
        self.record.write_text(content.replace("## Context controls", heading + "| --- | --- | --- | --- | --- |\n" + self.row +
                                              "\n\n## Context controls"))

    def authority(self):
        return decision_authority.context(self.private, self.name)[0]["decision"]

    def request(self):
        return {"operation": "create", "decision": self.authority(), "event": "Renewals exceed 80% in the pilot",
                "probability": 75, "made_on": self.today, "resolve_on": self.later,
                "criterion": "Use paid renewals divided by eligible pilot renewals at quarter close."}

    def test_public_readers_after_restore_and_studio_alignment(self):
        def cli(*args, data=None):
            run = subprocess.run([sys.executable, str(self.root / "tools/pm.py"), *args], cwd=self.root,
                                 input=json.dumps(data), text=True, capture_output=True)
            self.assertEqual(run.returncode, 0, run.stderr + run.stdout)
            return json.loads(run.stdout)

        metric = cli("metric", "set", "company.mrr", "--write", data={
            "approved_by": "Finance", "source": "Approved revenue policy", "effective_on": self.today,
            "changes": {"formula": "Sum eligible recurring invoice lines."}})["proposed"]
        forecast = cli("forecast", "preview", data=self.request())
        cli("forecast", "apply", data=forecast)
        expected = cli("forecast", "list")
        skill_name = "customizations/samples/context/products/billing/overview.md"
        skill = self.private / skill_name
        skill.parent.mkdir(parents=True)
        skill.write_text(self.record.read_text().replace("Keep manual reminders.", "Conjure personal canary."))
        before = {p.relative_to(self.private): p.read_bytes() for p in [
            skill, self.record, self.source, self.private / "context/metrics.json",
            self.private / "workspace/forecasts" / (expected[0]["id"] + ".json")]}
        actual = self.private
        for alias in ("private", "workspace", "studio"):
            if alias == "studio":
                cli("align")
            else:
                actual.rename(self.root / alias)
            actual = self.root / alias
            with self.subTest(root=alias):
                self.assertEqual(cli("metric", "show", "company.mrr", "--product", "billing"), metric)
                self.assertEqual(cli("forecast", "list", "--product", "billing"), expected)
                decisions = cli("forecast", "decisions", "--context", self.name)
                self.assertEqual(decisions[0]["decision"], expected[0]["decision"])
                self.assertIn(self.name, {row["record"] for row in cli("catalog")})
                self.assertNotIn(skill_name, {row["record"] for row in cli("catalog")})
                prompt = f"Review {alias}/workspace/roadmaps/billing/q4.md and the renewal decision."
                context = cli("task-context", prompt)
                self.assertEqual(context["scope"]["product"], "billing")
                self.assertIn("Keep manual reminders.", str(context["entries"]))
                self.assertNotIn("personal canary", str(context))
                example = cli("task-context", f"Read {alias}/{skill_name}.")
                self.assertFalse(example["scope"])
                spaced = f'{alias}/customizations/Friday sketches/context/products/billing/overview.md'
                self.assertFalse(cli("task-context", f'Read "{spaced}".')["scope"])
                self.assertTrue(all((actual / rel).read_bytes() == contents for rel, contents in before.items()))

    def test_personal_workflow_is_not_forecast_evidence(self):
        method = self.private / "customizations/skills/billing/SKILL.md"
        method.parent.mkdir(parents=True)
        method.write_bytes(self.source.read_bytes())
        self.record.write_text(self.record.read_text().replace("](sources/minutes.txt)", "](" +
                              os.path.relpath(method, self.record.parent) + ")"))
        run = subprocess.run([sys.executable, str(self.root / "tools/pm.py"), "forecast", "decisions",
                              "--context", self.name], cwd=self.root, text=True, capture_output=True)
        self.assertNotEqual(run.returncode, 0)
        self.assertIn("Cite the underlying decision evidence", run.stdout)
        lookup = subprocess.run([sys.executable, str(self.root / "tools/pm.py"), "task-context", "--product",
                                 "billing", "How do we handle renewal reminders?"], cwd=self.root,
                                check=True, text=True, capture_output=True)
        self.assertNotIn("Keep manual reminders.", str(json.loads(lookup.stdout)["entries"]))
        capture = {"sources": [{"reference": "[Method](customizations/skills/billing/SKILL.md)",
                                "date": self.today, "coverage": "read", "checked_on": self.today}], "entries": []}
        preview = subprocess.run([sys.executable, str(self.root / "tools/pm.py"), "route-context"],
                                 input=json.dumps(capture), cwd=self.root, text=True, capture_output=True)
        self.assertNotEqual(preview.returncode, 0)
        self.assertIn("Cite the underlying evidence", preview.stdout)

    def test_revision_preserves_original_and_sourced_resolution_scores_it(self):
        request = self.request()
        proposal = forecasts.preview(self.root, request)
        self.assertEqual(forecasts.list_records(self.private), [])
        first = forecasts.apply(self.root, proposal)
        identifier = first["id"]
        changed = {**request, "probability": 60}
        with self.assertRaisesRegex(ValueError, "separate revision"):
            forecasts.preview(self.root, changed)
        local_source = self.source.relative_to(self.private).as_posix()
        revise = {"operation": "revise", "id": identifier, "probability": 60, "on": self.tomorrow,
                  "evidence": {"source": local_source, "quote": "Fewer accounts renewed.", "observed_on": self.tomorrow}}
        self.source.write_text("Fewer accounts renewed.\n")
        with patch.object(forecasts, "today", return_value=self.tomorrow):
            revision = forecasts.preview(self.root, revise)
            self.source.write_text("Fewer accounts renewed. Seven accounts canceled.\n")
            with self.assertRaisesRegex(ValueError, "source changed"):
                forecasts.apply(self.root, revision)
            revision = forecasts.preview(self.root, revise)
            forecasts.apply(self.root, revision)
        self.source.write_text("79 of 100 eligible pilot accounts renewed.\n")
        resolve = {"operation": "resolve", "id": identifier, "outcome": False, "on": self.later,
                   "evidence": {"source": local_source, "quote": "79 of 100 eligible pilot accounts renewed.",
                                "observed_on": self.later}}
        self.record.write_text(self.record.read_text().replace("Keep manual reminders.", "Superseded after the pilot."))
        with patch.object(forecasts, "today", return_value=self.later):
            with self.assertRaisesRegex(ValueError, "known binary"):
                forecasts.preview(self.root, {**resolve, "outcome": "inconclusive"})
            final = forecasts.preview(self.root, resolve)
            after = forecasts.apply(self.root, final)
            self.assertEqual(after, forecasts.apply(self.root, final))
            self.assertEqual(first, forecasts.apply(self.root, proposal))
            self.assertEqual(revision, forecasts.preview(self.root, revise))
            self.assertEqual([], forecasts.check_workspace(self.private))
            data = forecasts.list_records(self.private)[0]
            self.assertEqual((75, 60, False, 0.5625), (data["probability"], data["revisions"][0]["probability"],
                                                      data["resolution"]["outcome"], data["resolution"]["score"]))

    def test_current_authority_and_clean_retries(self):
        request = self.request()
        preview = forecasts.preview(self.root, request)
        self.source.write_text("Corrected pilot minutes.\n")
        with self.assertRaisesRegex(ValueError, "changed"):
            forecasts.apply(self.root, preview)
        preview = forecasts.preview(self.root, self.request())
        fake = deepcopy(preview)
        fake["forecast"]["criterion"] += " lower threshold"
        with self.assertRaisesRegex(ValueError, "fresh preview"):
            forecasts.apply(self.root, fake)
        future_request = forecasts.request_for(preview["forecast"])
        with ThreadPoolExecutor(max_workers=2) as workers:
            results = list(workers.map(lambda _: forecasts.apply(self.root, preview), range(2)))
        self.assertEqual(results[0], results[1])
        path = forecasts.target_for(self.private, results[0]["id"])
        original = path.read_bytes()
        self.assertEqual(preview, forecasts.preview(self.root, future_request))
        self.assertEqual(original, path.read_bytes())
        self.record.write_text(self.record.read_text().replace("[S1] |", "[S1] *(Superseded by [S1])* |"))
        self.assertEqual([], decision_authority.context(self.private, self.name))
        self.assertEqual(results[0], forecasts.apply(self.root, preview))

    def test_invalid_authority_and_denied_publication(self):
        req = self.request()
        with self.assertRaisesRegex(ValueError, "missing, ambiguous"):
            forecasts.preview(self.root, {**req, "decision": {**req["decision"], "artifact_id": "other-product"}})
        proposal = forecasts.preview(self.root, req)
        with patch("storage.replace_text", side_effect=PermissionError("read-only workspace")):
            with self.assertRaises(PermissionError):
                forecasts.apply(self.root, proposal)
        self.assertEqual([], forecasts.list_records(self.private))
        self.record.write_text(self.record.read_text().replace(f"| {self.today} | {self.today} |",
                                                              f"| undated | {self.today} |"))
        self.assertEqual([], decision_authority.context(self.private, self.name))

    def test_ambiguous_decision_and_changed_private_history(self):
        proposal = forecasts.preview(self.root, {**self.request(), "probability": 62.5})
        result = forecasts.apply(self.root, proposal)
        # Two active outcomes against the same question and scope cannot confer authority.
        conflict = self.row.replace("Keep manual reminders.", "Automate all reminders.")
        self.record.write_text(self.record.read_text().replace(self.row, self.row + "\n" + conflict))
        with self.assertRaisesRegex(ValueError, "repeated active decisions"):
            self.authority()
        target = forecasts.target_for(self.private, result["id"])
        saved = json.loads(target.read_text())
        saved["forecast"]["probability"] = 90
        target.write_text(json.dumps(saved))
        self.assertIn("differs from its saved revision", forecasts.check_workspace(self.private)[0])

    def test_redirected_evidence_and_forecast_file_rejected(self):
        proposal = forecasts.preview(self.root, self.request())
        identifier = forecasts.apply(self.root, proposal)["id"]
        path = forecasts.target_for(self.private, identifier)
        copy = path.with_suffix(".copy")
        path.rename(copy)
        try:
            path.symlink_to(copy)
        except OSError:
            self.skipTest("Symlinks unavailable")
        with self.assertRaisesRegex(ValueError, "regular files"):
            forecasts.read(self.private, identifier)
        self.source.unlink()
        self.source.symlink_to(self.record)
        with self.assertRaisesRegex(ValueError, "redirected source"):
            self.authority()

    def test_legacy_forecast_survives_new_source_coverage(self):
        request = self.request()
        preview = forecasts.preview(self.root, request)
        archive = preview["forecast"]
        source = archive["authority"]["sources"][0]
        self.assertEqual(source.pop("coverage"), "unrecorded")
        self.assertEqual(forecasts.fingerprint({k: v for k, v in archive["authority"].items() if k != "owner_revision"}),
                         archive["decision"]["digest"])
        # Write the earlier release's format, without coverage metadata.
        old = forecasts.receipt(None, archive)
        path = forecasts.target_for(self.private, archive["id"])
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"forecast": archive, "revision": old["revision"]}))
        before = path.read_bytes()
        self.record.write_text(self.record.read_text().replace("## Work state",
                               f"<!-- source-coverage:S1:partial:{self.today} -->\n\n## Work state"))
        row, = decision_authority.context(self.private, self.name)
        self.assertEqual(row["authority"]["sources"][0]["coverage"], "partial")
        self.assertEqual(row["decision"], archive["decision"])
        self.assertEqual(forecasts.preview(self.root, request), old)
        self.assertEqual(forecasts.apply(self.root, old)["id"], archive["id"])
        self.assertEqual(forecasts.list_records(self.private), [archive])
        self.assertEqual(path.read_bytes(), before)

    def test_cross_scope_conflict_is_visible_on_confirmation_and_preserved(self):
        request = self.request()
        before = forecasts.preview(self.root, request)
        company = self.private / "context/company/overview.md"
        header = self.record.read_text().split("## Decisions already closed")[1].split(self.row)[0]
        conflict = self.row.replace("Mira,", "Legal,").replace("Keep manual reminders.", "Manual reminders require Legal permission.")
        company.write_text(company.read_text().replace("## Context controls",
                           "## Decisions already closed" + header + conflict + "\n\n## Context controls"))
        updated = forecasts.preview(self.root, request)
        self.assertEqual(before["forecast"]["decision"], updated["forecast"]["decision"])
        advisory, = updated["forecast"]["authority"]["advisories"]
        self.assertEqual((advisory["record"], advisory["state"]), (self.name, "open"))
        with self.assertRaisesRegex(ValueError, "fresh preview"):
            forecasts.apply(self.root, before)
        forecasts.apply(self.root, updated)
        company.write_text(company.read_text().replace("Manual reminders require Legal permission.", "Keep manual reminders."))
        current, = decision_authority.context(self.private, self.name)
        self.assertNotIn("advisories", current["authority"])
        saved, = forecasts.list_records(self.private)
        self.assertEqual(saved["authority"]["advisories"], [advisory])
        self.assertEqual(saved["probability"], 75)

    def test_competing_reviews_and_invalid_dates(self):
        root = self.root
        proposal = forecasts.preview(root, self.request())
        identifier = forecasts.apply(root, proposal)["id"]
        req = {"operation": "revise", "id": identifier, "on": self.today, "probability": 30,
               "evidence": {"source": "https://example.org/observations/2", "quote": "We received three orders.",
                            "observed_on": self.today}}
        a, b = forecasts.preview(root, req), forecasts.preview(root, {**req, "probability": 45})
        forecasts.apply(root, a)
        with self.assertRaisesRegex(ValueError, "fresh preview"):
            forecasts.apply(root, b)
        with self.assertRaisesRegex(ValueError, "after the resolution date"):
            forecasts.preview(root, {**{k: v for k, v in req.items() if k != "probability"},
                                     "operation": "resolve", "outcome": True})


class SignedDecisionForecastTests(unittest.TestCase):
    def test_signed_rationale_is_bound_and_old_format_readable(self):
        h = test_opportunities.InitiativeTests()
        self.addCleanup(h.doCleanups)
        h.setUp()
        detail = {"choice": "Defer reminders", "alternatives": ["Run a low-volume pilot"], "owner": "Mira Chen",
                  "scope": "Billing renewal notices", "tradeoff": "The pilot delays tax work by one cycle",
                  "reopen_when": "Contact rate exceeds five percent"}
        event = h.decision("defer", revisit="After the next reporting cycle", rationale=detail)
        h.submit(h.setup_event(), h.capture())
        h.preview({**event, "rationale": {**detail, "alternatives": [detail["choice"]]}}, error="distinct credible")
        proposal = h.preview(event)
        accepted = proposal["reviewed_transactions"][0]
        self.assertNotIn("rationale", accepted)
        self.assertEqual(json.loads(accepted["reason"].split(" | Reviewed rationale: ")[1]), detail)
        initiative_events.validate_event(accepted, approved=True)
        self.assertEqual(detail, initiative_events.decision_rationale(accepted))
        self.assertEqual({}, initiative_events.decision_rationale({**accepted, "reason": "Signed reason"}))
        self.assertEqual({}, initiative_events.decision_rationale({**accepted, "reason": "Old | Reviewed rationale: {}"}))
        h.apply(proposal)
        with patch.dict(os.environ, h.env):
            entry = decision_authority.registered(h.root, "example", h.i)[0]
            request = {"operation": "create", "decision": entry["decision"], "probability": 70,
                       "event": "Contact rate exceeds five percent", "made_on": h.today,
                       "resolve_on": (date.today() + timedelta(days=12)).isoformat(),
                       "criterion": "Use the next billing cycle's closed contacts report"}
            forecast = forecasts.preview(h.root, request)
            self.assertEqual(entry["authority"], forecast["forecast"]["authority"])
            ledger = json.loads(h.ledger.read_text())
            ledger["record"]["events"][-1]["reason"] = "Unreviewed decision"
            h.ledger.write_text(json.dumps(ledger))
            with self.assertRaisesRegex(ValueError, "signature"):
                forecasts.apply(h.root, forecast)
