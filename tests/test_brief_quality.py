"""Verify fresh narrative reviews and compatibility with earlier signed approvals."""

import json
import unittest

import test_opportunities
import opportunities
import pm
import records


class BriefReviewTests(unittest.TestCase):
    def setUp(self):
        self.hub = test_opportunities.InitiativeTests()
        self.addCleanup(self.hub.doCleanups)
        self.hub.setUp()

    def capture(self):
        h = self.hub
        h.submit(h.setup_event(), h.capture(), h.describe(), h.metric(), h.target(), h.decision("evaluate"))

    def test_discovery_plan_rejects_filler_and_accepts_a_terse_method(self):
        h = self.hub
        self.capture()
        h.submit(h.evidence()[0])
        h.new("discovery-brief", h.discovery)
        start = h.decision("start-discovery", review_on=h.today)
        headings = (*opportunities.DISCOVERY_PLAN, "Sources")
        for answers in (dict.fromkeys(headings, "Noted."),
                        dict(zip(headings, ["Reviewed by the team.", "To be defined.", "6 weeks.", "- [x]", "…"]))):
            h.fill(h.discovery, answers, complete=False)
            h.cli("check")
            errors = h.preview(start, error="Complete the brief for this review")
            for heading in headings:
                self.assertIn(heading, errors)
        plan = {
            "Known, assumed, and unknown": "Two disputed renewals. Cause unknown.",
            "Learning goals and exit criteria": "If reminders arrive late, pilot earlier alerts.",
            "Approach and timebox": "Interview five administrators.",
            "Capacity and review": "Billing PM leads. Sales reviews the calls.",
            "Sources": "SUP-417",
        }
        for empty_method in ("For the next six weeks.", "TBD in two weeks.", "Six weeks of discovery."):
            h.fill(h.discovery, {**plan, "Approach and timebox": empty_method}, complete=False)
            h.preview(start, error="Name the research method")
        h.fill(h.discovery, plan, complete=False)
        h.submit(start, h.evidence()[3])
        h.fill(h.discovery, {"Findings and recommendation": "Agreed."})
        h.preview(h.decision("prepare-brief"), error="Findings and recommendation")
        h.fill(h.discovery, {"Findings and recommendation": "Both reminders arrived late. Pilot earlier alerts."})
        h.submit(h.decision("prepare-brief"))

    def test_initiative_sections_need_visible_distinct_answers(self):
        h = self.hub
        self.capture()
        h.submit(h.decision("prepare-brief"))
        h.brief_ready()
        template = (h.root / "templates/initiative-brief.md").read_text()
        prompt = records.section(template, "Delivery and launch").strip().strip("{}")
        for launch, error in (("<!-- Enable Support -->", "Describe how the change"),
                              ("```md\nEnable Support.\n```", "Describe how the change"),
                              ("**Delivery and launch**", "Describe how the change"),
                              (prompt, "Describe how the change"),
                              ("send account reminders!", "repeats Proposal")):
            h.fill(h.brief, {"Delivery and launch": launch})
            h.preview(h.decision("approve-initiative"), error=error)
        h.fill(h.brief, {"Delivery and launch": "Enable Support.", "Sources": "[S1] [S2]"})
        h.preview(h.decision("approve-initiative"), error="Name an identifiable evidence source")
        h.fill(h.brief, {"Sources": "[S1](https://example.com/records/7)"})
        h.preview(h.decision("approve-initiative"))
        h.fill(h.brief, {"Sources": "[S1] INT-7"})
        h.submit(h.decision("approve-initiative"))
        self.assertEqual(h.trace()["initiative"]["phase"], "candidate")

    def test_historical_weak_approval_is_readable_but_cannot_authorize_new_investment(self):
        h = self.hub
        self.capture()
        h.submit(h.decision("prepare-brief"))
        h.brief_ready()
        h.submit(h.decision("approve-initiative"), h.cycle(), h.plan())

        # Reproduce an older client that signed any non-placeholder narrative.
        h.fill(h.brief, dict.fromkeys(opportunities.REQUIRED_SECTIONS["initiative-brief"], "Noted."))
        envelope = json.loads(h.ledger.read_text())
        old_approval = next(e for e in envelope["record"]["events"] if e.get("action") == "approve-initiative")
        old_approval["references"] = pm.initiative_store.doc_reference(
            h.root, h.brief, "initiative-brief", initiative=h.i)
        h.write_legacy_register(envelope["record"])

        h.cli("check")
        self.assertEqual(h.trace()["review_issues"], [])
        self.assertEqual(json.loads(h.cli("roadmap"))[0]["id"], h.i)
        h.preview(h.decision("start-delivery", delivery="https://example.com/delivery/7"), error="Reopen the initiative")
        h.submit(h.decision("unplan"))
        h.submit({**h.metric(), "metric": "other", "name": "Other signal volume"})
        h.preview(h.plan(), error="Reopen the initiative")
        h.submit(h.decision("defer", revisit="After the next support review"))
        self.assertEqual(h.trace()["initiative"]["phase"], "deferred")

    def test_experiment_approval_requires_distinct_visible_answers(self):
        h = self.hub
        self.capture()
        hypothesis, plan, _, _ = h.evidence()
        h.preview({**hypothesis, "statement": "Agreed."}, error="hypothesis.statement")
        h.submit(hypothesis)
        h.preview({**plan, "method": "TBD"}, error="experiment.method")
        h.preview({**plan, "source": "Noted."}, error="experiment.source")
        h.preview(plan)

        approval = {"type": "approve-experiment", "initiative": h.i, "metric": plan["metric"]}
        draft = h.trace()["initiative"]["experiment_drafts"][plan["metric"]]
        path = h.work / draft["path"]
        details = {**json.loads(path.read_text()), **{key: plan[key] for key in draft["missing"]}}
        for criterion, reason in (("As above.", "needs a concrete answer"),
                                  (plan["method"].lower() + ".", "needs a decision rule distinct from the test method")):
            path.write_text(json.dumps({**details, "criterion": criterion}))
            h.cli("check")
            h.preview(approval, error=f"experiment.criterion {reason}")
        path.write_text(json.dumps(details))
        h.submit(approval)
        self.assertFalse(path.exists())

    def test_historical_experiment_with_weak_criterion_is_readable(self):
        h = self.hub
        self.capture()
        hypothesis, plan, result, _ = h.evidence()
        h.submit(hypothesis, plan)

        envelope = json.loads(h.ledger.read_text())
        event = next(event for event in envelope["record"]["events"] if event["type"] == "experiment")
        event["criterion"] = "Noted."
        h.write_legacy_register(envelope["record"])

        h.cli("check")
        self.assertEqual(h.trace()["initiative"]["experiments"][plan["experiment"]]["criterion"], "Noted.")
        h.submit(result)
