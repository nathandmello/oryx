"""Weekly PM review through the published actions and real signed records."""

from datetime import date, timedelta
import json
import os
import re
import unittest
from unittest.mock import patch

import test_opportunities

import decision_review
import initiative_events
import initiative_views


class WeeklyReviewTests(unittest.TestCase):
    def setUp(self):
        self.hub = test_opportunities.InitiativeTests()
        self.addCleanup(self.hub.doCleanups)
        self.hub.setUp()

    def scan(self, *arguments):
        return json.loads(self.hub.cli("action", "portfolio", "decisions", "review", *arguments))

    def test_claim_projection_preserves_signed_reason_and_legacy_words(self):
        event = self.hub.decision("evaluate")
        rationale = {"choice": "Review the renewal pilot", "alternatives": ["Pause the pilot"], "tradeoff": "Delay billing research",
                     "owner": "Renewals PM", "scope": "Renewal pilot", "reopen_when": "Two customers opt out"}
        signed = initiative_events.reviewed_rationale({**event, "rationale": rationale})
        approval = {"action": "evaluate", "scope": None, "obligation": None, "brief": None, "on": self.hub.today,
                    "source": event["source"], "reason": signed["reason"]}
        selection = {**approval, "comparison": {"path": "planning.md", "sha256": "prior revision"}}
        basis = {"approval": approval, "selection": selection}
        self.assertEqual([c["text"] for c in initiative_views.signal_claims(None, basis)], [event["reason"]] * 2)
        self.assertIn(initiative_events.RATIONALE_MARK, approval["reason"])
        approval["reason"] = "Signed wording | Reviewed rationale: a later explanation"
        self.assertEqual(initiative_views.signal_claims(None, basis)[0]["text"], approval["reason"])

    def test_signed_dates_cap_and_no_write(self):
        h = self.hub
        events = [h.setup_event(max_open=9)]
        for number in range(6):
            identifier = f"{h.product_id}/request-{number}"
            events.extend([h.capture(identifier, f"Request number {number}", f"Support log {number}"),
                           h.decision("defer", identifier, revisit=h.today)])
        h.submit(*events)
        before = h.ledger.read_bytes()
        result = self.scan("--product", "example")
        self.assertEqual(result, json.loads(h.cli("decision-review", "--product", "example")))
        self.assertEqual(len(result["findings"]), 5)
        self.assertIn(result["findings"][0]["subject"], result["next_check"])
        for row in result["findings"]:
            self.assertEqual(row["kind"], "decision-due")
            self.assertIn(h.ledger.relative_to(h.work).as_posix(), row["sources"])
        self.assertEqual(before, h.ledger.read_bytes())
        h.cli("decision-review", "--product", "unknown", error="Unknown review product")
        h.ledger.write_text(h.ledger.read_text().replace("Support log 0", "Changed locator"))
        h.cli("decision-review", error="signature")

    def test_new_observation_against_observable_trigger_and_hypothesis(self):
        h = self.hub
        h.submit(h.setup_event(), h.capture(), h.evidence()[0])
        self.assertEqual(self.scan()["findings"][0]["kind"], "unassessed-hypothesis")
        h.submit(h.decision("defer", revisit="Two enterprise accounts request renewal notices."))
        self.assertEqual(self.scan()["findings"], [])
        h.submit({"type": "signal", "initiative": h.i, "observed_on": h.today,
                  "source": "Enterprise interviews, item two", "summary": "Two accounts requested renewal reminders."})
        row = self.scan()["findings"][0]
        self.assertEqual(row["kind"], "possible-trigger")
        self.assertIn("Two enterprise accounts", row["finding"])
        self.assertIn("Enterprise interviews, item two", row["sources"])
        self.assertIn("Product review notes", row["sources"])
        h.submit(h.decision("reopen"))
        self.assertEqual([r["kind"] for r in self.scan()["findings"]], ["unassessed-hypothesis"])
        h.submit(h.decision("decline"))
        self.assertEqual(self.scan(), {"findings": [], "next_check": None})

    def test_quiet_hypothesis_uses_its_own_latest_dated_result(self):
        h = self.hub
        hypothesis, experiment, result, assessment = h.evidence()
        h.submit(h.setup_event(), h.capture(), h.metric(), hypothesis, experiment)
        h.submit(result, assessment)
        self.assertEqual(self.scan()["findings"], [])
        with patch.dict(os.environ, h.env), patch.object(decision_review, "date") as clock:
            clock.today.return_value = date.today() + timedelta(days=29)
            self.assertEqual(decision_review.review(h.root)["findings"], [])
            clock.today.return_value = date.today() + timedelta(days=30)
            row = decision_review.review(h.root)["findings"][0]
        self.assertEqual(row["kind"], "quiet-hypothesis")
        self.assertIn(result["source"], row["sources"])

    def test_six_week_decision_and_forecast_checks_preserve_the_original(self):
        h = self.hub
        day = (date.today() - timedelta(weeks=6)).isoformat()
        later = (date.today() + timedelta(days=3)).isoformat()
        h.submit(h.setup_event(), {**h.capture(), "observed_on": day},
                 h.decision("defer", on=day, revisit="Customer panel requests the feature."))
        decision = json.loads(h.cli("action", "review", "decision", "show", "--product", "example"))[0]["decision"]
        request = {"operation": "create", "decision": decision, "event": "Ten pilot customers renew",
                   "probability": 70, "made_on": day, "resolve_on": later,
                   "criterion": "Read the final total from the pilot renewal report."}
        preview = json.loads(h.cli("action", "review", "forecast", "preview", value=request))
        h.cli("action", "review", "forecast", "apply", value=preview)
        before = h.cli("forecast", "list")
        rows = self.scan("--product", "example")["findings"]
        self.assertEqual({row["kind"] for row in rows}, {"decision-age", "forecast-review"})
        self.assertEqual(h.cli("forecast", "list"), before)

    def test_context_conflict_keeps_sources_and_ignores_sibling_product(self):
        h = self.hub
        other = "context/products/unrelated/overview.md"
        h.cli("new", "product-context", other)
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        for path, label, step in [(h.company, "Policy", "Obtain legal clearance."),
                                  (h.product_context, "Launch notes", "Announce the launch today."),
                                  (other, "Sibling notes", "Send a private beta invitation.")]:
            target = h.work / path
            content = re.sub(r"(?m)^\| \{\{Question resolved.*$",
                             f"| Release gate? | EU export | PM, {yesterday} | {step} [S1] | {step} |", target.read_text())
            content = re.sub(r"(?m)^\| \{\{S1\}\}.*$", f"| S1 | {label} | {yesterday} | {yesterday} |", content)
            if path == h.product_context:
                content = content.replace("| Review by | event-driven |", f"| Review by | {yesterday} |")
                content = content.replace("## Constraints\n", "## Constraints\n\n- Assumption: Legal can review the launch this week. [S1]\n")
            target.write_text(content)
        result = self.scan("--product", "example")
        self.assertNotIn("Sibling notes", json.dumps(result))
        kinds = {row["kind"]: row for row in result["findings"]}
        self.assertEqual(set(kinds), {"possible-conflict", "stale-assumption", "context-decision-review"})
        self.assertEqual(set(kinds["possible-conflict"]["sources"]),
                         {h.company, h.product_context, "Policy", "Launch notes"})
        context = json.loads(h.cli("task-context", "--product", "example"))
        risk, = context["risks"]
        self.assertEqual({r["record"] for r in risk["claims"]}, {h.company, h.product_context})
        self.assertEqual(kinds["possible-conflict"]["risk_id"], risk["id"])
        scoped = json.loads(h.cli("task-context", "--product", "example", "Draft the EU export customer update"))
        offer = scoped["conversation"]["suggestion"]
        self.assertEqual(offer["source"], risk["id"])
        self.assertEqual(set(offer["sources"]), {h.company, h.product_context, "Policy", "Launch notes"})
        self.assertNotIn("Sibling notes", json.dumps(offer))
