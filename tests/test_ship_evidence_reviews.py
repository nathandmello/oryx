"""Verify that advisory evidence is scoped, reviewed, and preserved with the ship decision."""

from datetime import date, timedelta
import json
import unittest

import test_opportunities


class ShipEvidenceReviewTests(unittest.TestCase):
    def test_ship_binds_signed_signals_and_independently_saved_context(self):
        h = test_opportunities.InitiativeTests()
        self.addCleanup(h.doCleanups)
        h.setUp()
        claim = "Restore alerts for the internal renewal cohort."
        h.submit(h.setup_event(), h.capture(), h.decision(
            "expedite", delivery="https://example.com/delivery/42", owner="Incident PM",
            obligation="Restore delay alerts", deadline=h.today, scope=claim, review_on=h.today))
        checks = [{"id": phase, "action": "add", "fields": {
            "title": "Verify " + phase, "phase": phase, "criterion": "Confirm delivery of the regional alert",
            "status": "verified", "owner": "Duty engineer",
            "verification": {"by": "Duty engineer", "on": h.today, "evidence": "Regional receipt R42"},
        }} for phase in ("upstream", "launch")]
        h.cli("launch-checklist", "apply", "example", "renewal", "--revision", "absent", value=checks)

        signal = {"type": "signal", "initiative": h.i, "source": "Pager review, item 2", "observed_on": h.today,
                  "summary": "Some renewal accounts use untested alert routes."}
        routine = {**signal, "source": "Receipt confirmation R42", "summary": "The drill receipt arrived."}
        h.submit(signal, routine)
        review = {"type": "review-signal", "initiative": h.i, "signal": signal["source"], "claim": claim,
                  "impact": "material", "action": "retain", "on": h.today, "source": "Incident PM review 17",
                  "reason": "Restrict the launch to accounts with confirmed routes.",
                  "residual_risk": "Untested accounts might miss alerts.", "follow_up": None}
        h.submit(review, {**review, "signal": routine["source"], "claim": None, "impact": "routine",
                          "action": "assess", "reason": "The receipt confirms the existing drill.", "residual_risk": None})

        def capture(source, quote, targets=None):
            risk = {"reason": "Confirm coverage before expanding the pilot.", "authority": "Regional operations"}
            if targets:
                risk["targets"] = targets
            payload = {"sources": [{"reference": source, "date": h.today, "checked_on": h.today,
                                    "coverage": "read", "text": quote}],
                       "entries": [{"scope": "product", "product": "example", "topic": "constraints", "source": 1,
                                    "location": "Minutes, item 4", "quote": quote, "risk": risk}]}
            return json.loads(h.cli("route-context", "--write", h.product_context, value=payload))["risk_events"][0]["id"]

        def respond(key, state, reason, **fields):
            reply = {"id": key, "state": state, "reason": reason, "source": "Operations review 24",
                     "record": h.product_context, **fields}
            h.cli("route-context", "--write", h.product_context, value={"entries": [], "sources": [], "responses": [reply]})

        quote = "Regional service hours vary between the pilot accounts."
        reference = "Operations coverage memo"
        key = capture(reference, quote)
        ship = h.decision("ship", review_on=h.today)
        old_ledger = h.ledger.read_bytes()
        proposal = h.preview(ship)
        old = proposal["reviewed_transactions"][0]["readiness"]
        self.assertEqual(old["outstanding"], {})
        signed = old["advisories"]["signals"]
        self.assertEqual(set(signed), {signal["source"]})
        self.assertEqual(signed[signal["source"]]["evidence"], {k: signal[k] for k in ("source", "summary", "observed_on")})
        self.assertEqual(signed[signal["source"]]["claims"][0]["text"], claim)
        self.assertEqual(signed[signal["source"]]["history"][-1]["source"], review["source"])
        self.assertEqual(signed[signal["source"]]["state"], "retained")
        context = old["advisories"]["context"][key]
        self.assertEqual(context["claims"][0]["text"], quote)
        self.assertEqual(context["claims"][0]["source"]["reference"], reference)
        self.assertTrue(context["current_claim_evidence"][0]["current_entries"])

        unrelated = capture("EU training notes", "Staff training moves to next Tuesday.", [h.product_id + "/training"])
        self.assertEqual(proposal, h.preview(ship))
        self.assertNotIn(unrelated, old["advisories"]["context"])
        respond(key, "follow-up", "Account coverage awaits the revised weekend schedule.",
                review_on=(date.today() + timedelta(days=7)).isoformat())
        fresh = h.preview(ship)
        current = fresh["reviewed_transactions"][0]["readiness"]
        self.assertEqual(fresh["base"], proposal["base"])
        self.assertNotEqual(current["revision"], old["revision"])
        disposition = current["advisories"]["context"][key]["disposition"]
        self.assertEqual(disposition["state"], "follow-up")
        self.assertEqual(disposition["source"], "Operations review 24")
        h.apply(proposal, error="proposal is stale")
        self.assertEqual(old_ledger, h.ledger.read_bytes())

        # A cited source can change without creating a new review event.
        owner = h.work / h.product_context
        original = owner.read_text()
        owner.write_text(original.replace("| " + reference + " |", "| Revised operations coverage memo |"))
        self.assertNotEqual(original, owner.read_text())
        h.apply(fresh, error="proposal is stale")
        fresh = h.preview(ship)
        current = fresh["reviewed_transactions"][0]["readiness"]
        current_entry, = current["advisories"]["context"][key]["current_claim_evidence"][0]["current_entries"]
        self.assertEqual(current_entry["sources"][0]["Source"], "Revised operations coverage memo")
        self.assertEqual(current["outstanding"], {})
        h.apply(fresh)
        respond(key, "resolve", "The new weekend schedule now covers the pilot.")
        trace = json.loads(h.cli("action", "initiative", "record", "show", "example", h.i))["initiative"]
        self.assertEqual(trace["phase"], "shipped")
        self.assertEqual(trace["decisions"][-1]["readiness"], current)
        self.assertIn("PASS", h.cli("check"))
