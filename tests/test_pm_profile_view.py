"""Profile lookups scope personal material to one explicit request."""

import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import context_capture
import pm_profile
import pm_profile_view
import test_onboarding_commands
from onboarding_fixtures import review_current_topic


class ProfileLookupTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.private = Path(temp.name).resolve()
        self.path = self.private / pm_profile.PATH
        self.path.parent.mkdir(parents=True)

    def test_index_and_single_section_keep_notes_and_locally_numbered_sources_separate(self):
        captured = """
## PM background

- I recommend Billing priorities. [S1] Role review
- I speak to the review group. [S3] Team roster

## Other PM context

- I aspire to lead a new product. [S2] Growth conversation

## Sources

| ID | Source | Source date | Checked on |
| --- | --- | --- | --- |
| S1 | Remit conversation | unknown | 2026-10-01 |
| S2 | Personal development note | unknown | 2026-10-01 |
<!-- source-coverage:S1:partial:2026-10-01 -->
"""
        manual = "# My context\n\nA short introduction.\n\n## My team\n\nI work on pricing. [S1]\n"
        tail = ("\n## Sources\n\n| ID | Source | Source date | Checked on |\n| --- | --- | --- | --- |\n"
                "| S1 | Manager note | unknown | 2026-11-01 |\n")
        original = manual + pm_profile.CAPTURE_START + "\n" + captured + pm_profile.CAPTURE_END + "\n" + tail
        self.path.write_text(original)
        index = pm_profile_view.view(self.private)
        self.assertEqual(index["profile"], pm_profile.PATH)
        self.assertEqual(index["sections"], ["Overview", "My team", "PM background", "Other PM context", "Sources"])
        self.assertNotIn("aspire", json.dumps(index))
        self.assertNotIn("Personal development", json.dumps(index))
        background = pm_profile_view.view(self.private, "PM background")
        self.assertNotIn("sections", background)
        part, = background["passages"]
        self.assertIn("recommend Billing priorities", part["text"])
        self.assertEqual([row["Source"] for row in part["sources"]], ["Remit conversation"])
        self.assertEqual(part["sources"][0]["coverage"], "partial")
        self.assertIn("source_notice", part)
        self.assertNotIn("aspire", json.dumps(background))
        manually_written = pm_profile_view.view(self.private, "My team")["passages"][0]
        self.assertEqual(manually_written["sources"][0]["Source"], "Manager note")
        self.assertIn("underlying question open", pm_profile_view.view(self.private, "Other role")["lookup"])
        self.assertEqual(self.path.read_text(), original)

    def test_topic_only_returns_explicitly_reviewed_entries_and_their_citations(self):
        def rendered(topic, statement, source, location):
            return context_capture.render_entry({"scope": "pm", "topic": topic, "quote": statement,
                                                 "location": location}, source)

        work = rendered("responsibilities", "I recommend Billing priorities.", "S1", "Role review")
        aspiration = rendered("aspirations", "I want to manage a team.", "S2", "Career discussion")
        unrelated = "- Fact: An old untagged entry. [S3] (Prior conversation)"
        source_rows = ("## Sources\n\n| ID | Source | Source date | Checked on |\n| --- | --- | --- | --- |\n"
                       "| S1 | Product charter | 2026-06-01 | 2026-06-01 |\n"
                       "| S2 | Confidential career discussion | unknown | 2026-06-02 |\n"
                       "| S3 | Older summary | unknown | 2026-06-02 |")
        captured = f"## Other PM context\n\n{work}\n{aspiration}\n{unrelated}\n\n{source_rows}"
        self.path.write_text(f"# My context\n\n{pm_profile.CAPTURE_START}\n{captured}\n{pm_profile.CAPTURE_END}\n")
        result = pm_profile_view.view(self.private, topic="responsibilities")
        part, = result["passages"]
        self.assertIn("recommend Billing priorities", part["text"])
        self.assertNotIn("pm-topic:", part["text"])
        self.assertEqual([s["Source"] for s in part["sources"]], ["Product charter"])
        for private_value in ("manage a team", "Confidential career discussion", "Older summary", "old untagged entry"):
            self.assertNotIn(private_value, json.dumps(result))
        empty = pm_profile_view.view(self.private, topic="expectations")
        self.assertEqual(empty["passages"], [])
        self.assertIn("question open", empty["lookup"])
        self.assertNotIn("remit", empty)

    def test_responsibility_topic_includes_only_recorded_remit_rows_and_status(self):
        row = {"subject": "product/billing", "role": "shared", "depends_on": ["area/finance"], "goals": []}
        remit = {"status": "confirmed", "responsibilities": [row], "follow": ["topic/private-interest"]}
        self.path.write_text(pm_profile.render(remit) + "\n## Personal notes\n\nPrivate career conversation.\n")
        result = pm_profile_view.view(self.private, topic="responsibilities")
        self.assertEqual(result["remit"], {"status": "confirmed", "responsibilities": [row]})
        self.assertEqual(result["profile"], pm_profile.PATH)
        self.assertNotIn("lookup", result)
        self.assertNotIn("private-interest", json.dumps(result))
        self.assertNotIn("Private career", json.dumps(result))
        self.assertNotIn("remit", pm_profile_view.view(self.private, topic="aspirations"))
        self.path.unlink()
        legacy = self.private / pm_profile.LEGACY
        for status in ("draft", None):
            data = dict(remit)
            if status:
                data["status"] = status
            else:
                del data["status"]
            legacy.write_text(json.dumps(data))
            with self.subTest(status=status):
                result = pm_profile_view.view(self.private, topic="responsibilities")
                self.assertEqual(result["profile"], pm_profile.LEGACY)
                self.assertEqual(result["remit"]["responsibilities"], [row])
                self.assertEqual(result["remit"]["status"], status or "unrecorded")
                self.assertIn("Confirm", result["remit"]["notice"])
                self.assertNotIn("lookup", result)
                self.assertNotIn("private-interest", json.dumps(result))
        legacy.write_text(json.dumps(dict(remit, responsibilities=[])))
        empty = pm_profile_view.view(self.private, topic="responsibilities")
        self.assertEqual(empty["remit"]["responsibilities"], [])
        self.assertIn("question open", empty["lookup"])

    def test_structured_or_legacy_remit_a_symlink_and_missing_record(self):
        self.assertIsNone(pm_profile_view.view(self.private)["profile"])
        remit = {"status": "draft", "responsibilities": [], "follow": ["topic/health"]}
        self.path.write_text(pm_profile.render(remit))
        self.assertEqual(pm_profile_view.view(self.private, "PM remit")["remit"], remit)
        self.assertNotIn("topic/health", json.dumps(pm_profile_view.view(self.private)))
        self.path.unlink()
        legacy = self.private / pm_profile.LEGACY
        legacy.write_text(json.dumps(remit))
        self.assertEqual(pm_profile_view.view(self.private, "PM remit")["remit"], remit)
        self.path.symlink_to(legacy)
        with self.assertRaisesRegex(ValueError, "regular private file"):
            pm_profile_view.view(self.private)


