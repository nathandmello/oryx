"""Exercise required setup and handoff through the registered agent hooks."""

import json
import unittest

import test_conversation
import test_pm
import onboarding_review
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
        requests = {"company": "Build me a Q4 roadmap by morning.",
                    "pm": "/pm portfolio backlog show",
                    "product": "Expedite mode. Put Billing on the roadmap."}
        for stage in ("company", "pm", "product"):
            for topic in self.frameworks[stage]:
                for client in clients:
                    route, guidance = self.prompt(client, client, requests[stage])
                    self.assertEqual(route["status"], "onboarding_required")
                    state = route["onboarding"]
                    self.assertEqual(state["stage"], stage)
                    self.assertEqual(state["walkthroughs"][stage]["next_topic"], topic)
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
