"""Exercise the signed scope of an active discovery plan through the normal CLI."""

import hashlib
import json
import os
import unittest
from unittest.mock import patch

import test_opportunities
import initiative_store


class DiscoverySourceTests(unittest.TestCase):
    def setUp(self):
        self.hub = test_opportunities.InitiativeTests()
        self.addCleanup(self.hub.doCleanups)
        h = self.hub
        h.setUp()
        h.submit(h.setup_event(), h.capture(), h.describe(), h.evidence()[0], h.decision("evaluate"))
        h.new("discovery-brief", h.discovery)
        self.sections = {
            "Known, assumed, and unknown": "Two customers missed renewals. The cause is unknown.",
            "Learning goals and exit criteria": "Check whether a reminder changes renewal timing.",
            "Approach and timebox": "Interview both customers and review their renewal records this week.",
            "Capacity and review": "One researcher reports back at the product review on Friday.",
        }
        self.source = "Support case 12, customer interview notes, section 2."
        h.fill(h.discovery, {**self.sections, "Sources": self.source}, complete=False)
        self.start = h.decision("start-discovery", review_on=h.today)
        self.finish = h.decision("prepare-brief")

    def test_sources_are_pinned_at_preview_and_in_the_active_plan(self):
        h = self.hub
        initial_proposal = h.preview(self.start)
        original = initial_proposal["reviewed_transactions"][0]["references"]
        self.assertEqual(original["scope"], "plan-and-sources")
        h.fill(h.discovery, {"Sources": "Renewal report, page 4, and support case 12."}, complete=False)
        h.apply(initial_proposal, error="stale or was modified")
        new_proposal = h.preview(self.start)
        new = new_proposal["reviewed_transactions"][0]["references"]
        self.assertNotEqual(original["sha256"], new["sha256"])
        h.apply(new_proposal)

        h.fill(h.discovery, {"Findings and recommendation": "Both customers confirmed the reminder timing gap."})
        self.assertEqual(h.trace()["review_issues"], [])
        h.fill(h.discovery, {"Sources": "Support case 99, replacement evidence."})
        self.assertTrue(any("differs from the reviewed revision" in issue for issue in h.trace()["review_issues"]))
        h.preview(self.finish, error="Authorize the revised timebox")
        h.submit(self.start)
        h.submit(h.evidence()[3], self.finish)
        self.assertEqual(h.trace()["initiative"]["phase"], "defining")

    def test_embedded_headings_cannot_hide_following_citations(self):
        h = self.hub
        path = h.work / h.discovery
        original = path.read_text()
        for opening, closing in (("```markdown", "```"), ("<!--", "-->")):
            with self.subTest(opening=opening):
                source = f"{self.source}\n\n{opening}\n## Example\n{closing}\n\n### Interview notes\nInterview 21, page 4."
                ambiguous = original.replace(self.source, source)
                path.write_text(ambiguous)
                h.preview(self.start, error="indent example headings")

                bound = ambiguous.replace("## Example", "    ## Example")
                path.write_text(bound)
                h.submit(self.start)
                self.assertEqual(h.trace()["review_issues"], [])
                path.write_text(bound.replace("Interview 21, page 4.", "Unreviewed interview 28, page 2."))
                self.assertTrue(any("differs from the reviewed revision" in issue for issue in h.trace()["review_issues"]))
                path.write_text(ambiguous.replace("Interview 21, page 4.", "Unreviewed interview 28, page 2."))
                self.assertTrue(any("ambiguous discovery section boundary" in issue for issue in h.trace()["review_issues"]))

    def test_previously_signed_timebox_reads_but_needs_new_source_approval_to_conclude(self):
        h = self.hub
        h.submit(self.start)
        # Sign the original three-field reference and four-section digest as an older Hub did.
        envelope = json.loads(h.ledger.read_text())
        reference = envelope["record"]["events"][-1]["references"]
        del reference["scope"]
        previous_bytes = json.dumps(list(self.sections.values()), separators=(",", ":")).encode("utf-8")
        reference["sha256"] = hashlib.sha256(previous_bytes).hexdigest()
        with patch.dict(os.environ, h.env):
            envelope["signature"] = initiative_store.sign(h.root, envelope["record"], h.key)
        h.ledger.write_text(json.dumps(envelope))
        self.assertEqual(h.trace()["review_issues"], [])
        h.fill(h.discovery, {"Sources": "Updated renewal log after the older timebox began."}, complete=False)
        self.assertEqual(h.trace()["review_issues"], [])
        h.preview(self.finish, error="sign start-discovery before prepare-brief")

        proposal = h.preview(self.start)
        del proposal["reviewed_transactions"][0]["references"]["scope"]
        h.apply(proposal, error="stale or was modified")
        h.submit(self.start)
        self.assertEqual(h.trace()["initiative"]["discovery"][1]["scope"], "plan-and-sources")
        h.fill(h.discovery, {"Findings and recommendation": "Renewal log and interviews support a reminder pilot."})
        h.submit(h.evidence()[3], self.finish)
        self.assertEqual(h.trace()["review_issues"], [])
