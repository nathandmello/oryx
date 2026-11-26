"""Exercise the reviewed scope of an active discovery plan through the normal CLI."""

import hashlib
import json
import unittest

import test_opportunities


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

    def test_workspace_sections_survive_template_removal_and_are_approved(self):
        h = self.hub
        change = {"templates": {"discovery-brief": {
            "Interview protocol": {"prompt": "Record the protocol."},
            "Approach and timebox": {"mode": "replace", "content": "| Method | Interviews |"}}}}
        def configure(patch):
            revision = json.loads(h.cli("customize", "show"))["revision"]
            h.cli("customize", "apply", value={"revision": revision, "config": patch})
        configure(change)
        (h.work / h.discovery).unlink()
        h.new("discovery-brief", h.discovery)
        h.fill(h.discovery, {**{k: v for k, v in self.sections.items() if k != "Approach and timebox"},
                             "Sources": self.source, "Interview protocol": "Use a common script."}, complete=False)
        h.preview(self.start, error="needs content in Approach and timebox")
        h.fill(h.discovery, {"Approach and timebox": self.sections["Approach and timebox"]}, complete=False)
        proposal = h.preview(self.start)
        self.assertEqual(proposal["reviewed_transactions"][0]["references"]["scope"], "plan-sources-and-custom-sections")
        h.apply(proposal)
        configure({"templates": None})
        self.assertEqual(h.trace()["review_issues"], [])
        h.fill(h.discovery, {"Interview protocol": "Use a revised sampling protocol.",
                             "Findings and recommendation": "Two interviews support a reminder pilot."})
        h.preview(self.finish, error="Authorize the revised timebox")
        h.submit(self.start)
        h.submit(h.evidence()[3], self.finish)
        self.assertEqual(h.trace()["review_issues"], [])

    def test_embedded_headings_cannot_hide_following_citations(self):
        h = self.hub
        path = h.work / h.discovery
        original = path.read_text()
        # Findings may be absent before the timebox starts.
        findings = original.index("## Findings and recommendation")
        original = original[:findings] + original[original.index("## Sources", findings):]
        for opening, closing in (("```markdown", "```"), ("<!--", "-->"), ("<pre>", "</pre>")):
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
        h.write_legacy_register(envelope["record"])
        self.assertEqual(h.trace()["review_issues"], [])
        h.fill(h.discovery, {"Sources": "Updated renewal log.\n\n<pre>\n## Example\n</pre>\nLost interview 91."},
               complete=False)
        self.assertEqual(h.trace()["review_issues"], [])
        h.preview(self.finish, error="start-discovery before prepare-brief")
        h.preview(self.start, error="indent example headings")
        path = h.work / h.discovery
        path.write_text(path.read_text().replace("## Example", "    ## Example"))

        proposal = h.preview(self.start)
        del proposal["reviewed_transactions"][0]["references"]["scope"]
        h.apply(proposal, error="stale or was modified")
        h.submit(self.start)
        self.assertEqual(h.trace()["initiative"]["discovery"][1]["scope"], "plan-and-sources")
        h.fill(h.discovery, {"Findings and recommendation": "Renewal log and interviews support a reminder pilot."})
        h.submit(h.evidence()[3], self.finish)
        self.assertEqual(h.trace()["review_issues"], [])
