"""Check guardrails, evidence eligibility and corrections through signed PM proposals."""

from datetime import date, timedelta
import json
from unittest import TestCase
from unittest.mock import patch

import test_outcome_reviews
import initiative_store


class OutcomeEvidenceTests(TestCase):
    def setUp(self):
        self.flow = test_outcome_reviews.OutcomeReviewTests()
        self.flow.setUp()
        self.addCleanup(self.flow.doCleanups)
        self.h = self.flow.hub
        self.metric = "renewal-rate"
        self.errors = "setup-errors"
        self.population = "Eligible pilot tenants"
        self.release = self.flow.release(self.metric)
        self.h.submit({**self.h.metric(), "metric": self.errors, "name": "Setup error rate",
                       "definition": "Eligible pilot tenants with setup failures"})

    def rule(self, **values):
        return {"type": "guardrail", "guardrail": "pilot-errors", "metric": self.errors, "initiative": self.h.i,
                "operator": "lt", "threshold": "2", "unit": "percent", "population": self.population,
                "basis": "day", "effective_on": self.release, "source": "Pilot rollout review, decision 12",
                "adopted_from": {"target": self.metric, "on": self.release, "source": "Pilot charter, item 8"}, **values}

    def reading(self, key, value, *, guard=False, observed=None, start=None, source=None, **obs_fields):
        observed = observed or self.h.today
        start = start or observed
        end = (date.fromisoformat(start) + timedelta(days=1)).isoformat()
        source = source or f"Fictional query export, version {key}"
        metric = self.errors if guard else self.metric
        obs = {"start": start, "end": end, "basis": "day", "unit": "percent", "definition": metric,
               "population": self.population, "timezone": "UTC", "complete": True, "source": source, **obs_fields}
        event = {"type": "measurement", "initiative": self.h.i, "measurement": key, "metric": metric,
                 "value": value, "observed_on": observed, "source": source, "observation": obs}
        if guard:
            event.update(type="guardrail-reading", guardrail="pilot-errors")
        return event

    def correction(self, key, replacement=None):
        event = {"type": "correct-measurement", "initiative": self.h.i, "measurement": key,
                 "reason": "Dashboard repeated internal tenants.", "source": "Audit query R-12, signed report"}
        if replacement:
            event["replacement"] = replacement
        return event

    def outcomes(self, status, *refs, disposition=None, follow=None):
        extra = {"guardrail_dispositions": {"pilot-errors": disposition}} if disposition else {}
        return self.flow.review({self.metric: self.flow.assessment(status, *refs)}, follow, **extra)

    def test_adoption_bounds_including_equality_upcoming_revision_and_gap(self):
        h = self.h
        follow = {"on": self.flow.tomorrow, "action": "Check the completed pilot cohort."}
        h.submit(self.outcomes("unmeasured", follow=follow))
        rule = self.rule()
        h.preview({k: v for k, v in rule.items() if k != "adopted_from"}, error="prior evidence")
        h.submit(rule)
        h.preview(self.outcomes("unmeasured"), error="pilot-errors is unavailable")
        h.submit(self.reading("under", "1.99", guard=True, observed=self.flow.yesterday))
        self.assertEqual(h.trace()["initiative"]["guardrail_results"]["pilot-errors"]["status"], "within")
        h.submit(self.reading("edge", "2.00", guard=True))
        self.assertIn("breached", h.cli("backlog", "--due", "--format", "markdown"))
        self.assertIn("breached", h.cli("backlog", "--due", "--format", "csv"))
        h.preview(self.outcomes("unmeasured"), error="pilot-errors is breached")
        h.preview(self.outcomes("met", "edge", disposition="Hold rollout and verify the error spike."),
                  error="different target")
        h.submit(self.outcomes("unmeasured", disposition="The PM paused rollout and accepted the evidence gap."))
        self.assertEqual(self.flow.due(), [])
        current = h.trace()["initiative"]
        self.assertEqual(current["decisions"][-1]["evidence_review"]["guardrails"]["pilot-errors"]["status"], "breached")
        revised = {k: v for k, v in self.rule(operator="lte", effective_on=h.today).items() if k != "adopted_from"}
        h.preview(revised, error="would change an existing reading")
        h.submit(dict(revised, effective_on=self.flow.tomorrow))
        h.submit(self.outcomes("unmeasured", disposition="The PM continues the pause pending the next bound."))
        self.assertEqual(h.trace()["initiative"]["outcome_review"]["next_review_on"], self.flow.tomorrow)

    def test_correction_reopens_and_retains_both_histories_and_sources(self):
        h = self.h
        h.submit(self.rule(operator="lte"))
        h.submit(self.reading("equal", "2.00", guard=True))
        h.submit(self.reading("bad", "99"))
        old_outcome = self.outcomes("met", "bad")
        h.submit(old_outcome)
        signed = json.loads(h.ledger.read_text())["record"]["events"]
        h.submit(self.correction("bad"))
        self.assertEqual(self.flow.due(), [h.i])
        h.preview(old_outcome, error="unusable evidence")
        h.submit(self.outcomes("unmeasured"))
        self.assertEqual(json.loads(h.ledger.read_text())["record"]["events"][:len(signed)], signed)
        self.assertEqual(self.flow.due(), [])
        trace = h.trace()["initiative"]
        self.assertIn("bad", trace["unusable_measurements"])
        self.assertEqual(trace["measurements"]["bad"]["source"], "Fictional query export, version bad")
        self.assertEqual(trace["corrections"]["bad"]["source"], "Audit query R-12, signed report")
        h.preview(self.correction("bad"), error="active measurement")
        h.submit(self.correction("equal"))
        h.preview(self.outcomes("unmeasured"), error="pilot-errors is unavailable")
        h.submit(self.outcomes("unmeasured", disposition="The PM accepts the missing pilot reading."))
        current = h.trace()["initiative"]["guardrail_results"]["pilot-errors"]
        self.assertTrue(current["missing_current_reading"])
        self.assertEqual(current["readings"][0]["assessed_as"], "within")

    def test_follow_up_cannot_hide_changed_data_or_supersession(self):
        h = self.h
        h.submit(self.reading("first", "99", observed=self.flow.yesterday))
        follow = {"on": self.flow.tomorrow, "action": "Check the completed pilot cohort."}
        h.submit(self.outcomes("met", "first", follow=follow))
        alternative = h.preview(self.correction("first"))
        corrected = self.reading("recount", "54", observed=self.flow.yesterday)
        h.submit(corrected)
        self.assertEqual(self.flow.due(), [h.i])
        h.preview(self.outcomes("met", "first"), error="conflicting observations")
        h.preview(self.outcomes("pending", "first", follow=follow), error="material evidence")
        h.apply(alternative, error="stale")
        h.preview(self.reading("wrong-day", "54"), self.correction("first", "wrong-day"), error="original observation")
        h.preview(dict(corrected, measurement="accidental-retry"), error="already recorded")
        h.submit(self.correction("first", "recount"))
        h.preview(self.correction("recount", "first"), error="distinct active replacement")
        h.submit(self.outcomes("missed", "recount"))
        self.assertEqual(self.flow.due(), [])
        self.assertIn("PASS", h.cli("check"))

    def test_a_guardrail_within_an_old_window_cannot_clear_a_newer_target(self):
        h = self.h
        h.submit(self.rule(), self.reading("previous", "1", guard=True, observed=self.flow.yesterday),
                 self.reading("current", "89"))
        h.preview(self.outcomes("met", "current"), error="pilot-errors is unavailable")
        h.submit(self.outcomes("met", "current", disposition="Pause expansion until the pilot error count is available."))
        self.assertTrue(h.trace()["initiative"]["guardrail_results"]["pilot-errors"]["missing_current_reading"])

    def test_a_measurement_cannot_span_two_guardrail_revisions(self):
        h = self.h
        # Use a full seven-day release window and change the threshold inside it.
        early = (date.today() - timedelta(days=15)).isoformat()
        weekly = self.rule(basis="week", effective_on=early,
                           adopted_from={"target": self.metric, "on": early, "source": "Pilot charter"})
        h.submit(weekly)
        change = {k: v for k, v in self.rule(basis="week", effective_on=h.today).items() if k != "adopted_from"}
        h.submit(change)
        week = self.reading("weekly", "2", guard=True, start=(date.today() - timedelta(days=6)).isoformat(),
                            end=self.flow.tomorrow, basis="week")
        h.preview(week, error="bound changed during this window")

    def test_registry_reading_cannot_bypass_signed_period_denominator_or_original_revision(self):
        h = self.h
        reg = "logo-churn"
        request = {"approved_by": "Pilot Finance", "source": "Fictional pilot metrics agreement",
                   "effective_on": self.release, "changes": {"reporting_window": "day", "period": "Day"}}
        h.cli("metric", "set", reg, "--product", "example", "--write", value=request)
        row = json.loads(h.cli("metric", "show", reg, "--product", "example"))
        h.submit({"type": "metric", "metric": reg})
        h.submit(self.rule(metric=reg, population=row["population"]))
        guard = dict(self.reading("fraction", "2.0", guard=True, definition=row["reference"],
                                  population=row["population"], denominator_basis=row["denominator"],
                                  numerator=1996, denominator=100000, numerator_subset=True), metric=reg)
        for changed, message in [({"basis": "week"}, "basis"), ({"denominator_basis": "All accounts"}, "denominator"),
                                  ({"start": self.flow.tomorrow}, "start"), ({"numerator": 4000}, "recalculated")]:
            h.preview(dict(guard, observation={**guard["observation"], **changed}), error=message)
        h.submit(guard)
        # Rounded 2.0% comes from 1.996%; the strict upper bound passes.
        self.assertEqual(h.trace()["initiative"]["guardrail_results"]["pilot-errors"]["status"], "within")
        h.cli("metric", "set", reg, "--product", "example", "--write", value={**request, "effective_on": h.today,
              "changes": {"period": "Calendar month", "reporting_window": "calendar month"}})
        self.assertEqual(h.trace()["initiative"]["guardrail_results"]["pilot-errors"]["status"], "within")
        fresh = {**guard, "measurement": "restated", "source": "Pinned basis query R8",
                 "observation": {**guard["observation"], "source": "Pinned basis query R8"}}
        h.preview(fresh, error="source of a restatement")
        h.submit(dict(fresh, restatement="Query R8 recalculates the daily pilot cohort on the signed definition."))
        h.submit(self.outcomes("unmeasured"))

    def test_previous_signed_history_replays_before_new_eligibility_applies(self):
        h = self.h
        # Reproduce the exact old schemas: the pre-upgrade signer neither recorded a contract
        # nor generated a date or an evidence snapshot on its measurement and review.
        h.submit(self.reading("old-claim", "99"))
        h.submit(self.outcomes("met", "old-claim"))
        record = json.loads(h.ledger.read_text())["record"]
        registered = json.loads(h.cli("metric", "show", "logo-churn"))
        ref = "Metric registry " + registered["reference"]
        for event in record["events"]:
            if event["type"] == "metric" and event["metric"] == self.metric:
                event["source"] = ref
            if event["type"] == "measurement":
                for key in ("recorded_on", "observation"):
                    event.pop(key, None)
                event["value"] = "99 percent"
            if event.get("action") == "review-outcomes":
                event.pop("evidence_review")
        with patch.dict("os.environ", h.env):
            signature = initiative_store.sign(h.root, record, str(h.key))
        h.ledger.write_text(json.dumps({"record": record, "signature": signature}))
        before = h.ledger.read_bytes()
        view = h.trace()["initiative"]
        self.assertEqual(view["outcome_review"]["status"], "closed")
        self.assertEqual(view["unusable_measurements"], ["old-claim"])
        self.assertEqual(h.ledger.read_bytes(), before)
        h.preview(self.outcomes("met", "old-claim"), error="unusable evidence")
        h.preview(self.flow.measure(self.metric, "second-claim", h.today), error="Supply an observation")
        h.submit(self.correction("old-claim"), self.outcomes("unmeasured"))
