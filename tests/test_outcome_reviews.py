"""Exercise signed outcome reviews and their due dates through the private workspace CLI."""

from datetime import date, timedelta
import json
import unittest

import test_opportunities


class OutcomeReviewTests(unittest.TestCase):
    def setUp(self):
        self.hub = test_opportunities.InitiativeTests()
        self.addCleanup(self.hub.doCleanups)
        self.hub.setUp()
        self.yesterday = (date.today() - timedelta(days=1)).isoformat()
        self.tomorrow = (date.today() + timedelta(days=1)).isoformat()

    def release(self, *metrics):
        h = self.hub
        released = (date.today() - timedelta(days=2)).isoformat()
        h.submit(h.setup_event(), {**h.capture(), "observed_on": released})
        for metric in metrics:
            h.submit({**h.metric(), "metric": metric, "name": metric}, {**h.target(), "metric": metric})
        h.submit(h.decision("expedite", on=released, delivery="https://example.com/delivery/42",
                            owner="Support lead", obligation="Restore renewal notices", deadline=h.today,
                            scope="Correct the renewal schedule", review_on=h.today),
                 h.ship_without_checklist(on=released))
        return released

    def measure(self, metric, identifier, when):
        return {"type": "measurement", "initiative": self.hub.i, "measurement": identifier, "metric": metric,
                "value": "82 percent", "observed_on": when, "source": "Release dashboard cohort report"}

    def assessment(self, status, *measurements):
        return {"status": status, "measurements": list(measurements), "assessment": "PM reviewed the renewal cohort."}

    def review(self, outcomes, follow_up=None, **fields):
        return self.hub.decision("review-outcomes", outcomes=outcomes, follow_up=follow_up, **fields)

    def due(self):
        return [row["id"] for row in json.loads(self.hub.cli("backlog", "--due"))]

    def test_activity_retrieves_the_signed_target_only_for_its_initiative(self):
        h = self.hub
        self.release("renewal-rate")
        observed = self.measure("renewal-rate", "pilot-cohort", h.today)
        h.submit(observed)
        query = "How did it perform?"
        initiative = json.loads(h.cli("task-context", "--product", "example", "--initiative", "renewal", query))
        check = initiative["activity_check"]
        self.assertEqual(check["status"], "check_source_and_scope")
        targets = check["recorded_targets"]
        self.assertEqual(len(targets), 1)
        for field in ("metric", "initiative", "baseline", "target", "due", "source"):
            self.assertEqual(targets[0][field], h.target()[field])
        self.assertEqual(h.work / targets[0]["record"], h.ledger)
        view = json.loads(h.cli(*check["initiative_lookup"]))
        reading = view["initiative"]["measurements"]["pilot-cohort"]
        for field in ("value", "source", "observed_on"):
            self.assertEqual(reading[field], observed[field])
        product = json.loads(h.cli("task-context", "--product", "example", query))
        self.assertNotIn("recorded_targets", product["activity_check"])

    def test_review_accounts_for_each_target_and_reschedules_remaining_work(self):
        h = self.hub
        self.release("renewal-rate", "retention")
        h.submit(self.measure("renewal-rate", "cohort", h.today))
        self.assertEqual(self.due(), [h.i])
        renewal = self.assessment("missed", "cohort")
        pending = self.assessment("pending")
        follow = {"on": self.tomorrow, "action": "Confirm retention after the cohort matures."}
        h.preview(self.review({"renewal-rate": renewal}), error="Review every initiative target")
        h.preview(self.review({"renewal-rate": renewal, "retention": self.assessment("met", "cohort")}),
                  error="different target")
        h.preview(self.review({"renewal-rate": renewal, "retention": self.assessment("met")}),
                  error="cite measured evidence")
        h.preview(self.review({"renewal-rate": self.assessment("unmeasured"), "retention": pending}, follow),
                  error="cannot be marked unmeasured")
        h.preview(self.review({"renewal-rate": renewal, "retention": pending}), error="pending evidence")
        readings = {"renewal-rate": renewal, "retention": pending}
        h.preview(self.review(readings, follow, on=self.yesterday), error="predate the recorded measurements")
        h.preview(self.review(readings, {**follow, "on": self.yesterday}), error="after the outcome review")
        proposal = h.preview(self.review(readings, follow))
        self.assertEqual(self.due(), [h.i])
        h.apply(proposal)
        self.assertEqual(self.due(), [])
        self.assertEqual(h.trace()["initiative"]["outcome_review"]["next_review_on"], self.tomorrow)
        h.submit(self.measure("retention", "retained", self.yesterday))
        complete = {"renewal-rate": renewal, "retention": self.assessment("inconclusive", "retained")}
        h.submit(self.review(complete, {**follow, "on": h.today}))
        self.assertEqual(self.due(), [h.i])
        h.submit(self.review(complete))
        item = h.trace()["initiative"]
        self.assertEqual(item["phase"], "shipped")
        self.assertEqual(item["outcome_review"], {"status": "closed", "next_review_on": None, "reviewed_on": h.today})
        self.assertEqual(item["decisions"][-1]["outcomes"], complete)
        self.assertEqual(self.due(), [])
        previously_signed = json.loads(h.ledger.read_text())["record"]["events"]
        later = self.measure("retention", "late-sample", self.yesterday)
        h.submit(later, self.measure("renewal-rate", "second-cohort", h.today))
        self.assertEqual(self.due(), [h.i])
        item = h.trace()["initiative"]
        self.assertEqual(item["outcome_review"], {"status": "open", "next_review_on": self.yesterday, "reviewed_on": h.today})
        self.assertEqual(item["review_trigger_measurements"], ["late-sample", "second-cohort"])
        self.assertEqual(json.loads(h.ledger.read_text())["record"]["events"][:-2], previously_signed)
        h.preview(self.review(complete), error="Cite the new measurements")
        h.submit(self.review(complete, follow))
        h.submit(self.measure("retention", "monthly-cohort", h.today))
        self.assertEqual(self.due(), [])
        self.assertEqual(h.trace()["initiative"]["outcome_review"]["next_review_on"], self.tomorrow)
        updated = {**complete, "retention": self.assessment("inconclusive", "late-sample", "monthly-cohort")}
        h.preview(self.review(updated), error="second-cohort")
        updated["renewal-rate"] = self.assessment("missed", "second-cohort")
        h.submit(self.review(updated))
        self.assertEqual(self.due(), [])
        self.assertEqual(h.trace()["initiative"]["review_trigger_measurements"], [])

    def test_explicit_unmeasured_review_preserves_the_evidence_gap(self):
        h = self.hub
        self.release("renewal-rate")
        gap = self.assessment("unmeasured")
        gap["assessment"] = "The data provider retired the cohort. The PM accepts the evidence gap."
        h.preview(self.review({"renewal-rate": {**gap, "assessment": "Noted."}}), error="concrete PM assessment")
        h.preview(self.review({"renewal-rate": gap}, {"on": self.tomorrow, "action": "Reviewed."}), error="dated follow_up")
        h.submit(self.review({"renewal-rate": gap}))
        item = h.trace()["initiative"]
        self.assertEqual(item["decisions"][-1]["outcomes"]["renewal-rate"]["status"], "unmeasured")
        self.assertEqual(item["measurements"], {})
        self.assertEqual(self.due(), [])

    def test_shipped_history_without_targets_keeps_its_reminder_until_review(self):
        h = self.hub
        self.release()
        previous = h.ledger.read_bytes()
        self.assertEqual(self.due(), [h.i])
        self.assertEqual(h.trace()["initiative"]["outcome_review"]["status"], "open")
        self.assertEqual(h.ledger.read_bytes(), previous)
        h.submit(self.review({}, reason="The incident release had no agreed outcome targets."))
        self.assertEqual(self.due(), [])
        self.assertEqual(h.trace()["initiative"]["measurements"], {})

    def test_outcome_review_rejects_unreleased_initiative(self):
        h = self.hub
        h.submit(h.setup_event(), h.capture())
        h.preview(self.review({}), error="Cannot review-outcomes from inbox")
