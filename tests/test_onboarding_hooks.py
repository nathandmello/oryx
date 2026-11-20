"""Exercise required setup and handoff through the registered agent hooks."""

import unittest

import test_conversation
import test_pm
import onboarding_review
import task_context
from onboarding_fixtures import define_fixture_frameworks, review_current_topic


class OnboardingHookTests(unittest.TestCase):
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
                    self.assertEqual(task_context.previous_scope(self.work, client), {"setup_stage": stage})
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
