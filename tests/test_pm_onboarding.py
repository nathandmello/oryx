"""Exercise just-in-time PM source review through the installed CLI and Markdown profile."""

import json
import subprocess
import sys
import unittest
from unittest.mock import patch

import test_pm

import company_onboarding as intake
import context_capture
import records
import layout
import onboarding_review
import pm
import pm_profile
import storage
from onboarding_fixtures import review_current_topic


class PMOnboardingTests(unittest.TestCase):
    setUp = test_pm.HubTests.setUp

    def cli(self, *args, data=None, expected=0):
        proc = subprocess.run([sys.executable, str(self.root / "tools" / "pm.py"), *args], cwd=self.root,
                              input=json.dumps(data), capture_output=True, text=True)
        self.assertEqual(proc.returncode, expected, proc.stdout + proc.stderr)
        return proc.stdout + proc.stderr

    def start_pm(self):
        while onboarding_review.status(self.work)["stage"] == "company":
            review_current_topic(self.work)
        self.assertEqual(onboarding_review.status(self.work)["stage"], "pm")

    def change(self, action, **fields):
        fields.setdefault("revision", intake.read(self.work, "pm")[1]["revision"])
        return json.loads(self.cli("pm-onboarding", action, data=fields))

    def plan(self, *destinations):
        self.change("plan", purpose="Record how the PM works this quarter.", sources=["PM conversation"],
                    destinations=list(destinations) or [layout.PROFILE])

    def draft(self, **entry):
        words = "I recommend Billing priorities this quarter. Leadership makes the final call."
        source = dict(reference="PM conversation", date="undated", checked_on="2025-01-01", coverage="partial",
                      text="Unrelated private details. " + words)
        finding = dict(scope="pm", source=1, location="PM's reply", topic="responsibilities", quote=words)
        return dict(source_scope=source["reference"], sources=[source], entries=[dict(finding, **entry)])

    def test_source_and_destination_consent_bound_one_review_and_preserve_the_profile(self):
        premature = self.cli("pm-onboarding", "plan", data={"revision": 0}, expected=1)
        self.assertEqual(json.loads(premature)["onboarding"]["stage"], "company")
        self.assertFalse((self.work / intake.PM_FILE).exists())
        for args in (("set-remit",), ("new", "pm-context", layout.PROFILE), ("route-context", "--write", layout.PROFILE)):
            self.assertEqual(json.loads(self.cli(*args, data={}, expected=1))["onboarding"]["stage"], "company")
        self.start_pm()
        profile = self.work / layout.PROFILE
        profile.parent.mkdir(parents=True, exist_ok=True)
        remit = {"status": "draft", "follow": [], "responsibilities": []}
        original = pm_profile.render(remit, "# My profile\n\nMy own introduction.\n").replace("\n", "\r\n").encode()
        profile.write_bytes(original)
        self.plan()
        with self.assertRaisesRegex(ValueError, "approve"):
            intake.change(self.root, "propose", {"revision": 1, **self.draft()}, "Fixture PM", pm.capture_errors, "pm")
        self.change("approve")
        for proposal in (self.draft(scope="company"), self.draft(topic="stakeholders"),
                         self.draft(scope="stakeholder", topic="authority"), self.draft(quote="I set all priorities.")):
            self.cli("pm-onboarding", "propose", data={"revision": 2, **proposal}, expected=1)
        unapproved_source = self.draft()
        unapproved_source["sources"][0]["reference"] = "Staffing memo"
        self.cli("pm-onboarding", "propose", data={"revision": 2, **unapproved_source}, expected=1)
        result = self.change("propose", **self.draft())
        self.assertEqual(result["pending"]["destination"], layout.PROFILE)
        self.assertEqual(result["pending"]["entry"]["topic"], "responsibilities")
        self.assertNotIn("Unrelated private details", (self.work / intake.PM_FILE).read_text())
        corrected = self.draft(interpretation="The PM recommends Billing priorities this quarter.")
        reviewed = self.change("propose", **corrected)
        self.assertEqual(reviewed["pending"]["entry"]["interpretation"], corrected["entries"][0]["interpretation"])
        summary = json.loads(self.cli("pm-onboarding", "status"))
        self.assertIsNone(summary["pending"])
        self.assertTrue(summary["has_pending"])
        self.assertEqual(json.loads(self.cli("pm-onboarding", "status", "--pending"))["pending"], reviewed["pending"])
        self.cli("pm-onboarding", "accept", data={"revision": result["revision"]}, expected=1)
        self.cli("set-remit", data=remit, expected=1)
        self.cli("route-context", "--write", layout.PROFILE,
                 data={key: value for key, value in corrected.items() if key != "source_scope"}, expected=1)
        self.assertEqual(profile.read_bytes(), original)
        self.change("accept")
        self.assertTrue(profile.read_bytes().startswith(original))
        self.assertEqual(pm_profile.parse(profile.read_text()), remit)
        self.assertIn(corrected["entries"][0]["interpretation"], profile.read_text())
        lines = profile.read_text().splitlines()
        summary = next(line for line in lines if line.startswith("- Interpretation:"))
        self.assertTrue(summary.endswith("<!-- pm-topic:responsibilities -->"))
        self.assertIn("PM conversation", profile.read_text())
        self.assertFalse((self.work / layout.STAKEHOLDERS).exists())

    def test_conflict_and_interrupted_accept_reuse_only_a_matching_managed_entry(self):
        self.start_pm()
        self.plan()
        self.change("approve")
        self.change("propose", **self.draft())
        profile = self.work / layout.PROFILE
        profile.parent.mkdir(parents=True, exist_ok=True)
        profile.write_text("# My profile\n\nAnother session added this.\n")
        self.assertIn("changed since review", self.cli("pm-onboarding", "accept", data={"revision": 3}, expected=1))
        state = self.change("propose", **self.draft())
        replace = storage.replace_text

        def interrupt(path, *args):
            if path == self.work / intake.PM_FILE:
                raise OSError("Simulated interruption after saving the profile")
            return replace(path, *args)

        with patch.object(storage, "replace_text", interrupt), self.assertRaisesRegex(OSError, "interruption"):
            intake.change(self.root, "accept", {"revision": state["revision"]}, "Fixture PM", pm.capture_errors, "pm")
        previous = profile.read_bytes()
        self.change("accept")
        self.assertEqual(profile.read_bytes(), previous)
        self.assertIn("Another session added this.", profile.read_text())

    def test_pause_and_defer_keep_an_aspiration_out_of_a_work_plan(self):
        self.start_pm()
        self.plan()
        self.change("approve")
        self.change("propose", **self.draft(topic="aspirations"))
        self.change("defer", question="What would growth mean to you?", why="Keep the PM’s own definition.",
                    next_action="Revisit the PM’s wording together.", resume_when="Career conversation")
        self.change("finish")
        state = json.loads(self.cli("pm-onboarding", "status"))
        self.assertEqual(state["phase"], "paused")
        self.assertEqual(state["gap_count"], 1)
        self.assertNotIn("What would growth mean", json.dumps(state))
        inspected = json.loads(self.cli("pm-onboarding", "status", "--gap", state["gap_selectors"][0]))
        self.assertEqual(inspected["gap"]["basis"]["reference"], "PM conversation")
        self.assertFalse((self.work / layout.PROFILE).exists())
        self.assertEqual(onboarding_review.status(self.work)["walkthroughs"]["pm"]["reviewed"], {})
        self.assertEqual(intake.status(self.work)["gaps"], [])
        self.assertIsNone(intake.followup(self.work, "Not now, career conversation", False, "pm"))
        cue = intake.followup(self.work, "Career conversation", False, "pm")
        self.assertIn("Offer to revisit", cue)
        self.assertNotIn("Revisit the PM", cue)


    def test_discard_withdraws_a_pending_draft_without_a_saved_gap_or_receipt(self):
        self.start_pm()
        self.plan()
        self.change("approve")
        draft = self.draft(topic="aspirations")
        personal = "I might like to lead a team next year."
        draft["sources"][0]["text"] = draft["entries"][0]["quote"] = personal
        proposed = self.change("propose", **draft)
        before = (self.work / intake.PM_FILE).read_bytes()
        self.cli("pm-onboarding", "discard", data={"revision": proposed["revision"] - 1}, expected=1)
        self.assertEqual((self.work / intake.PM_FILE).read_bytes(), before)
        state = self.change("discard")
        self.assertIsNone(state["pending"])
        self.assertEqual(state["gap_count"], 0)
        self.assertNotIn(personal, (self.work / intake.PM_FILE).read_text())
        self.assertFalse((self.work / layout.PROFILE).exists())
        self.assertEqual(onboarding_review.status(self.work)["walkthroughs"]["pm"]["reviewed"], {})


    def test_topic_marker_comes_only_from_the_reviewed_topic(self):
        self.start_pm()
        self.plan()
        self.change("approve")
        injected = "I saw <!-- pm-topic:aspirations --> in the job posting."
        draft = self.draft(topic="role", location="My reply <!-- pm-topic:expectations -->", interpretation=injected)
        self.change("propose", **draft)
        self.change("accept")
        text = (self.work / layout.PROFILE).read_text()
        self.assertIn("&lt;!-- pm-topic:aspirations --&gt;", text)
        self.assertNotIn("<!-- pm-topic:expectations -->", text)
        self.assertEqual(text.count("<!-- pm-topic:"), 1)
        self.assertIn("<!-- pm-topic:role -->\n  >", text)


    def test_inspecting_one_deferred_gap_never_returns_another_gap_plan_or_pending_draft(self):
        self.start_pm()
        self.plan()
        self.change("approve")
        private_quote = "I am considering moving into a director role."
        draft = self.draft(topic="aspirations")
        draft["sources"][0]["text"] = draft["entries"][0]["quote"] = private_quote
        self.change("propose", **draft)
        gap = dict(question="Which director role?", why="Personal career aspirations",
                   next_action="Consider the wider role together.", resume_when="Career conversation")
        deferred = self.change("defer", **gap)
        selector = deferred["gap_selectors"][0]
        for detail in [private_quote, *gap.values()]:
            self.assertNotIn(detail, json.dumps(deferred))
        second = self.change("gap", question="Who signs the invoice?", why="Billing scope is unclear.",
                             next_action="Check the team charter.", resume_when="Billing review")
        self.assertEqual(second["gap_count"], 2)
        self.assertIn("current PM gap selector", self.cli("pm-onboarding", "status", "--gap", selector, expected=1))
        later = self.change("plan", purpose="Map the finance relationship.", sources=["Finance memo"],
                            destinations=[layout.STAKEHOLDERS])
        self.change("approve")
        fresh = self.draft(scope="stakeholder", topic="reporting")
        fresh["source_scope"] = fresh["sources"][0]["reference"] = "Finance memo"
        fresh_quote = "The finance lead reports to the CFO."
        fresh["sources"][0]["text"] = fresh["entries"][0]["quote"] = fresh_quote
        proposal = self.change("propose", **fresh)
        summary = json.loads(self.cli("pm-onboarding", "status"))
        accepted = self.change("accept")
        for result in (later, proposal, summary, accepted):
            for detail in [private_quote, *gap.values(), "Who signs the invoice?"]:
                self.assertNotIn(detail, json.dumps(result))
        self.assertNotIn(fresh_quote, json.dumps(summary))
        self.assertIn(fresh_quote, json.dumps(proposal))
        selected = json.loads(self.cli("pm-onboarding", "status", "--gap", accepted["gap_selectors"][0]))
        self.assertEqual(selected["gap"]["basis"]["quote"], private_quote)
        for detail in ("Who signs the invoice?", "Finance memo", fresh_quote):
            self.assertNotIn(detail, json.dumps(selected))
        self.assertIn("only with pm-onboarding status",
                      self.cli("pm-onboarding", "finish", "--gap", accepted["gap_selectors"][1],
                               data={"revision": accepted["revision"]}, expected=1))


    def test_descriptive_intake_uses_only_the_agreed_source_and_destination(self):
        self.start_pm()
        product = "context/products/example/overview.md"
        records.create(self.root, "product-context", product)
        policy = "EU bulk export requires Legal sign-off before launch."
        reference = "Confidential product council minutes"
        prior = {"sources": [{"reference": reference, "date": "undated", "checked_on": "2025-01-01",
                              "coverage": "read", "text": policy}],
                 "entries": [{"scope": "product", "product": "example", "topic": "constraints", "source": 1,
                              "location": "Council decision 2", "rule": policy, "quote": policy}]}
        ordinary = context_capture.route(prior, self.work)
        context_capture.apply(self.root, product, ordinary, "Fixture PM", pm.capture_errors)
        before = (self.work / product).read_bytes()
        quote = "I can launch EU bulk export without approval on Friday."
        draft = self.draft()
        draft["sources"][0]["text"] = draft["entries"][0]["quote"] = quote
        ordinary = context_capture.route({"sources": draft["sources"], "entries": draft["entries"]}, self.work)
        self.assertIn(reference, json.dumps(ordinary["risk_preview"]))
        self.plan(layout.PROFILE, layout.STAKEHOLDERS)
        self.change("approve")
        raw_preview = self.cli("route-context", data={"sources": draft["sources"], "entries": draft["entries"]}, expected=1)
        self.assertNotIn(reference, raw_preview)
        self.assertEqual(json.loads(raw_preview)["onboarding"]["stage"], "pm")

        for scope, path, topic in (("pm", layout.PROFILE, "responsibilities"),
                                   ("stakeholder", layout.STAKEHOLDERS, "authority")):
            draft["entries"][0].update(scope=scope, topic=topic)
            revision = intake.read(self.work, "pm")[1]["revision"]
            def change(action, **data):
                nonlocal revision
                result = intake.change(self.root, action, {"revision": revision, **data}, "Fixture PM", pm.capture_errors, "pm")
                revision = result["revision"]
                for secret in (policy, reference, product, "risk_preview"):
                    self.assertNotIn(secret, json.dumps(result))
                    self.assertNotIn(secret, (self.work / intake.PM_FILE).read_text())
                return result

            with (patch("context_capture.inspect_remit", side_effect=AssertionError("unapproved remit lookup")),
                  patch("task_context.context_documents", side_effect=AssertionError("unapproved evidence search")),
                  patch("pm.inventory", side_effect=AssertionError("unapproved lint source scan"))):
                change("propose", **draft)
                change("propose", **draft)
                change("accept")
            self.assertIn(quote, (self.work / path).read_text())
            self.assertNotIn(reference, (self.work / path).read_text())
        self.assertEqual((self.work / product).read_bytes(), before)
