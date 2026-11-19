"""Exercise risk capture, recall and PM dispositions using the public commands."""

from datetime import date
import json
from pathlib import Path
import subprocess
import sys
import unittest

import test_opportunities


class ContextRiskTests(unittest.TestCase):
    def setUp(self):
        self.h = test_opportunities.InitiativeTests()
        self.h.setUp()
        self.addCleanup(self.h.doCleanups)
        self.today = date.today().isoformat()

    def packet(self, source, quote, scope="product", *, coverage="read", **entry):
        home = {"product": "example"} if scope == "product" else {}
        return {"sources": [{"reference": source, "date": self.today, "checked_on": self.today,
                             "coverage": coverage, "text": quote + " Extra transcript detail only."}],
                "entries": [dict(scope=scope, **home, topic="constraints", source=1, location="Minute 12",
                                 quote=quote, **entry)]}

    def committee(self, scope, quote, person, decision_scope="EU bulk export"):
        record = self.h.company if scope == "company" else self.h.product_context
        packet = self.packet(person + " minutes", quote, scope)
        packet["entries"][0].update(topic="decisions", decision={
            "question": "When can EU bulk export launch?", "scope": decision_scope, "person": person,
            "date": self.today, "next_step": "Draft the customer update."})
        return record, packet

    def capture(self, owner, packet):
        return json.loads(self.h.cli("route-context", "--write", owner, value=packet))

    def lookup(self, *extra):
        return json.loads(self.h.cli("task-context", "Draft a customer update about EU bulk export.",
                                     "--product", "example", *extra))

    def test_conflict_on_capture_hook_repeat_and_resolution_history(self):
        h = self.h
        first = self.committee("company", "EU bulk export needs Legal sign-off before launch.", "Legal")
        self.capture(*first)
        second = self.committee("product", "Launch EU bulk export on Friday before Legal sign-off.", "Product")
        owner, packet = second
        before = (h.work / owner).read_bytes()
        preview = json.loads(h.cli("route-context", value=packet))
        self.assertTrue(any(r["classification"] == "potential conflict" for r in preview["risk_preview"]))
        self.assertEqual((h.work / owner).read_bytes(), before)
        event, = self.capture(*second)["risk_events"]
        self.assertEqual({c["authority"].split(",")[0] for c in event["claims"]}, {"Legal", "Product"})
        self.assertTrue(all(c["sources"] for c in event["claims"]))
        self.assertNotIn("Extra transcript detail", (h.work / owner).read_text())
        recorded = (h.work / owner).read_bytes()
        self.assertEqual(self.lookup()["risks"][0]["id"], event["id"])
        hooks = subprocess.run([sys.executable, str(h.root / "tools/hook.py")], cwd=h.root, input=json.dumps({
            "hook_event_name": "UserPromptSubmit", "session_id": "risk-fixture",
            "cwd": str(h.root), "prompt": "Quiet. Draft a customer update for product/example EU bulk export."}),
            env=h.env, capture_output=True, text=True, check=True)
        self.assertIn(event["id"], hooks.stdout)
        self.assertEqual(self.capture(*second)["written"], None)
        self.assertEqual((h.work / owner).read_bytes(), recorded)
        response = {"id": event["id"], "record": owner, "state": "dismiss",
                    "reason": "The Friday date was for an internal rehearsal.", "source": "PM clarification, minute 20"}
        replies = {"entries": [], "sources": [], "responses": [response]}
        wrong = dict(response, record=h.company)
        h.cli("route-context", "--write", h.company, value=dict(replies, responses=[wrong]), error="owning context")
        self.capture(owner, replies)
        self.assertNotIn(event["id"], str(self.lookup().get("risks", [])))
        self.assertEqual(self.capture(owner, replies)["written"], None)
        recalled = json.loads(h.cli("task-context", "Show " + event["id"]))
        self.assertEqual([e["state"] for e in recalled["risk_history"][0]["history"]], ["open", "dismiss"])
        self.assertEqual(recalled["risk_history"][0]["history"][-1]["reason"], response["reason"])
        amended = self.committee("product", "Send the EU bulk export release to customers before clearance.", "Sales")
        self.capture(*amended)
        self.assertTrue(any(r["id"] != event["id"] for r in self.lookup()["risks"]))
        self.assertIn("PASS", h.cli("check"))

    def test_partial_meeting_note_honors_authority_and_missing_scope(self):
        h = self.h
        note = "context/company/2026-11-19-weekly-roundtable.md"
        quote = "Legal prohibits EU bulk export for the target cohort."
        packet = self.packet("Roundtable recording", quote, "company", coverage="partial",
                             risk={"reason": "The named cohort may include current pilot customers.",
                                   "authority": "Meeting attendee relaying Legal's position"})
        packet["entries"][0]["record"] = {"path": note, "parent": h.company, "basis": "event-history",
                                          "reason": "The PM revisits this decision.", "trigger": "The transcript changes."}
        event, = self.capture(note, packet)["risk_events"]
        review = self.lookup()["risks"][0]
        self.assertEqual(review["id"], event["id"])
        self.assertEqual(review["claims"][0]["source"]["coverage"], "partial")
        self.assertEqual(review["claims"][0]["location"], "Minute 12")
        self.assertNotIn("Extra transcript detail", (h.work / note).read_text())
        self.assertFalse(h.ledger.exists())
        question = {"sources": [{"reference": "Legal ruling L-82", "coverage": "unavailable", "date": "undated"}],
                    "entries": [{"scope": "company", "topic": "constraints",
                                 "question": "Which EU accounts fall within the ruling?",
                                 "risk": {"reason": "The applicable cohort remains unknown.", "source": 1}}]}
        pending, = self.capture(h.company, question)["risk_events"]
        self.assertEqual(pending["claims"][0]["source"]["coverage"], "unavailable")
        self.assertNotIn("checked_on", pending["claims"][0]["source"])
        self.assertIn("PASS", h.cli("check"))

    def test_disjoint_decision_scopes_remain_separate(self):
        self.capture(*self.committee("company", "Release needs written approval.", "Legal", "EU pilot"))
        self.capture(*self.committee("product", "Launch on Friday.", "Product", "US pilot"))
        self.assertNotIn("risks", self.lookup())

    def test_context_risk_appears_on_existing_initiative_and_portfolio_views(self):
        h = self.h
        h.submit(h.setup_event(), h.capture(), h.describe(), h.metric(), h.decision("evaluate"))
        h.submit(h.decision("prepare-brief"))
        h.brief_ready()
        h.submit(h.target(), h.decision("approve-initiative"))
        h.submit(h.cycle(), h.plan())
        source = self.packet("Clearance assessment", "Legal requires another review for the pilot.",
                             risk={"reason": "Friday clearance is uncertain.", "targets": [h.i]})
        register_bytes = h.ledger.read_bytes()
        event, = self.capture(h.product_context, source)["risk_events"]
        self.assertEqual(h.ledger.read_bytes(), register_bytes)
        review, = h.trace()["initiative"]["context_risks"]
        self.assertEqual(review["id"], event["id"])
        self.assertIn(event["id"], h.cli("action", "portfolio", "roadmap", "show", "--format", "markdown"))
        self.assertIn(event["id"], h.cli("action", "portfolio", "backlog", "show", "--due"))
        response = {"record": h.product_context, "id": event["id"], "state": "retain",
                    "reason": "The PM accepts the timing exposure pending Legal approval.", "source": "PM review, item 2"}
        self.capture(h.product_context, {"entries": [], "sources": [], "responses": [response]})
        self.assertEqual(h.trace()["initiative"]["context_risks"][0]["state"], "retain")
        self.assertEqual(json.loads(h.cli("backlog", "--due")), [])
        self.assertEqual(h.ledger.read_bytes(), register_bytes)
        signal = {"type": "signal", "initiative": h.i, "source": "Legal directive, item 7",
                  "summary": "The pilot is blocked.", "observed_on": self.today}
        h.submit(signal)
        result = self.lookup("--initiative", "renewal")
        self.assertEqual({r["id"] for r in result["risks"]}, {event["id"], signal["source"]})
        self.assertIn("PASS", h.cli("check"))

    def test_corrupt_unrelated_history_is_scoped_and_repairable(self):
        h = self.h
        other = "context/products/other/overview.md"
        h.new("product-context", other)
        record = h.work / other
        record.write_text(record.read_text().replace("## Context controls",
            "## Evidence review history\n\n```jsonl\nmalformed\n```\n\n## Context controls"))
        self.assertNotIn("risks", self.lookup())
        result = json.loads(h.cli("task-context", "--product", "other"))
        self.assertIn(other, str(result["warnings"]))
        source = self.packet("Scope report", "The pilot can use an existing queue.")
        source["entries"][0]["product"] = "other"
        old = record.read_bytes()
        h.cli("route-context", "--write", other, value=source, error="Restore the evidence review history")
        self.assertEqual(record.read_bytes(), old)
        self.capture(*self.committee("company", "Legal approval covers the pilot.", "Legal"))

    def test_changed_coverage_reopens_dismissed_risk_and_preserves_event_bytes(self):
        h = self.h
        packet = self.packet("Cohort memo", "The cohort excludes current pilot accounts.", coverage="partial",
                             risk={"reason": "Check the planned audience.", "authority": "Policy owner"})
        original, = self.capture(h.product_context, packet)["risk_events"]
        path = h.work / h.product_context
        first_line = next(line for line in path.read_bytes().splitlines() if b'"classification":' in line)
        self.capture(h.product_context, {"sources": [], "entries": [], "responses": [{
            "record": h.product_context, "state": "dismiss", "id": original["id"],
            "source": "PM review log", "reason": "The incomplete excerpt refers to another pilot."}]})
        packet["sources"][0]["coverage"] = "read"
        updated, = self.capture(h.product_context, packet)["risk_events"]
        self.assertNotEqual(updated["id"], original["id"])
        self.assertIn(first_line, path.read_bytes().splitlines())
        result = self.lookup("--history")
        self.assertEqual([r["id"] for r in result["risks"]], [updated["id"]])
        row, = [r for r in result["entries"] if "The cohort excludes" in r["text"]]
        self.assertEqual(row["sources"][0]["coverage"], "read")
        self.assertEqual({r["state"] for r in result["risk_history"]}, {"dismiss", "open"})

    def test_recall_by_id_for_cross_product_risk_and_unfiled_legacy_conflict(self):
        h = self.h
        packet = self.packet("Supply assessment", "The transfer date moved to March.",
                             risk={"reason": "A different product depends on the February transfer.",
                                   "targets": ["product-context-0123456789ab/transfer"]})
        event, = self.capture(h.product_context, packet)["risk_events"]
        self.assertEqual(json.loads(h.cli("task-context", "Show " + event["id"]))["risk_history"][0]["id"], event["id"])
        self.capture(*self.committee("company", "EU release requires Legal clearance.", "Legal"))
        owner, second = self.committee("product", "Proceed with EU release before clearance.", "Product")
        pair, = self.capture(owner, second)["risk_events"]
        # Simulate copied legacy records that predate evidence journals.
        path = h.work / owner
        text = path.read_text()
        start = text.index("## Evidence review history")
        path.write_text(text[:start] + text[text.index("## Context controls", start):])
        before = path.read_bytes()
        recalled = json.loads(h.cli("task-context", "Show " + pair["id"]))["risk_history"]
        self.assertEqual([r["id"] for r in recalled], [pair["id"]])
        self.assertEqual(path.read_bytes(), before)