class ProfileLookupRoutingTests(unittest.TestCase):
    setUp = test_onboarding_commands.OnboardingCommandTests.setUp
    cli = test_onboarding_commands.OnboardingCommandTests.cli

    def test_existing_profile_waits_for_company_walkthrough_then_reads_while_product_pending(self):
        profile = self.work / pm_profile.PATH
        profile.parent.mkdir(parents=True, exist_ok=True)
        profile.write_text("# PM context\n\n## Role\n\nI recommend Billing priorities.\n")
        self.assertEqual(self.cli("pm-profile", ok=False)["onboarding"]["stage"], "company")
        self.assertEqual(self.cli("action", "context", "pm", "show", ok=False)["onboarding"]["stage"], "company")
        while self.cli("onboarding", "status")["stage"] == "company":
            review_current_topic(self.work)
        self.assertEqual(self.cli("pm-profile")["sections"], ["Role"])
        self.assertEqual(self.cli("action", "context", "pm", "show", "--topic", "responsibilities")["passages"], [])
        self.assertEqual(self.cli("action", "context", "pm", "show", "--section", "Role")["passages"][0]["text"],
                         "I recommend Billing priorities.")
        while self.cli("onboarding", "status")["stage"] == "pm":
            review_current_topic(self.work)
        self.assertEqual(self.cli("onboarding", "status")["stage"], "product")
        self.assertEqual(self.cli("pm-profile")["sections"], ["Role"])
