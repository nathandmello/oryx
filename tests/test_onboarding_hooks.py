"""Exercise required setup and handoff through the registered agent hooks."""

import json
import unittest

import test_conversation
import test_pm
import hook
import onboarding_review
import layout
import task_context
from onboarding_fixtures import define_fixture_frameworks, review_current_topic


class OnboardingHookTests(unittest.TestCase):
    cli = test_conversation.ConversationTests.cli
    turn = test_conversation.ConversationTests.turn
    prompt = test_conversation.ConversationTests.prompt

    def setUp(self):
        test_pm.HubTests.setUp(self)
        self.cwd = self.root
        self.frameworks = define_fixture_frameworks(self.root)

    def test_each_stage_routes_every_request_then_offers_the_original_task_once(self):
        clients = ("Codex", "Claude")
        for client in clients:
            start = self.turn(client, "SessionStart", client)
            self.assertIn(hook.CANDOR_GUIDANCE, start["hookSpecificOutput"]["additionalContext"])
        requests = {"company": "Build me a Q4 roadmap by morning.",
                    "pm": "/pm portfolio backlog show",
                    "product": "Expedite mode. Put Billing on the roadmap."}
        for stage in ("company", "pm", "product"):
            for topic in self.frameworks[stage]:
                for client in clients:
                    route, guidance = self.prompt(client, client, requests[stage])
                    self.assertIn(hook.CANDOR_GUIDANCE, guidance)
                    self.assertEqual(route["status"], "onboarding_required")
                    state = route["onboarding"]
                    self.assertEqual(state["stage"], stage)
                    self.assertEqual(state["walkthroughs"][stage]["next_topic"], topic)
                    if stage == "pm":
                        self.assertIn("playbook/pm-context.md", guidance)
                        self.assertIn("pm-onboarding status", state["pm_updates"])
                    self.assertNotIn("entries", route)
                    self.assertNotIn("Expedite mode is active", guidance)
                    self.assertNotIn("Use conversation data for continuity", guidance)
                    saved = {"setup_stage": stage}
                    if stage == "product":
                        saved["setup_mode"] = "expedite"
                    self.assertEqual(task_context.previous_scope(self.work, client), saved)
                review_current_topic(self.work)

        self.assertTrue(onboarding_review.status(self.work)["ready"])
        for client in clients:
            route, guidance = self.prompt(client, client, "Thanks!")
            self.assertNotEqual(route.get("status"), "onboarding_required")
            self.assertIn("offer to resume it once", guidance)
            for session in (client, client + "-new-session"):
                result, guidance = self.prompt(client, session, "Show the Billing roadmap")
                self.assertNotEqual(result.get("status"), "onboarding_required")
                self.assertNotIn("offer to resume it once", guidance)

    def test_agreed_company_followup_is_available_between_walkthroughs_and_after_setup(self):
        gap = {"question": "How do independent shops handle deposits?", "why": "Qualify the proposed market.",
               "next_action": "Review one firsthand account.", "resume_when": "After the merchant interviews."}
        self.cli("company-onboarding", "gap", payload={"revision": 0, **gap})
        self.cli("company-onboarding", "plan", payload={
            "revision": 1, "purpose": "Review what one shop told the founder.", "sources": ["Founder conversation"],
        })
        while onboarding_review.status(self.work)["stage"] == "company":
            review_current_topic(self.work)
        manifest = self.root / onboarding_review.MANIFEST
        manifest.write_text(json.dumps(dict(self.frameworks, pm=None)))
        learning = "I finished the merchant interviews. One shop told me how they handle deposits."
        checkpoint = self.work / onboarding_review.FILE
        for stage in ("pending-pm", "pm", "product", "ready"):
            with self.subTest(stage=stage):
                before = checkpoint.read_bytes()
                if stage == "pm":
                    manifest.write_text(json.dumps(self.frameworks))
                expected = self.cli("task-context", learning)
                for client in ("Codex", "Claude"):
                    route, _ = self.prompt(client, client, learning)
                    if stage == "ready":
                        self.assertIn(gap["next_action"], route["conversation"]["company_followup"])
                        self.assertEqual(route["conversation"]["company_followup"],
                                         expected["conversation"]["company_followup"])
                    else:
                        self.assertEqual(route["onboarding"], expected["onboarding"])
                        state = route["onboarding"]
                        self.assertIn(gap["next_action"], state["company_followup"])
                        self.assertIn("Check whether the cue occurred", state["company_followup"])
                        self.assertEqual(state["company_phase"], "plan")
                        self.assertIn("proposed source plan", state["capture_next_action"])
                        self.assertIn("hypothesis", state["company_updates"])
                        self.assertNotIn("Founder conversation", str(route))
                self.assertEqual(checkpoint.read_bytes(), before)
                if stage in {"pm", "product"}:
                    for prompt in ("Show me the roadmap.", "Quiet mode. I finished the merchant interviews.",
                                   "Wait until the merchant interviews."):
                        result = self.cli("task-context", prompt)
                        self.assertNotIn("company_followup", result["onboarding"])
                    while onboarding_review.status(self.work)["stage"] == stage:
                        review_current_topic(self.work)

    def test_pm_topic_resumes_without_raw_edits_and_reuses_an_agreed_gap(self):
        while onboarding_review.status(self.work)["stage"] == "company":
            review_current_topic(self.work)
        gap = {"question": "Who sets the Billing objectives?", "why": "Understand the PM’s remit.",
               "next_action": "Review the agreed role note.", "resume_when": "After the remit review."}
        self.cli("pm-onboarding", "gap", payload={"revision": 0, **gap})
        self.cli("pm-onboarding", "plan", payload={
            "revision": 1, "purpose": "Capture the PM’s responsibilities.", "sources": ["Role note"],
            "destinations": [layout.PROFILE]})
        source = "I propose Billing priorities each quarter."
        self.cli("pm-onboarding", "approve", payload={"revision": 2})
        self.cli("pm-onboarding", "propose", payload={
            "revision": 3, "source_scope": "Role note",
            "sources": [{"reference": "Role note", "date": "undated", "checked_on": "2025-02-01",
                         "coverage": "read", "text": source}],
            "entries": [{"source": 1, "scope": "pm", "topic": "responsibilities", "location": "Line 1", "quote": source}]})
        checkpoint = self.work / onboarding_review.FILE
        progress = checkpoint.read_bytes()
        expected = self.cli("task-context", "Pick up my PM context.")
        self.assertEqual(expected["onboarding"]["pm_phase"], "review")
        self.assertNotIn(source, str(expected))
        for client in ("Codex", "Claude"):
            resumed, _ = self.prompt(client, "resumed-" + client, "Pick up my PM context.")
            self.assertEqual(resumed, expected)
            for path in (layout.PROFILE, layout.STAKEHOLDERS):
                result = self.turn(client, "PreToolUse", client, tool_name="Edit" if client == "Claude" else "apply_patch",
                                   tool_input={"file_path": str(self.work / path)} if client == "Claude" else
                                   {"input": f"*** Begin Patch\n*** Add File: studio/{path}\n+# bypass\n*** End Patch"})
                self.assertIn("pm-onboarding", result["hookSpecificOutput"]["permissionDecisionReason"])
        self.cli("onboarding", "review-topic", payload={
            "revision": expected["onboarding"]["revision"], "stage": "pm", "topic": "role",
            "outcome": "reviewed", "pm_reply": "Fine."}, error="pending PM finding")
        self.assertEqual(checkpoint.read_bytes(), progress)
        self.cli("pm-onboarding", "defer", payload={"revision": 4, **gap})
        while onboarding_review.status(self.work)["stage"] == "pm":
            review_current_topic(self.work)
        cue = "We finished the remit review."
        state = self.cli("task-context", cue)["onboarding"]
        self.assertEqual(state["stage"], "product")
        self.assertIn("Offer to revisit", state["pm_followup"])
        self.assertNotIn(gap["question"], str(state))
        self.assertNotIn("pm_followup", self.cli("task-context", "Quiet mode. " + cue)["onboarding"])
        for client in ("Codex", "Claude"):
            self.assertEqual(self.prompt(client, "return-" + client, cue)[0]["onboarding"], state)
        review_current_topic(self.work)
        self.assertIn("Offer to revisit", self.cli("task-context", cue)["conversation"]["pm_followup"])

    def test_personal_gap_stays_private_on_unrelated_work_in_every_stage(self):
        while onboarding_review.status(self.work)["stage"] == "company":
            review_current_topic(self.work)
        gap = {"question": "Do I want to leave the company?", "why": "Personal career plans.",
               "next_action": "Review the other offer.", "resume_when": "I have spoken with the hiring manager"}
        self.cli("pm-onboarding", "gap", payload={"revision": 0, **gap})
        unrelated = "The hiring manager got a new workstation. Where is the Billing backlog?"
        for stage in ("pm", "product", "ready"):
            for prompt, offer in ((unrelated, False), (gap["resume_when"] + ".", True),
                                  ("Quiet mode. " + gap["resume_when"], False),
                                  ("Expedite mode. " + gap["resume_when"], False),
                                  ("Not now. " + gap["resume_when"], False)):
                with self.subTest(stage=stage, prompt=prompt):
                    results = [self.cli("task-context", prompt)]
                    for client in ("Codex", "Claude"):
                        route, guidance = self.prompt(client, client + stage + str(len(prompt)), prompt)
                        results.append(route)
                        self.assertNotIn(gap["question"], guidance)
                    for result in results:
                        turn = result.get("conversation" if stage == "ready" else "onboarding", {})
                        self.assertEqual("pm_followup" in turn, offer)
                        if offer:
                            self.assertIn("pm-onboarding status --gap 1/1", turn["pm_followup"])
                        for value in (gap["question"], gap["why"], gap["next_action"]):
                            self.assertNotIn(value, json.dumps(result))
            while stage != "ready" and onboarding_review.status(self.work)["stage"] == stage:
                review_current_topic(self.work)

    def test_setup_pace_suppresses_offers_until_coaching_resumes_in_the_same_session(self):
        gap = {"question": "How do merchants handle deposits?", "why": "Qualify the market.",
               "next_action": "Review one firsthand account.", "resume_when": "After the merchant interviews."}
        self.cli("company-onboarding", "gap", payload={"revision": 0, **gap})
        learning = "I finished the merchant interviews."
        for client in ("Codex", "Claude"):
            for directive, mode in (("Quiet mode", "quiet"), ("Expedite mode", "expedite")):
                session = client + mode
                self.prompt(client, session, directive)
                route, guidance = self.prompt(client, session, learning)
                self.assertEqual(route["onboarding"]["conversation_mode"], mode)
                self.assertNotIn("company_followup", route["onboarding"])
                self.assertNotIn(gap["question"], guidance)
                self.assertIn("omit unsolicited offers", guidance)
                independent, _ = self.prompt(client, session + "-other", learning)
                self.assertIn(gap["question"], independent["onboarding"]["company_followup"])
                self.prompt(client, session, "Resume coaching.")
                resumed, _ = self.prompt(client, session, learning)
                self.assertIn(gap["question"], resumed["onboarding"]["company_followup"])
        self.cli("task-context", "Quiet mode")
        self.assertIn("company_followup", self.cli("task-context", learning)["onboarding"])

    def test_company_and_damaged_walkthroughs_protect_existing_pm_records_in_both_clients(self):
        before = {}
        for record in (layout.PROFILE, layout.STAKEHOLDERS):
            path = self.work / record
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("# Approved context\n")
            before[record] = path.read_bytes()
        for stage in ("company", "repair"):
            if stage == "repair":
                checkpoint = self.work / onboarding_review.FILE
                checkpoint.parent.mkdir(parents=True, exist_ok=True)
                checkpoint.write_bytes(b"incomplete checkpoint")
            state = self.cli("onboarding", "status")
            self.assertEqual(state["stage"], stage)
            for record, original in before.items():
                path = self.work / record
                for client, tool, inputs in (
                    ("Codex", "apply_patch", {"input": f"*** Begin Patch\n*** Update File: studio/{record}\n"
                                                     "@@\n-# Approved context\n+# Unreviewed edit\n*** End Patch"}),
                    ("Claude", "Edit", {"file_path": str(path), "old_string": "Approved", "new_string": "Unreviewed"}),
                ):
                    with self.subTest(stage=stage, record=record, client=client):
                        result = self.turn(client, "PreToolUse", client, tool_name=tool, tool_input=inputs)
                        decision = result["hookSpecificOutput"]
                        self.assertEqual(decision["permissionDecision"], "deny")
                        self.assertEqual(decision["permissionDecisionReason"], state["next_action"])
                        self.assertEqual(path.read_bytes(), original)

    def test_existing_and_new_work_files_wait_for_required_setup(self):
        existing = self.work / "workspace" / "roadmaps" / "q4.md"
        existing.parent.mkdir(parents=True, exist_ok=True)
        existing.write_text("# Q4 roadmap\n")
        for client, tool, inputs in (
            ("Codex", "apply_patch", {"input": "*** Begin Patch\n*** Add File: studio/workspace/notes/new.md\n+# Notes\n*** End Patch"}),
            ("Claude", "Edit", {"file_path": str(existing), "old_string": "Q4 roadmap", "new_string": "Q4 plan"}),
        ):
            result = self.turn(client, "PreToolUse", client, tool_name=tool, tool_input=inputs)
            self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "deny")
            self.assertIn("required Studio onboarding", result["hookSpecificOutput"]["permissionDecisionReason"])
        self.assertEqual(existing.read_text(), "# Q4 roadmap\n")
        self.assertFalse((self.work / "workspace/notes/new.md").exists())
