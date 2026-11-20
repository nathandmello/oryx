"""Check scope continuity and reviewed checkpoints in fictional PM workspaces."""

from datetime import date
import json
import subprocess
import sys
import unittest
from unittest.mock import patch

import test_opportunities
import test_pm
from onboarding_fixtures import reviewed_setup
import conversation
import hook
import preferences
import records
import task_context


class ConversationTests(unittest.TestCase):
    def setUp(self):
        reviewed_setup(self)
        records.create(self.root, "company-context", "context/company/overview.md")
        records.create(self.root, "product-context", "context/products/billing/overview.md", "Billing")
        records.create(self.root, "product-context", "context/products/shipping/overview.md", "Shipping")
        self.record = "workspace/problems/bulk-export.md"
        self.checkpoint = records.create(self.root, "problem", self.record, "Bulk export")
        self.cwd = self.root

    def cli(self, *args, payload=None, error=None):
        result = subprocess.run(
            [sys.executable, str(self.root / "tools/pm.py"), *args], cwd=self.cwd,
            input="" if payload is None else json.dumps(payload), capture_output=True, text=True
        )
        if error:
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(error, result.stdout + result.stderr)
            return
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def turn(self, client, event, session, **fields):
        path = {"Codex": ".codex/hooks.json", "Claude": ".claude/settings.json"}[client]
        config = json.loads((self.root / path).read_text())["hooks"][event][0]["hooks"][0]
        cmd = config["command"] if client == "Codex" else [config["command"], *config["args"]]
        result = subprocess.run(
            cmd, shell=client == "Codex", input=json.dumps({
                "hook_event_name": event, "session_id": session, "cwd": str(self.cwd), **fields
            }), cwd=self.cwd, capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def prompt(self, client, session, prompt):
        response = self.turn(client, "UserPromptSubmit", session, prompt=prompt)
        guidance = response["hookSpecificOutput"]["additionalContext"]
        line = guidance.splitlines()[-1]
        return (json.loads(line) if line.startswith("{") else {}), guidance

    def test_registered_clients_keep_per_turn_rules_after_walkthrough(self):
        overview = self.work / "context/company/overview.md"
        original = overview.read_bytes()
        for client in ("Codex", "Claude"):
            with self.subTest(client=client):
                for request in ("Help me set up oryx", "Quiet mode", "Show my roadmap"):
                    _, guidance = self.prompt(client, client, request)
                    self.assertIn("ask one focused question", guidance)
                    self.assertIn("explicit confirmation of a specific product decision", guidance)
                    self.assertIn("follow the pm's current request", guidance.lower())
                    if request == "Quiet mode":
                        self.assertIn("Quiet mode is active", guidance)
                self.assertEqual(overview.read_bytes(), original)

    def test_company_gap_returns_on_the_agreed_cue_across_client_sessions(self):
        gap = {"question": "What share of revenue comes from renewals?", "why": "Understand the economics.",
               "next_action": "Check the reported renewal share.", "resume_when": "Finance shares the next operating review."}
        self.cli("company-onboarding", "gap", payload={"revision": 0, **gap})
        self.cli("company-onboarding", "finish", payload={"revision": 1})
        before = (self.work / "workspace/onboarding/company.json").read_bytes()
        for client in ("Codex", "Claude"):
            for prompt in ("Show the billing roadmap.", "Wait until the operating review.", "Quiet mode. Read the operating review."):
                _, guidance = self.prompt(client, client + prompt, prompt)
                self.assertNotIn(gap["question"], guidance)
            _, guidance = self.prompt(client, client, "Here's Finance's latest operating review.")
            self.assertIn(gap["question"], guidance)
            self.assertIn(gap["next_action"], guidance)
            self.assertIn("Check whether the cue occurred", guidance)
        self.assertEqual((self.work / "workspace/onboarding/company.json").read_bytes(), before)

    def test_active_source_plan_resumes_and_routes_native_company_edits_to_review(self):
        source = "Fictional strategy deck"
        self.cli("company-onboarding", "plan", payload={"revision": 0, "purpose": "Understand the company.", "sources": [source]})
        overview = "studio/context/company/overview.md"
        for client in ("Codex", "Claude"):
            _, guidance = self.prompt(client, client, "Let's resume company setup.")
            self.assertIn("phase plan", guidance)
            self.assertNotIn(source, guidance)
            def guard(path):
                if client == "Codex":
                    return self.turn(client, "PreToolUse", client, tool_name="apply_patch", tool_input={
                        "input": f"*** Begin Patch\n*** Update File: {path}\n@@\n+x\n*** End Patch"})
                return self.turn(client, "PreToolUse", client, tool_name="Edit", tool_input={"file_path": path, "new_string": "x"})
            for path in (overview, "studio/context/company/supplement.md", "studio/workspace/onboarding/company.json"):
                output = guard(path)["hookSpecificOutput"]
                self.assertEqual(output["permissionDecision"], "deny")
                self.assertIn("company-onboarding", output["permissionDecisionReason"])
            self.assertEqual(guard("studio/context/products/billing/overview.md"), {})
        self.cli("company-onboarding", "finish", payload={"revision": 1})
        self.assertIsNone(hook.edit_reason(self.root, self.work, self.root / overview, "text"))

    def test_native_scope_resumes_after_acknowledgment_or_answer(self):
        for client in ("Codex", "Claude"):
            for message in ("Thanks!", "Churn was our strongest concern."):
                with self.subTest(client=client, message=message):
                    session = client + message
                    scoped, _ = self.prompt(client, session, "Draft the Billing plan")
                    self.assertEqual(scoped["scope"]["product"], "billing")
                    middle, _ = self.prompt(client, session, message)
                    self.assertFalse(middle.get("entries"))
                    if message.startswith("Thanks"):
                        self.assertFalse(middle)
                        self.assertEqual(self.turn(client, "Stop", session, last_assistant_message="You're welcome."), {})
                    scoped, _ = self.prompt(client, session, "Can you make it shorter?")
                    self.assertEqual(scoped["scope"]["product"], "billing")

    def test_switch_replaces_scope_and_unknown_request_never_inherits(self):
        for client in ("Codex", "Claude"):
            with self.subTest(client=client):
                self.prompt(client, client, "Draft the Billing plan")
                scoped, _ = self.prompt(client, client, "Switch from Billing to Shipping")
                self.assertEqual(scoped["scope"]["product"], "shipping")
                empty, guidance = self.prompt(client, client, "Let’s switch to Unknown")
                self.assertFalse(empty)
                self.assertIn("Context scope is uncertain", guidance)
                self.assertFalse(self.prompt(client, client, "Can you make it shorter?")[0])
                self.prompt(client, client, "Draft the Billing plan")
                self.assertFalse(self.prompt(client, client, "Give me a soup recipe")[0])
                self.assertFalse(self.prompt(client, client, "Thanks!")[0])
                self.assertFalse(self.prompt(client, client, "Can you make it shorter?")[0])

    def test_company_record_follow_up_replaces_preceding_product(self):
        for client in ("Codex", "Claude"):
            with self.subTest(client=client):
                self.prompt(client, client, "Review product/billing.")
                company, _ = self.prompt(client, client, "Read studio/context/company/overview.md.")
                self.assertTrue(company["scope"]["company"])
                follow_up, _ = self.prompt(client, client, "Can you make it shorter?")
                self.assertTrue(follow_up["scope"]["company"])
                self.assertIsNone(follow_up["scope"].get("product"))

    def test_quiet_survives_neutral_and_unnamed_discussion_turns(self):
        for client in ("Codex", "Claude"):
            with self.subTest(client=client):
                self.prompt(client, client, "Quiet mode for Billing. Give me the workaround.")
                ambiguous, guidance = self.prompt(client, client, "What do we know about displacement?")
                self.assertIn("Quiet mode is active", guidance)
                self.assertFalse(ambiguous["entries"])
                self.prompt(client, client, "Thanks!")
                follow_up, _ = self.prompt(client, client, "Can you make it shorter?")
                self.assertEqual(follow_up["conversation"]["mode"], "quiet")
                switched, _ = self.prompt(client, client, "Switch to Shipping")
                self.assertEqual(switched["conversation"]["mode"], "thought-partner")

    def test_expedite_is_an_explicit_pace_for_current_work(self):
        gap = {"question": "Who approves renewals?", "why": "Clarify ownership.",
               "next_action": "Ask Finance.", "resume_when": "operating review"}
        self.cli("company-onboarding", "gap", payload={"revision": 0, **gap})
        before = self.checkpoint.read_bytes()
        for client in ("Codex", "Claude"):
            with self.subTest(client=client):
                _, guidance = self.prompt(client, client, "Use expedite mode.")
                self.assertIn("Expedite mode is active", guidance)
                prompt = "Billing roadmap for our operating review. Can we claim a 20% impact?"
                scoped, guidance = self.prompt(client, client, prompt)
                self.assertEqual(scoped["conversation"]["mode"], "expedite")
                self.assertNotIn("suggestion", scoped["conversation"])
                self.assertIn(hook.NUMBERS_GUIDANCE, guidance)
                self.assertNotIn(gap["question"], guidance)
                self.assertIn("Complete each required craft step", guidance)
                self.prompt(client, client, "Thanks!")
                follow, _ = self.prompt(client, client, "Can you make it shorter?")
                self.assertEqual(follow["conversation"]["mode"], "expedite")
                switched, _ = self.prompt(client, client, "Switch to Shipping")
                self.assertEqual(switched["conversation"]["mode"], "thought-partner")
                scoped, _ = self.prompt(client, client, "Switch to expedited mode for Shipping.")
                self.assertEqual(scoped["conversation"]["mode"], "expedite")
                scoped, _ = self.prompt(client, client, "Quiet mode for Shipping.")
                self.assertEqual(scoped["conversation"]["mode"], "quiet")
                self.prompt(client, client, "Yes, use expedite mode.")
                self.prompt(client, client, "Exit expedite mode.")
                scoped, _ = self.prompt(client, client, "Make this shorter.")
                self.assertEqual(scoped["conversation"]["mode"], "thought-partner")
                self.prompt(client, client, "Let’s use expedite mode for Shipping.")
                scoped, _ = self.prompt(client, client, "Resume coaching for Shipping.")
                self.assertEqual(scoped["conversation"]["mode"], "thought-partner")
                scoped, _ = self.prompt(client, client + "-fresh", prompt)
                self.assertEqual(scoped["conversation"]["mode"], "thought-partner")
        self.assertEqual(before, self.checkpoint.read_bytes())

    def test_hooks_off_expedite_and_mentions_that_do_not_change_pace(self):
        for prompt in ("Expedite mode for my Q4 roadmap.", "Please enter expedited mode."):
            result = self.cli("task-context", "--product", "billing", prompt)
            self.assertEqual(result["conversation"]["mode"], "expedite")
        for prompt in ("Build a roadmap for Q4. It's due by morning.",
                       'The customer wrote: "Use expedite mode."',
                       "Expedite mode was discussed at planning.",
                       "Should we use expedite mode?", "Don't use expedite mode.", "Yes."):
            result = self.cli("task-context", "--product", "billing", prompt)
            self.assertEqual(result["conversation"]["mode"], "thought-partner")

    def test_only_a_current_offer_accepts_a_short_yes(self):
        offer = "I can check the inputs while you make the calls.\n\n" + conversation.EXPEDITE_OFFER
        for client in ("Codex", "Claude"):
            with self.subTest(client=client):
                session = client + "-offer"
                self.prompt(client, session, "I need the Billing roadmap and revenue figures by morning.")
                # The numeric review blocks the first Stop. Only the final reply counts.
                first = self.turn(client, "Stop", session, last_assistant_message=offer)
                self.assertEqual(first["decision"], "block")
                self.turn(client, "Stop", session, stop_hook_active=True, last_assistant_message=offer)
                _, other = self.prompt(client, session + "-other", "Yes, please.")
                self.assertNotIn("Expedite mode is active", other)
                answer, guidance = self.prompt(client, session, "Yes, please.")
                self.assertEqual(answer["scope"]["product"], "billing")
                self.assertTrue(answer["conversation"]["accepted_expedite_offer"])
                self.assertEqual(answer["conversation"]["mode"], "expedite")
                self.assertIn(hook.NUMBERS_GUIDANCE, guidance)
                follow, _ = self.prompt(client, session, "Can you make it shorter?")
                self.assertEqual(follow["conversation"]["mode"], "expedite")

                session = client + "-unscoped"
                self.prompt(client, session, "Can you help me build a roadmap by morning?")
                self.turn(client, "Stop", session, last_assistant_message=offer)
                self.prompt(client, session, "Sure!")
                scoped, _ = self.prompt(client, session, "It's for Billing.")
                self.assertEqual(scoped["conversation"]["mode"], "expedite")

                for reply in ("No, thanks.", "Yes, switch to Shipping.", "Something else first."):
                    session = client + reply
                    self.prompt(client, session, "The Billing plan is due by morning.")
                    self.turn(client, "Stop", session, last_assistant_message=offer)
                    _, immediate = self.prompt(client, session, reply)
                    self.assertNotIn("Expedite mode is active", immediate)
                    _, late = self.prompt(client, session, "Yes.")
                    self.assertNotIn("Expedite mode is active", late)

    def test_an_old_stop_or_quoted_offer_cannot_activate_expedite(self):
        question = conversation.EXPEDITE_OFFER
        for message in (f"> {question}", f'"{question}"', "Which team?\n\n" + question,
                        "Sample language:\n\n" + question, "~~~\nExample.\n\n" + question,
                        question + "\nThe above was an example.", None):
            self.assertFalse(conversation.offered_expedite(message))
        session = "stale-stop"
        self.turn("Codex", "UserPromptSubmit", session, turn_id="one", prompt="Billing needs a plan by morning.")
        self.turn("Codex", "UserPromptSubmit", session, turn_id="two", prompt="Switch to Shipping.")
        self.turn("Codex", "Stop", session, turn_id="one", last_assistant_message=question)
        _, guidance = self.prompt("Codex", session, "Yes, please.")
        self.assertNotIn("Expedite mode is active", guidance)

    def test_checkpoint_preview_apply_and_hooks_off_resume(self):
        before = self.checkpoint.read_bytes()
        changes = {
            "state": "waiting", "mode": "quiet",
            "last_checkpoint": "2026-11-19: Two support calls cite the export failure.",
            "next_action": "Check the supported export formats.",
            "waiting_on": "Support case links",
            "resume_when": "Support shares the case references.",
        }
        receipt = self.cli("conversation", "checkpoint", "preview", self.record, payload=changes)
        self.assertEqual(self.checkpoint.read_bytes(), before)
        self.cli("conversation", "checkpoint", "apply", self.record, payload=receipt)
        written = self.checkpoint.read_bytes()
        self.assertEqual(receipt["checkpoint"]["id"], self.cli("conversation", "checkpoint", "show", self.record)["id"])
        self.cli("conversation", "checkpoint", "apply", self.record, payload=receipt, error="stale")
        self.assertEqual(self.checkpoint.read_bytes(), written)

        preferences.save(self.work, updates={"layout": "bullets", "detail": "concise"})
        context = self.cli("task-context", "--product", "billing", "--work-record", self.record, "Continue the decision")
        self.assertEqual(context["conversation"]["mode"], "quiet")
        self.assertEqual(context["conversation"]["reply_preferences"], {"detail": "concise", "layout": "bullets"})
        self.assertEqual(context["conversation"]["checkpoint"]["work_state"]["Waiting on"], "Support case links")

        for client in ("Codex", "Claude"):
            scoped, guidance = self.prompt(client, client, f"Resume Billing with {self.record}")
            self.assertEqual(scoped["conversation"]["mode"], "quiet")
            self.assertIn("Keep optional explanation brief", guidance)
            unscoped, _ = self.prompt(client, client, "What do we know about displacement?")
            self.assertEqual(unscoped["conversation"]["mode"], "quiet")
            resumed, _ = self.prompt(client, client, "Can you make it shorter?")
            self.assertEqual(resumed["conversation"]["mode"], "quiet")
            scoped, _ = self.prompt(client, client, "Switch to Shipping")
            self.assertEqual(scoped["conversation"]["mode"], "thought-partner")
        self.assertEqual(self.checkpoint.read_bytes(), written)

    def test_standalone_checkpoint_resumes_without_borrowing_product_scope(self):
        receipt = self.cli("conversation", "checkpoint", "preview", self.record, payload={"mode": "quiet"})
        self.cli("conversation", "checkpoint", "apply", self.record, payload=receipt)
        for client in ("Codex", "Claude"):
            self.prompt(client, client, "Review Billing.")
            result, _ = self.prompt(client, client, f"Resume {self.record}")
            self.assertEqual(result["scope"], {})
            self.assertEqual(result["conversation"]["checkpoint"]["record"], self.record)
            self.prompt(client, client, "Thanks!")
            follow_up, guidance = self.prompt(client, client, "Can you make it shorter?")
            self.assertFalse(follow_up)
            self.assertIn("Quiet mode is active", guidance)

    def test_changes_are_checked_before_private_file_is_written(self):
        before = self.checkpoint.read_bytes()
        self.cli("conversation", "checkpoint", "preview", self.record,
                 payload={"next_action": "Write | invalid table content"}, error="single concrete value")
        self.cli("conversation", "checkpoint", "preview", "../workspace/problems/bulk-export.md",
                 payload={"mode": "quiet"}, error="existing workspace")
        receipt = self.cli("conversation", "checkpoint", "preview", self.record, payload={"mode": "quiet"})
        with (self.work / ".gitignore").open("a") as stream:
            stream.write(f"\n{self.record}\n")
        self.cli("conversation", "checkpoint", "apply", self.record, payload=receipt, error="ignores")
        self.assertEqual(self.checkpoint.read_bytes(), before)

    def test_deferral_holds_only_unchanged_in_scope_workflow_until_review(self):
        scope = {"product": "billing"}
        source = "Fixture launch review, item 3"
        revision = conversation.fingerprint("Escalation still needs review")
        candidate = {
            "workflow": "context-health", "scope": scope, "source": source, "revision": revision,
            "reason": "The dated approval expired.", "next_action": "Check the current policy.",
        }
        other = {**candidate, "workflow": "decision-coaching"}
        unavailable = {**candidate, "workflow": "stakeholder-profile"}
        out_of_scope = {**candidate, "scope": {"product": "shipping"}}
        choices = [other, unavailable, candidate, out_of_scope]
        first, review = date(2026, 11, 19), date(2026, 11, 20)
        self.assertIs(conversation.select_offer(choices, scope), candidate)
        self.assertIsNone(conversation.select_offer(choices, scope, quiet=True))
        changes = {"deferral": {
            **{key: candidate[key] for key in ("workflow", "scope", "source", "revision")},
            "review_on": review.isoformat(),
        }}
        receipt = self.cli("conversation", "checkpoint", "preview", self.record, payload=changes)
        self.cli("conversation", "checkpoint", "apply", self.record, payload=receipt)
        durable = self.cli("conversation", "checkpoint", "show", self.record)["deferrals"]
        self.assertEqual(durable, [changes["deferral"]])
        self.assertIs(conversation.select_offer(choices, scope, deferrals=durable, on=first), other)
        self.assertIs(conversation.select_offer(choices, scope, deferrals=durable, on=review), candidate)
        changed = {**candidate, "revision": conversation.fingerprint("New authoritative ruling")}
        self.assertIs(conversation.select_offer([other, changed], scope, deferrals=durable, on=first), changed)

    def test_clear_deferral_removes_only_the_reviewed_scope_and_source(self):
        first = {"workflow": "context-health", "scope": {"product": "billing"},
                 "source": "Legal memo, page 1", "revision": conversation.fingerprint("Original"),
                 "review_on": None}
        same_source = {**first, "scope": {"product": "shipping"}}
        same_scope = {**first, "source": "Product review, item 2"}
        for item in (first, same_source, same_scope):
            receipt = self.cli("conversation", "checkpoint", "preview", self.record,
                               payload={"deferral": item})
            self.cli("conversation", "checkpoint", "apply", self.record, payload=receipt)
        self.cli("conversation", "checkpoint", "preview", self.record,
                 payload={"clear_deferral": {**first, "revision": conversation.fingerprint("New evidence")}},
                 error="no longer current")
        receipt = self.cli("conversation", "checkpoint", "preview", self.record,
                           payload={"clear_deferral": first})
        self.cli("conversation", "checkpoint", "apply", self.record, payload=receipt)
        state = self.cli("conversation", "checkpoint", "show", self.record)
        self.assertEqual(state["deferrals"], [same_source, same_scope])

    def test_source_linked_conflict_offer_stays_quiet_for_routine_work(self):
        scope = {"product": "billing"}
        question = "Can the UK rollout start?"
        sources = [
            {"record": "context/company/overview.md", "text": "Wait for Legal.",
             "section": "Decisions already closed", "sources": [{"Source": "Legal policy"}]},
            {"record": "context/products/billing/overview.md", "text": "Launch on Friday.",
             "section": "Decisions already closed", "sources": [{"Source": "Product meeting"}]},
        ]
        risk = {"id": "risk-123", "state": "open", "classification": "potential conflict",
                "reason": "The guidance gives different next steps.", "question": question, "claims": sources}
        result = {"scope": scope, "warnings": [], "entries": [], "risks": [risk]}
        prompt = "Draft the Billing customer update"
        offer = conversation.context_offer(prompt, result, [], False)
        self.assertEqual(offer["workflow"], "context-health")
        self.assertIn("context/company/overview.md", offer["sources"])
        self.assertIn("context/products/billing/overview.md", offer["sources"])
        self.assertIsNone(conversation.context_offer("Show the Billing roadmap", result, [], False))
        self.assertIsNone(conversation.context_offer("Red-team the Billing launch decision", result, [], False))
        self.assertIsNone(conversation.context_offer("Shorten the Billing roadmap", result, [], False))
        self.assertIsNone(conversation.context_offer(prompt, result, [], True))
        deferral = {**{key: offer[key] for key in ("workflow", "scope", "source", "revision")},
                    "review_on": None}
        self.assertIsNone(conversation.context_offer(prompt, result, [deferral], False))
        risk["claims"].reverse()
        self.assertIsNone(conversation.context_offer(prompt, result, [deferral], False))

    def test_native_forecast_edits_use_reviewed_commands(self):
        path = self.work / "workspace" / "forecasts" / "f-123.md"
        why = hook.edit_reason(self.root, self.work, path, "# Forecast")
        self.assertIn("forecast preview", why)
        self.assertIn("forecast apply", why)

    def test_invalid_cache_and_unavailable_write_keep_the_hook_usable(self):
        session = "invalid-cache"
        state = task_context.session_state(self.work, session)
        state.parent.mkdir(parents=True, exist_ok=True)
        state.write_text("{")
        scoped, _ = self.prompt("Codex", session, "Draft the Billing plan")
        self.assertEqual(scoped["scope"]["product"], "billing")
        with patch.object(task_context, "remember_scope", side_effect=PermissionError):
            result = hook.prompt_context(self.work, self.cwd, {"prompt": "Draft the Billing plan", "session_id": session})
        guidance = result["hookSpecificOutput"]["additionalContext"]
        self.assertIn("session checkpoint cache was unavailable", guidance)
        self.assertEqual(json.loads(guidance.splitlines()[-1])["scope"]["product"], "billing")


class SignedCheckpointTests(unittest.TestCase):
    def test_an_exact_byte_signature_prevents_a_checkpoint_write(self):
        hub = test_opportunities.InitiativeTests()
        try:
            hub.setUp()
            hub.submit(hub.setup_event(), hub.capture(), hub.describe(), hub.metric(), hub.decision("evaluate"))
            hub.submit(hub.decision("prepare-brief"))
            hub.brief_ready()
            hub.submit(hub.target(), hub.decision("approve-initiative"))
            path = hub.work / hub.brief
            before = path.read_bytes()
            hub.cli("conversation", "checkpoint", "preview", hub.brief,
                    value={"mode": "quiet"}, error="signed review binds this file")
            self.assertEqual(path.read_bytes(), before)
        finally:
            hub.doCleanups()
