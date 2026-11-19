"""Exercise plan evidence review through signed initiative commands."""

from copy import deepcopy
from datetime import date, timedelta
import json
import unittest

import test_opportunities


class SignalReviewTests(unittest.TestCase):
    claim = "Legal clearance covers every target customer before rollout."

    def setUp(self):
        self.hub = test_opportunities.InitiativeTests()
        self.addCleanup(self.hub.doCleanups)
        self.hub.setUp()
        h = self.hub
        h.submit(h.setup_event(), h.capture(), h.describe(), h.metric(), h.decision("evaluate"))
        h.submit(h.decision("prepare-brief"))
        h.brief_ready()
        h.fill(h.brief, {"Assumptions and risks": self.claim})
        h.submit(h.target(), h.decision("approve-initiative"))
        h.submit(h.cycle(), h.plan())
        self.signal = {
            "type": "signal", "initiative": h.i, "source": "Legal decision 41, scope item 2",
            "observed_on": (date.today() - timedelta(days=1)).isoformat(),
            "summary": "Legal prohibits rollout for every customer in the approved cohort.",
        }

    def assessment(self, **overrides):
        return {
            "type": "review-signal", "initiative": self.hub.i, "signal": self.signal["source"],
            "claim": self.claim, "impact": "material", "action": "assess", "on": self.hub.today,
            "reason": "The legal restriction covers the entire approved cohort.",
            "source": "PM launch review, decision 7", "residual_risk": "The ship date depends on approval.",
            "follow_up": None, **overrides,
        }

    def reviews(self):
        return self.hub.trace()["initiative"]["signal_reviews"]

    def test_ordinary_signal_previews_signed_claims_and_remains_due_after_capture(self):
        h = self.hub
        self.assertEqual(self.reviews(), [])
        before = h.ledger.read_bytes()
        proposal = h.preview(self.signal)
        review, = proposal["signal_reviews"][h.i]
        self.assertEqual(review["state"], "needs-triage")
        self.assertEqual(review["claims"][0]["text"], self.claim)
        self.assertEqual(review["claims"][0]["record"], h.brief)
        self.assertEqual(review["basis"]["selection"]["action"], "plan")
        self.assertEqual(h.ledger.read_bytes(), before)
        modified = deepcopy(proposal)
        modified["signal_reviews"][h.i][0]["reason"] = "An edited preview."
        h.apply(modified, error="proposal is stale or was modified")
        h.apply(proposal)
        self.assertEqual(h.trace()["initiative"]["phase"], "planned")
        self.assertEqual(self.reviews(), [review])
        self.assertEqual(h.trace()["review_issues"], [])
        self.assertEqual([row["id"] for row in json.loads(h.cli("backlog", "--due"))], [h.i])
        self.assertIn("needs-triage", h.cli("roadmap", "--format", "csv"))
        self.assertIn("Evidence review", h.cli("roadmap", "--format", "markdown"))
        h.preview(self.signal, error="Source already captured")

    def test_material_uncertain_revise_and_retained_reviews_preserve_history(self):
        h = self.hub
        h.submit(self.signal)
        h.preview(self.assessment(claim="Invented clearance claim."), error="Quote a specific claim")
        h.preview(self.assessment(claim=None), error="Link a specific approved claim")
        h.preview(self.assessment(residual_risk=None), error="state the residual risk")
        h.preview(self.assessment(action="follow-up"), error="needs a date")
        h.submit(self.assessment(impact="uncertain", reason="Legal has confirmed one country only."))
        review, = self.reviews()
        self.assertEqual(review["state"], "uncertain")
        self.assertEqual(review["claims"][0]["text"], self.claim)
        self.assertIn(self.claim, h.cli("roadmap"))
        h.submit(self.assessment(action="revise"))
        self.assertEqual(self.reviews()[0]["state"], "revise")
        self.assertEqual(h.trace()["initiative"]["phase"], "planned")
        follow_up = {"on": (date.today() + timedelta(days=3)).isoformat(), "action": "Ask Legal about the remaining markets."}
        h.submit(self.assessment(action="follow-up", follow_up=follow_up))
        self.assertEqual(json.loads(h.cli("backlog", "--due")), [])
        h.submit(self.assessment(action="retain", reason="The PM retained the already approved markets."))
        review, = self.reviews()
        self.assertEqual(review["state"], "retained")
        self.assertEqual([row["action"] for row in review["history"]],
                         ["assess", "revise", "follow-up", "retain"])
        self.assertEqual(review["residual_risk"], "The ship date depends on approval.")
        self.assertIsNone(review["review_on"])
        self.assertEqual(json.loads(h.cli("backlog", "--due")), [])
        self.assertEqual(h.trace()["initiative"]["phase"], "planned")
        self.assertIn("PASS", h.cli("check"))

    def test_routine_signal_clears_and_explicit_reopen_unplans_only_affected_work(self):
        h = self.hub
        sibling = f"{h.product_id}/incident"
        h.submit(h.capture(sibling, "Review sign-in outage", "Incident 17, initial report"))
        sibling_before = json.loads(h.cli("initiative", "show", "example", sibling))["initiative"]
        routine = self.signal
        second = {**routine, "source": "Legal decision 56, renewal cohort"}
        h.submit(routine, self.assessment(impact="routine", claim=None, residual_risk=None,
                                         reason="The new notes contain a routine wording update."), second)
        self.assertEqual([review["state"] for review in self.reviews()], ["routine", "needs-triage"])
        self.assertEqual(len(json.loads(h.cli("backlog", "--due"))), 1)
        h.submit(self.assessment(signal=second["source"], action="reopen"))
        self.assertEqual([review["state"] for review in self.reviews()], ["routine", "reopened"])
        item = h.trace()["initiative"]
        self.assertEqual(item["phase"], "under consideration")
        self.assertEqual(item["decisions"][-1]["action"], "reopen")
        self.assertIsNone(item["planning"])
        self.assertEqual(json.loads(h.cli("backlog", "--due")), [])
        self.assertEqual(json.loads(h.cli("roadmap")), [])
        self.assertEqual(item["signals"][-1]["source"], second["source"])
        self.assertEqual(json.loads(h.cli("initiative", "show", "example", sibling))["initiative"], sibling_before)
        h.preview(self.assessment(signal=second["source"]), error="against the active signed approval")
