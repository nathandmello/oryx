"""Exercise the PM's duplicate decision at the signed capture boundary."""

from copy import deepcopy
import json
import os
import unittest
from unittest.mock import patch

import test_opportunities
import initiative_store


class IntakeReviewTests(unittest.TestCase):
    def setUp(self):
        self.hub = test_opportunities.InitiativeTests()
        self.addCleanup(self.hub.doCleanups)
        self.hub.setUp()

    def apply(self, proposal, *ids, error=None):
        hub = self.hub
        before = hub.ledger.read_bytes()
        flags = []
        for identifier in ids:
            flags.extend(("--confirm-distinct", identifier))
        hub.cli("initiative", "apply", "example", "--key", str(hub.key), *flags, value=proposal, error=error)
        if error:
            self.assertEqual(hub.ledger.read_bytes(), before)

    def test_paraphrase_with_no_shared_words_requires_pm_choice_and_can_become_a_signal(self):
        h = self.hub
        original = {**h.capture(title="Support dashboard", source="Sales interview A"),
                    "summary": "Managers cannot see unresolved tickets."}
        h.submit(h.setup_event(), original, h.decision("defer", revisit="When staffing changes"))
        alternate = h.product_id + "/operations-cockpit"
        report = {**h.capture(alternate, "Operations cockpit", "Customer council B"),
                  "summary": "Supervisors lack visibility into ageing customer cases."}
        proposal = h.preview(report)
        self.assertEqual(proposal["intake_reviews"][alternate], [
            {"id": h.i, "title": "Support dashboard", "phase": "deferred", "problem": original["summary"],
             "source": original["source"]}])
        self.assertEqual(proposal["reviewed_transactions"][0]["intake_review"], {"considered": 1, "candidates": [h.i]})
        self.apply(proposal, error="--confirm-distinct")
        self.apply(proposal, h.i, error="--confirm-distinct")
        h.preview({**report, "intake_review": {"considered": 0, "candidates": []}}, error="unknown")
        self.assertEqual(len(json.loads(h.cli("backlog", "--all-phases"))), 1)

        signal = {key: report[key] for key in ("source", "observed_on", "summary")}
        h.submit({"type": "signal", "initiative": h.i, **signal})
        self.assertEqual(h.trace()["initiative"]["signals"][-1], signal)
        self.assertEqual([r["id"] for r in json.loads(h.cli("backlog", "--all-phases"))], [h.i])

    def test_batched_captures_bind_bounded_comparisons_and_the_exact_confirmed_ids(self):
        h = self.hub
        h.submit(h.setup_event(max_open=10), h.capture(title="Aged case dashboard"))
        batch = [h.capture(f"{h.product_id}/distinct-{i}", f"Independent item {i}", f"Report {i}") for i in range(6)]
        proposal = h.preview(*batch)
        ids = [entry["initiative"] for entry in batch]
        reviews = [entry["intake_review"] for entry in proposal["reviewed_transactions"]]
        self.assertEqual([review["considered"] for review in reviews], list(range(1, 7)))
        self.assertEqual([len(review["candidates"]) for review in reviews], [1, 2, 3, 4, 5, 5])
        self.assertIn(ids[-2], reviews[-1]["candidates"])
        self.apply(proposal, *ids[:-1], error="--confirm-distinct")
        self.apply(proposal, *ids, ids[-1], error="--confirm-distinct")
        self.apply(proposal, *ids, h.i, error="--confirm-distinct")

        altered = deepcopy(proposal)
        altered["intake_reviews"][ids[-1]][0]["problem"] = "Different evidence."
        self.apply(altered, *ids, error="stale or was modified")
        h.submit({"type": "signal", "initiative": h.i, "source": "Workshop C", "observed_on": h.today,
                  "summary": "A dashboard needs an ageing case chart."})
        self.apply(proposal, *ids, error="stale or was modified")
        current = h.preview(*batch)
        self.apply(current, *ids)
        saved = json.loads(h.cli("initiative", "show", "example", ids[-1]))["initiative"]
        self.assertEqual(saved["intake_review"], current["reviewed_transactions"][-1]["intake_review"])
        related = {**h.capture(f"{h.product_id}/charts", "Ageing case chart", "Another request"),
                   "summary": "Dashboard for aged cases."}
        review = h.preview(related)
        self.assertEqual(review["intake_reviews"][related["initiative"]][0]["id"], h.i)
        self.assertEqual(review["reviewed_transactions"][0]["intake_review"]["considered"], 7)

    def test_previous_signed_captures_are_included_without_rewriting_history(self):
        h = self.hub
        h.submit(h.setup_event(), h.capture())
        prior = h.capture(h.product_id + "/older", "Older problem", "Old register")
        envelope = json.loads(h.ledger.read_text())
        envelope["record"]["events"].append(prior)
        with patch.dict(os.environ, h.env):
            envelope["signature"] = initiative_store.sign(h.root, envelope["record"], h.key)
        h.ledger.write_text(json.dumps(envelope))
        before = h.ledger.read_bytes()
        new = h.capture(h.product_id + "/later", "Later problem", "New source")
        proposal = h.preview(new)
        self.assertEqual(set(proposal["reviewed_transactions"][0]["intake_review"]["candidates"]),
                         {h.i, prior["initiative"]})
        self.assertEqual(h.ledger.read_bytes(), before)
        h.submit(h.capture(h.product_id + "/concurrent", "Concurrent report", "Separate intake"))
        self.apply(proposal, new["initiative"], error="stale or was modified")
        refreshed = h.preview(new)
        self.assertEqual(refreshed["reviewed_transactions"][0]["intake_review"]["considered"], 3)
