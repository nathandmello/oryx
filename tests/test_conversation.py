"""Check scope continuity and reviewed checkpoints in fictional PM workspaces."""

from datetime import date
import json
import subprocess
import sys
import unittest
from unittest.mock import patch

import test_opportunities
import test_pm
import conversation
import hook
import preferences
import records
import task_context


class ConversationTests(unittest.TestCase):
    def setUp(self):
        test_pm.HubTests.setUp(self)
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
                empty, guidance = self.prompt(client, client, "Switch to Unknown")
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
                company, _ = self.prompt(client, client, "Read private/context/company/overview.md.")
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
            scoped, _ = self.prompt(client, client, "Switch to Shipping")
            self.assertEqual(scoped["conversation"]["mode"], "thought-partner")
        self.assertEqual(self.checkpoint.read_bytes(), written)

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

    def test_source_linked_conflict_offer_stays_quiet_for_routine_work(self):
        scope = {"product": "billing"}
        question = "Can the UK rollout start?"
        sources = [
            {"record": "context/company/overview.md", "text": "Wait for Legal.",
             "section": "Decisions already closed", "sources": [{"Source": "Legal policy"}]},
            {"record": "context/products/billing/overview.md", "text": "Launch on Friday.",
             "section": "Decisions already closed", "sources": [{"Source": "Product meeting"}]},
        ]
        result = {"scope": scope, "warnings": [], "entries": [],
                  "conflicts": [{"question": question, "scope": "UK rollout", "entries": sources}]}
        prompt = "Draft the Billing customer update"
        offer = conversation.context_offer(prompt, result, [], False)
        self.assertEqual(offer["workflow"], "context-health")
        self.assertIn("context/company/overview.md", offer["source"])
        self.assertIn("context/products/billing/overview.md", offer["source"])
        self.assertIsNone(conversation.context_offer("Show the Billing roadmap", result, [], False))
        self.assertIsNone(conversation.context_offer(prompt, result, [], True))
        deferral = {**{key: offer[key] for key in ("workflow", "scope", "source", "revision")},
                    "review_on": None}
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
