"""One PM-reviewed claim moves from a scoped source plan to reusable context."""

import json
import subprocess
import sys
import unittest
from unittest.mock import patch

import test_pm

import company_onboarding as onboarding
import context_capture
import pm
import storage


class CompanyOnboardingTests(unittest.TestCase):
    setUp = test_pm.HubTests.setUp

    def change(self, operation, **kwargs):
        kwargs.setdefault("revision", onboarding.status(self.work)["revision"])
        return onboarding.change(self.root, operation, kwargs, "Fixture PM", pm.capture_errors)

    def plan(self):
        return self.change("plan", purpose="Establish the company's customer segments",
                           sources=["Board deck", "https://docs.test/finance/"])

    def draft(self, reference="Board deck"):
        quote = "Enterprise is an opportunity to explore."
        source = {"reference": reference, "date": "undated", "coverage": "partial",
                  "checked_on": "2025-01-01", "text": "Unrelated details. " + quote}
        entry = {"source": 1, "scope": "company", "topic": "markets", "quote": quote, "location": "Slide 2"}
        return {"source_scope": "Board deck", "sources": [source], "entries": [entry]}

    def test_plan_correction_and_idempotent_accept_after_interruption(self):
        self.assertEqual(onboarding.status(self.work)["phase"], "welcome")
        plan = self.plan()
        item = self.draft()
        with self.assertRaisesRegex(ValueError, "approve"):
            self.change("propose", **item)
        self.change("approve")
        first = self.change("propose", **item)
        self.assertNotIn("Unrelated details", (self.work / onboarding.FILE).read_text())
        with self.assertRaisesRegex(ValueError, "stale"):
            self.change("accept", revision=plan["revision"])
        self.assertFalse((self.work / "context/company/overview.md").exists())
        item["entries"][0]["location"] = "Slide 2, possible future markets"
        corrected = self.change("propose", **item)
        with self.assertRaisesRegex(ValueError, "stale"):
            self.change("accept", revision=first["revision"])
        write = storage.replace_text

        def interrupt(target, original, candidate, **kwargs):
            if target == self.work / onboarding.FILE:
                raise OSError("checkpoint unavailable")
            return write(target, original, candidate, **kwargs)

        with patch.object(storage, "replace_text", interrupt), self.assertRaisesRegex(OSError, "checkpoint"):
            self.change("accept")
        self.assertEqual(onboarding.status(self.work)["revision"], corrected["revision"])
        self.change("accept")
        doc = (self.work / "context/company/overview.md").read_text()
        self.assertEqual(doc.count("  > Enterprise is an opportunity to explore."), 1)
        self.assertIn("Slide 2, possible future markets", doc)
        self.assertNotIn("opportunity to explore", (self.work / onboarding.FILE).read_text())
        self.assertEqual(self.change("finish")["phase"], "existing")
        self.assertEqual(pm.check(self.root), [])

    def test_scope_and_ownership(self):
        self.plan()
        self.change("approve")
        item = self.draft()
        for bad in ("Slack thread", "[Slides](https://outside.test/slide.pdf)"):
            item["sources"][0]["reference"] = bad
            with self.assertRaisesRegex(ValueError, "outside"):
                self.change("propose", **item)
        base = "https://docs.test/finance/"
        item["source_scope"] = base
        for bad in ("https://docs.test/other/doc", base + "../doc", base + "%2E%2E/doc", "https://evil.test/finance/doc"):
            item["sources"][0]["reference"] = bad
            with self.assertRaisesRegex(ValueError, "outside"):
                self.change("propose", **item)
        item["sources"][0]["reference"] = "[Finance deck](https://docs.test/finance/doc)"
        self.change("propose", **item)
        item["entries"][0]["topic"] = "decisions"
        with self.assertRaisesRegex(ValueError, "decision"):
            self.change("propose", **item)
        item = self.draft()
        item["sources"][0]["text"] = "We will prioritize field services only if the pilot succeeds."
        item["entries"][0]["quote"] = "We will prioritize field services"
        with self.assertRaisesRegex(ValueError, "qualifications"):
            self.change("propose", **item)
        item["entries"][0]["quote"] = "The company has committed to enterprise."
        with self.assertRaisesRegex(ValueError, "differs"):
            self.change("propose", **item)

    def test_resume_and_defer_do_not_write_or_lose_existing_drafts(self):
        self.plan()
        self.change("approve")
        self.change("propose", **self.draft())
        gap = dict(question="Has leadership chosen enterprise?", why="This changes who the roadmap serves.",
                   next_action="Review the new operating plan together.", resume_when="Next operating review")
        result = self.change("defer", **gap)
        self.assertEqual(result["gaps"][0]["basis"]["reference"], "Board deck")
        self.assertEqual(result["gaps"][0]["question"], gap["question"])
        self.assertEqual(self.change("finish")["phase"], "paused")
        command = [sys.executable, str(self.root / "tools/pm.py"), "company-onboarding", "status"]
        resumed = subprocess.run(command, capture_output=True, check=True, text=True)
        self.assertEqual(json.loads(resumed.stdout)["gaps"], result["gaps"])
        cue = onboarding.followup(self.work, "I finished the operating review.", company_scope=False)
        self.assertIn(gap["next_action"], cue)
        self.assertNotIn("Board deck", cue)
        self.assertNotIn(self.draft()["entries"][0]["quote"], cue)
        self.assertEqual(json.loads(resumed.stdout)["gaps"][0]["basis"]["quote"], self.draft()["entries"][0]["quote"])
        self.assertFalse((self.work / context_capture.COMPANY_PATH).exists())

    def test_founder_can_revisit_a_hypothesis_after_the_company_pass(self):
        def cli(*args, payload=None):
            result = subprocess.run([sys.executable, str(self.root / "tools/pm.py"), *args],
                                    input=json.dumps(payload), text=True, capture_output=True, check=True)
            return json.loads(result.stdout)

        def preview(reference, day, location, quote, **fields):
            self.change("plan", purpose="Understand how independent clinics follow up on unpaid invoices.",
                        sources=[reference])
            self.change("approve")
            return self.change("propose", source_scope=reference, sources=[{
                "reference": reference, "date": day, "checked_on": day, "coverage": "partial", "text": quote,
            }], entries=[{
                "scope": "company", "topic": "markets", "source": 1, "quote": quote, "location": location, **fields,
            }])

        brief = self.work / context_capture.COMPANY_PATH
        belief = "I think independent clinics lose track of unpaid invoices."
        question = "How common is missed follow-up among independent clinics?"
        first = preview("Founder setup conversation", "2025-03-03", "Founder's opening account", belief,
                        interpretation="Founder hypothesis about unpaid invoice follow-up.", uncertainty=question)
        self.assertFalse(brief.exists())
        self.change("accept", revision=first["revision"])
        self.change("gap", question=question, why="The founder is choosing whom to serve.",
                    next_action="Review the founder's first clinic conversation.", resume_when="First clinic conversation")
        self.change("finish")

        walkthrough = cli("onboarding", "status")
        for topic, outcome, reply in (
            ("customers", "open", belief),
            ("economics", "open", "I haven't chosen a business model."),
            ("portfolio", "not_applicable", "I haven't built a product yet."),
            ("growth", "open", "I don't know how I'll reach clinics."),
            ("tradeoffs", "reviewed", "I have time to explore just one customer segment."),
        ):
            self.assertEqual(walkthrough["walkthroughs"]["company"]["next_topic"]["id"], topic)
            walkthrough = cli("onboarding", "review-topic", payload={
                "revision": walkthrough["revision"], "stage": "company", "topic": topic,
                "outcome": outcome, "pm_reply": reply,
            })
        self.assertEqual(walkthrough["stage"], "pm")
        accepted = brief.read_text()
        self.assertIn("Interpretation: Founder hypothesis", accepted)
        self.assertIn(belief, accepted)

        quote = "At my clinic I check unpaid invoices with a spreadsheet every Friday."
        follow_up = preview("Clinic operator conversation", "2025-03-06", "One operator's account", quote)
        self.assertEqual(brief.read_text(), accepted)
        with self.assertRaisesRegex(ValueError, "exact open question"):
            self.change("resolve", question=question)
        cli("company-onboarding", "accept", payload={"revision": follow_up["revision"]})
        updated = brief.read_text()
        for label in ("Interpretation: Founder hypothesis", belief, "Founder setup conversation", quote,
                      "One operator's account", "Clinic operator conversation", "2025-03-06"):
            self.assertIn(label, updated)
        company = cli("company-onboarding", "status")
        self.assertEqual([gap["question"] for gap in company["gaps"]], [question])
        current = cli("onboarding", "status")
        self.assertEqual(current["walkthroughs"], walkthrough["walkthroughs"])
        self.assertEqual(current["stage"], "pm")
        self.assertFalse(current["ready"])

    def test_separate_current_gap_survives_retrieval_until_reviewed_resolution(self):
        self.plan()
        self.change("approve")
        source = self.draft()
        self.change("propose", **source)
        self.change("accept")
        question = "Has leadership committed to enterprise?"
        self.change("gap", question=question, why="Shapes the segment we target.",
                    next_action="Ask Finance for the operating plan.", resume_when="Next operating review")
        self.change("finish")

        def lookup(prompt):
            return pm.task_context.resolve(self.work, prompt)
        prompt = "Did our company choose enterprise as its priority for the roadmap?"
        result = lookup(prompt)
        self.assertIn(source["entries"][0]["quote"], result["entries"][0]["text"])
        gap, = result["unresolved_company_questions"]
        self.assertEqual(gap["question"], question)
        self.assertEqual(gap["resume_when"], "Next operating review")
        self.assertNotIn("next_action", gap)
        for unrelated in ("How does the company earn its subscription revenue?", prompt + " As of 2025-01-02.",
                          "Does product/checkout target enterprise?", "What was our company selling last year?"):
            self.assertNotIn("unresolved_company_questions", lookup(unrelated))
        self.plan()
        self.change("approve")
        answer = self.draft()
        answer["entries"][0].update(answers=question, quote="The board deferred the enterprise investment.")
        answer["sources"][0]["text"] = answer["entries"][0]["quote"]
        self.change("propose", **answer)
        self.change("resolve", question=question)
        self.assertNotIn("unresolved_company_questions", lookup(prompt))

    def test_plain_capture_cannot_skip_review_and_resolution_requires_evidence(self):
        self.plan()
        self.change("approve")
        source = self.draft()
        route = [sys.executable, str(self.root / "tools/pm.py"), "route-context", "--write", context_capture.COMPANY_PATH]
        payload = {key: source[key] for key in ("sources", "entries")}
        blocked = subprocess.run(route, input=json.dumps(payload), capture_output=True, text=True)
        self.assertNotEqual(blocked.returncode, 0)
        gate = json.loads(blocked.stdout)
        self.assertEqual(gate["status"], "onboarding_required")
        self.assertEqual(gate["onboarding"]["company_phase"], "gather")
        self.assertFalse((self.work / context_capture.COMPANY_PATH).exists())
        plan = context_capture.route(payload, self.work)
        with self.assertRaisesRegex(ValueError, "Review and accept"):
            onboarding.check_capture(self.work, context_capture.COMPANY_PATH, plan)
        self.change("propose", **source)
        gap = {"question": "Has leadership approved enterprise?", "why": "Sets the target market.",
               "next_action": "Check the operating plan.", "resume_when": "New operating plan"}
        self.change("defer", **gap)
        with self.assertRaisesRegex(ValueError, "sourced answer"):
            self.change("resolve", question=gap["question"])
        self.change("plan", purpose="Check the executive decision", sources=["PM and leadership discussion"])
        self.change("approve")
        answer = self.draft("PM and leadership discussion")
        answer["source_scope"] = "PM and leadership discussion"
        answer["entries"][0].update(answers=gap["question"], quote="Leadership is still exploring enterprise.")
        answer["sources"][0].pop("text")
        with self.assertRaisesRegex(ValueError, "inspected source text"):
            self.change("propose", **answer)
        answer["sources"][0]["text"] = "Leadership is still exploring enterprise."
        preview = self.change("propose", **answer)
        self.assertEqual(preview["pending"]["verification"], "reviewed excerpt matched inspected text")
        resolved = self.change("resolve", question=gap["question"])
        self.assertFalse(resolved["gaps"])
        self.assertIn("Leadership is still exploring enterprise.", (self.work / context_capture.COMPANY_PATH).read_text())

    def test_empty_template_and_partial_sources(self):
        path = self.work / context_capture.COMPANY_PATH
        path.parent.mkdir(exist_ok=True, parents=True)
        path.write_text(pm.records.draft_text(self.root, "company-context", path, owner="Fixture PM"))
        self.assertEqual(onboarding.status(self.work)["phase"], "welcome")
        self.plan()
        self.change("approve")
        proposal = self.draft()
        proposal["sources"][0]["text"] += " We will continue serving regional clinics."
        self.assertEqual(self.change("propose", **proposal)["pending"]["verification"],
                         "reviewed excerpt matched inspected text")
        path.write_text(path.read_text() + "\n")
        with self.assertRaisesRegex(ValueError, "changed since review"):
            self.change("accept")

    def test_supplementary_record_retains_source_and_separate_approval(self):
        self.plan()
        self.change("approve")
        self.change("propose", **self.draft())
        self.change("accept")
        parent = (self.work / context_capture.COMPANY_PATH).read_bytes()
        extra = self.draft()
        extra["entries"][0].update(
            quote="Referral fees rose in the regional pilot.",
            record={"path": "context/company/referral-fees.md", "parent": context_capture.COMPANY_PATH,
                    "basis": "maintained-reference", "reason": "Finance consults regional referral fees.",
                    "trigger": "The fee schedule changes."})
        extra["sources"][0]["text"] = extra["entries"][0]["quote"]
        preview = self.change("propose", **extra)["pending"]
        self.assertEqual(preview["destination"], "context/company/referral-fees.md")
        self.assertFalse((self.work / preview["destination"]).exists())
        self.change("accept")
        self.assertEqual((self.work / context_capture.COMPANY_PATH).read_bytes(), parent)
        self.assertIn("Board deck", (self.work / preview["destination"]).read_text())
