"""Exercise transcript controls, optional advice and source exclusions through configured clients."""

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import test_pm
import test_conversation
from onboarding_fixtures import reviewed_setup
import context_advice
import ingestion_signals
import offer_queue
import overrides
import records
import session_journal
import turn_intent
import work_handoffs


class SessionWorkflowTests(unittest.TestCase):
    turn = test_conversation.ConversationTests.turn
    cli = test_conversation.ConversationTests.cli

    def setUp(self):
        reviewed_setup(self)
        self.cwd = self.root
        state = tempfile.TemporaryDirectory()
        self.addCleanup(state.cleanup)
        self.addCleanup(patch.stopall)
        patch.dict(os.environ, {"XDG_STATE_HOME": str(Path(state.name).resolve())}).start()

    def test_all_four_capture_and_tip_settings_in_the_real_hook(self):
        for logging in (False, True):
            for tips in (False, True):
                with self.subTest(logging=logging, tips=tips):
                    # Use a new Studio per trial so reservations from one do not suppress another.
                    with tempfile.TemporaryDirectory() as tmp:
                        self._exercise_settings(Path(tmp).resolve(), logging, tips)

    def _exercise_settings(self, base, logging, tips):
        import shutil
        import subprocess
        import sys
        root = base / "hub"
        shutil.copytree(self.root, root)
        private = root / self.work.name
        session = f"settings-{int(logging)}-{int(tips)}"
        session_journal.configure(private, enabled=logging)
        args = test_pm.pm.build_parser().parse_args(["override", "context-advice", "on" if tips else "off"])
        overrides.run(root, args)
        context_advice.observe_claude(private, {"session_id": session, "context_window": {"used_percentage": 94}})
        config = json.loads((root / ".claude/settings.json").read_text())["hooks"]
        def event(name, **fields):
            handler = config[name][0]["hooks"][0]
            payload = dict(cwd=str(root), session_id=session, turn_id="phase-two", hook_event_name=name, **fields)
            result = subprocess.run([sys.executable, *handler["args"]], cwd=root, input=json.dumps(payload),
                                    capture_output=True, text=True, check=True)
            return json.loads(result.stdout)
        response = event("UserPromptSubmit", prompt="What is next? Before we start drafting, review the decision.")
        guidance = response["hookSpecificOutput"]["additionalContext"]
        self.assertEqual('"workflow": "context-advice"' in guidance, tips)
        self.assertNotIn("systemMessage", response)
        stopped = event("Stop", last_assistant_message="The target for the review is still open.")
        self.assertNotIn("systemMessage", stopped)
        if logging:
            evidence = session_journal.read_session(private, "claude", session)["events"]
            self.assertEqual([row["role"] for row in evidence], ["human", "assistant"])
            self.assertIn("target for the review", evidence[-1]["text"])
        else:
            self.assertFalse(session_journal.status(private)["enabled"])
            self.assertFalse(session_journal.read_session(private, "claude", session)["events"])

    def test_explicit_source_exclusions_and_session_pause_survive_separate_hook_processes(self):
        session_journal.configure(self.work, enabled=True)
        for client in ("Claude", "Codex"):
            session = client + "-privacy"
            def submit(turn, prompt):
                return self.turn(client, "UserPromptSubmit", session, turn_id=turn, prompt=prompt)["hookSpecificOutput"]["additionalContext"]
            protected = submit("one", "Please keep this conversation off the record. Rowan asked for a packet about account Seacrest.")
            self.assertNotIn("Background ingestion assessment", protected)
            self.assertTrue(session_journal.off_record(self.work, client.lower(), session))
            self.assertNotIn("Background ingestion assessment", submit("two", "Rowan prefers the Seacrest estimate first."))
            submit("three", "Back on the record.")
            question = submit("question", "Could we keep this off the record? The rehearsal detail is lavender.")
            self.assertNotIn("Background ingestion assessment", question)
            self.assertTrue(session_journal.off_record(self.work, client.lower(), session))
            self.turn(client, "Stop", session, turn_id="question", last_assistant_message="The lavender detail is private.")
            submit("private-followup", "The follow-up detail is lilac.")
            submit("on-again", "Could we go back on the record?")
            self.assertFalse(session_journal.off_record(self.work, client.lower(), session))
            self.assertNotIn("Background ingestion assessment", submit("four", "Don't use this for stakeholder profiles. Rowan needs the file."))
            self.turn(client, "Stop", session, turn_id="four", last_assistant_message="Understood.")
            events = session_journal.read_session(self.work, client.lower(), session)["events"]
            self.assertNotIn("Seacrest", json.dumps(events))
            self.assertNotIn("lavender", json.dumps(events))
            self.assertNotIn("lilac", json.dumps(events))
            self.assertTrue(any("Rowan needs the file" in (e["text"] or "") for e in events))

    def test_identical_milestones_at_distinct_client_submissions(self):
        prompt = "What is next? Check the mulberry decision."
        receipts = self.work / offer_queue.FILE

        def queue_source(label):
            path = f"context/products/billing/sources/{label}.txt"
            source = self.work / path
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text("Jo Diaz: I prefer a written summary with examples.\n")
            ingestion_signals.assess(self.work, {"moment": "busy", "source": {
                "kind": "transcript", "scope": path, "reference": path, "authorized": True,
                "purposes": ["stakeholder-profile"], "retention": "review", "subject": "product/billing"}})
            return next(token for token, row in offer_queue.read(self.work)[1].items() if row["status"] == "pending")

        def after_cooldown():
            rows = offer_queue.read(self.work)[1]
            for row in rows.values():
                row["at"] -= offer_queue.COOLDOWN + 1
            receipts.write_text(json.dumps(rows))

        for client in ("Codex", "Claude"):
            session = "milestones-" + client
            def submit(**fields):
                response = self.turn(client, "UserPromptSubmit", session, prompt=prompt, **fields)
                last = response["hookSpecificOutput"]["additionalContext"].splitlines()[-1]
                turn = json.loads(last).get("conversation", {}) if last.startswith("{") else {}
                return turn.get("optional_offer", {}).get("token")

            first = queue_source(client + "-initial")
            self.assertEqual(submit(), first)
            pending = turn_intent.pending_path(self.work, client.lower(), session)
            self.assertNotIn("mulberry", pending.read_text())
            self.assertEqual(pending.stat().st_mode & 0o777, 0o600)
            for boundary in ("Stop", "PostCompact"):
                after_cooldown()
                fresh = queue_source(client + "-" + boundary)
                self.assertIsNone(submit(), "A replay during the open submission must use its existing pause")
                if boundary == "Stop":
                    self.turn(client, boundary, session, last_assistant_message="The decision is open.")
                else:
                    self.turn(client, boundary, session, trigger="auto")
                self.assertEqual(submit(), fresh, (client, boundary))
            # Real clients can also supply a message or prompt ID without a turn_id.
            field = "user_message_id" if client == "Codex" else "prompt_id"
            after_cooldown()
            identified = queue_source(client + "-identified")
            self.assertEqual(submit(**{field: "first"}), identified)
            after_cooldown()
            later = queue_source(client + "-later")
            self.assertIsNone(submit(**{field: "first"}))
            self.assertEqual(submit(**{field: "second"}), later)
            self.assertFalse(session_journal.read_session(self.work, client.lower(), session)["events"])
            self.assertNotIn("mulberry", receipts.read_text())
            after_cooldown()

    def test_stale_and_nested_stops_preserve_an_unidentified_submission(self):
        for client in ("Codex", "Claude"):
            sid = "overlap-" + client
            self.turn(client, "UserPromptSubmit", sid, turn_id="older", prompt="Check the timeline.")
            self.turn(client, "UserPromptSubmit", sid, prompt="What is next?")
            pending = turn_intent.pending_path(self.work, client.lower(), sid)
            outstanding = pending.read_bytes()
            for stop in ({"agent_id": "worker"}, {"turn_id": "older"}):
                self.turn(client, "Stop", sid, last_assistant_message="Earlier reply.", **stop)
                self.assertEqual(pending.read_bytes(), outstanding)
            self.turn(client, "UserPromptSubmit", sid, prompt="What is next?")
            self.assertEqual(pending.read_bytes(), outstanding)

    def test_new_compaction_signal_at_an_identical_codex_milestone(self):
        sid = "compacted-codex"
        def window(turn):
            context_advice.observe_codex_event(self.work, sid, {"method": "turn/started", "params": {
                "threadId": sid, "turn": {"id": turn}}})
            context_advice.observe_codex_event(self.work, sid, {"method": "thread/tokenUsage/updated", "params": {
                "threadId": sid, "turnId": turn, "tokenUsage": {"modelContextWindow": 10000,
                                                                 "last": {"totalTokens": 9000}}}})
        def milestone():
            reply = self.turn("Codex", "UserPromptSubmit", sid, prompt="What is next?")
            turn = json.loads(reply["hookSpecificOutput"]["additionalContext"].splitlines()[-1])
            offer = turn["conversation"]["optional_offer"]
            self.assertEqual(offer["action"], "compact")
            return offer["token"]

        window("before")
        first = milestone()
        rows = offer_queue.read(self.work)[1]
        rows[first]["at"] -= offer_queue.COOLDOWN + 1
        (self.work / offer_queue.FILE).write_text(json.dumps(rows))
        self.turn("Codex", "PostCompact", sid)
        window("after")
        self.assertNotEqual(milestone(), first)

    def test_unwritable_submission_marker_preserves_primary_work(self):
        context_advice.observe_claude(self.work, {"session_id": "no-marker", "context_window": {"used_percentage": 94}})
        (self.work / ".state/pending-submissions").write_text("Cannot create a marker here.")
        result = self.turn("Claude", "UserPromptSubmit", "no-marker", prompt="What is next?")
        guidance = result["hookSpecificOutput"]["additionalContext"]
        self.assertIn("follow the pm's current request", guidance.lower())
        self.assertNotIn('"optional_offer"', guidance)

    def test_quoted_controls_cannot_change_consent_and_explicit_mute_is_immediate(self):
        self.assertEqual(turn_intent.controls('Summarize this. Transcript: Dina: off the record.'), (None, False, None))
        self.assertEqual(turn_intent.controls('Review the sentence “mute context tips”.'), (None, False, None))
        self.assertEqual(turn_intent.controls('Transcript: Please keep this conversation off the record.'), (None, False, None))
        self.assertEqual(turn_intent.controls('Explain “Please keep this conversation off the record.”'), (None, False, None))
        self.assertEqual(turn_intent.controls('Summarize this email.\n> Could we keep this off the record?'), (None, False, None))
        self.turn("Codex", "UserPromptSubmit", "mute-once", turn_id="a", prompt="Mute context tips.")
        self.assertFalse(overrides.context_advice_allowed(self.work, "native"))
        self.assertTrue(overrides.profile_suggestions_allowed(self.work, "chat"))

    def save_handoff(self, name):
        task = {"name": name, "scope": "product/harbour", "objective": "Review the schedule.",
                "open_question": "Who will cover the pilot?", "next_step": "Check the support rota."}
        return work_handoffs.save(self.work, {"review": work_handoffs.preview(self.work, task), "approved": True})

    def exchange(self, client, session, turn, prompt, *, reply="Understood."):
        self.turn(client, "UserPromptSubmit", session, turn_id=turn, prompt=prompt)
        self.turn(client, "Stop", session, turn_id=turn, last_assistant_message=reply)
        events = session_journal.read_session(self.work, client.lower(), session)["events"]
        return [row for row in events if row["turn_id"] == turn]

    def work_turn(self, client, session, turn, prompt):
        fields = {"turn_id": turn} if client == "Codex" else {}
        result = self.turn(client, "UserPromptSubmit", session, prompt=prompt, **fields)
        self.turn(client, "Stop", session, last_assistant_message="The duty roster is pencilled in.", **fields)
        return result["hookSpecificOutput"]["additionalContext"]

    def enter_other_product(self):
        records.create(self.root, "company-context", "context/company/overview.md")
        records.create(self.root, "product-context", "context/products/invoices/overview.md", "Invoices")
        self.cwd = self.work / "workspace/initiatives/invoices"
        self.cwd.mkdir(parents=True, exist_ok=True)

    def test_selected_handoff_survives_generic_turns_without_recording(self):
        self.enter_other_product()
        records.create(self.root, "product-context", "context/products/harbour/overview.md", "Harbour")
        chosen = self.save_handoff("Harbour review")
        other = self.save_handoff("Harbour staffing")
        request = "Please pick back up our Harbour review."
        self.assertFalse(session_journal.status(self.work)["enabled"])
        for client in ("Codex", "Claude"):
            with self.subTest(client=client):
                sid = "default-journal-" + client
                self.turn(client, "SessionStart", sid)
                prompts = (request, "Continue.", "Can we continue?", "Please make it more concise.", "Can you make it shorter?")
                for i, prompt in enumerate(prompts):
                    context = self.work_turn(client, sid, str(i), prompt)
                    self.assertIn(chosen["id"], context)
                    self.assertIn("Check the support rota.", context)
                    self.assertNotIn(other["id"], context)
                    if i:
                        snapshots = [json.loads(line) for line in context.splitlines() if line.startswith("{")]
                        self.assertIn("harbour", [row["scope"].get("product") for row in snapshots if "conversation" in row])
                for delegated in ("Continue.", "Resume Harbour staffing."):
                    nested = self.turn(client, "UserPromptSubmit", sid, agent_id="worker", prompt=delegated)
                    context = nested["hookSpecificOutput"]["additionalContext"]
                    self.assertNotIn(chosen["id"], context)
                    self.assertNotIn(other["id"], context)
                self.assertIn(chosen["id"], self.work_turn(client, sid, "after-worker", "Continue."))
                fresh = self.work_turn(client, sid + "-fresh", "first", "Continue.")
                self.assertIn(chosen["id"], fresh)
                self.assertIn(other["id"], fresh)
                state = b"\n".join(p.read_bytes() for p in (self.work / ".state").rglob("*") if p.is_file())
                for text in (request, "Please make it more concise.", "The duty roster is pencilled in."):
                    self.assertNotIn(text.encode(), state)
                self.assertFalse(session_journal.location(self.work).exists())
                self.assertEqual(session_journal.read_session(self.work, client.lower(), sid)["events"], [])
                switched = self.work_turn(client, sid, "switch", "Switch to product/invoices.")
                self.assertNotIn(chosen["id"], switched)
                later = self.work_turn(client, sid, "later", "Continue.")
                self.assertIn(chosen["id"], later)
                self.assertIn(other["id"], later)

    def test_named_native_resume_applies_the_saved_mode_to_later_turns(self):
        self.enter_other_product()
        self.save_handoff("Harbour staffing")
        record, step = "workspace/problems/invoices.md", "Verify the dispatch labels."
        records.create(self.root, "problem", record, "Export labels")
        preview = self.cli("conversation", "checkpoint", "preview", record, payload={"mode": "quiet", "next_action": step})
        self.cli("conversation", "checkpoint", "apply", record, payload=preview)
        for client in ("Codex", "Claude"):
            with self.subTest(client=client):
                sid = "native-mode-" + client
                turns = (("Resume the export labels.", "Quiet"), ("Continue.", "Quiet"),
                         ("Expedite mode. Resume the export labels.", "Expedite"), ("What's next?", "Expedite"))
                for i, (prompt, pace) in enumerate(turns):
                    context = self.work_turn(client, sid, str(i), prompt)
                    self.assertIn(record, context)
                    self.assertIn(step, context)
                    self.assertIn(pace + " mode is active", context)
                    self.assertNotIn('"product": "invoices"', context)
                switched = self.work_turn(client, sid, "switch", "Resume Harbour staffing.")
                self.assertNotIn("Expedite mode is active", switched)
                self.assertNotIn(record, switched)
                self.assertNotIn('"product": "invoices"', switched)
                resumed = self.work_turn(client, sid, "back", "Resume the export labels.")
                self.assertIn("Quiet mode is active", resumed)
                pending = sid + "-choose-pace-first"
                with patch.object(self, "cwd", self.root):
                    self.work_turn(client, pending, "pace", "Expedite mode.")
                    chosen = self.work_turn(client, pending, "select", "Resume the export labels.")
                self.assertIn("Expedite mode is active", chosen)
                self.assertIn(step, chosen)

    def test_followup_scope_through_real_hooks_and_task_switches(self):
        session_journal.configure(self.work, enabled=True)
        first = self.save_handoff("Harbour review")
        second = self.save_handoff("Harbour staffing")
        scope = "work/handoff/" + first["id"]
        other = "work/handoff/" + second["id"]
        for client in ("Claude", "Codex"):
            with self.subTest(client=client):
                sid = "scope-" + client
                start = self.exchange(client, sid, "one", "Resume the Harbour review.")
                self.assertEqual([event["scope"] for event in start], [scope, scope])
                followup = self.exchange(client, sid, "two", "Keep the existing pilot schedule.")
                self.assertEqual([event["scope"] for event in followup], [scope, scope])
                self.assertEqual(session_journal.later_exchanges(self.work, start[-1]["id"], scope=scope), followup)
                self.assertIsNone(self.exchange(client, sid+"-fresh", "one", "Keep the existing pilot schedule.")[0]["scope"])
                self.assertEqual(self.exchange(client, sid, "three", "Continue.")[0]["scope"], scope)
                self.assertEqual(self.exchange(client, sid, "switch", "Resume Harbour staffing.")[0]["scope"], other)
                self.assertEqual(self.exchange(client, sid, "four", "What about the support rota?")[0]["scope"], other)
                self.assertIsNone(self.exchange(client, sid, "exit", "Leave this task.")[0]["scope"])
                self.assertIsNone(self.exchange(client, sid, "after-exit", "Keep the existing pilot schedule.")[0]["scope"])
                self.assertEqual(self.exchange(client, sid, "resume-again", "Resume Harbour review.")[0]["scope"], scope)
                self.assertIsNone(self.exchange(client, sid, "switch-subject", "Switch to product/invoices.")[0]["scope"])
                self.assertIsNone(self.exchange(client, sid, "post-switch", "Keep the existing pilot schedule.")[0]["scope"])
                self.assertEqual(self.exchange(client, sid, "another-resume", "Resume Harbour review.")[0]["scope"], scope)
                self.assertIsNone(self.exchange(client, sid, "vacation", "Help me plan my vacation schedule.")[0]["scope"])
                self.assertIsNone(self.exchange(client, sid, "after-vacation", "Keep the existing pilot schedule.")[0]["scope"])
                for i, unrelated in enumerate(("Keep the existing vacation schedule.",
                                               "Yes, I have a separate medical question.")):
                    self.assertEqual(self.exchange(client, sid, f"review-{i}", "Resume Harbour review.")[0]["scope"], scope)
                    self.assertIsNone(self.exchange(client, sid, f"unrelated-{i}", unrelated)[0]["scope"])

    def test_restored_handoff_and_new_consent_require_a_new_resume(self):
        checkpoint = self.save_handoff("Harbour review")
        scope = "work/handoff/" + checkpoint["id"]
        path = self.work / work_handoffs.FILE
        original = path.read_bytes()
        client, sid = "Codex", "scope-consent"
        def exchange(turn, prompt):
            return self.exchange(client, sid, turn, prompt)[0]["scope"]
        self.work_turn(client, sid, "before-consent", "Resume Harbour review.")
        session_journal.configure(self.work, enabled=True)
        self.assertIsNone(exchange("first-consent", "Keep the existing pilot schedule."))
        self.assertEqual(exchange("resume", "Resume Harbour review."), scope)
        path.unlink()
        self.assertIsNone(exchange("deleted", "Keep the existing pilot schedule."))
        path.write_bytes(original)
        self.assertIsNone(exchange("restored", "Keep the existing pilot schedule."))
        self.assertEqual(exchange("authorized", "Resume Harbour review."), scope)
        self.assertEqual(exchange("next", "Keep the existing pilot schedule."), scope)
        session_journal.configure(self.work, enabled=False)
        session_journal.configure(self.work, enabled=True)
        self.assertIsNone(exchange("new-permission", "Keep the existing pilot schedule."))
        self.assertEqual(exchange("new-resume", "Resume Harbour review."), scope)
        session_journal.delete(self.work, client=client.lower(), session_id=sid)
        self.assertIsNone(exchange("deleted-journal", "Keep the existing pilot schedule."))

    def test_record_handoff_recovers_only_related_exchanges_in_the_same_product(self):
        session_journal.configure(self.work, enabled=True)
        records.create(self.root, "company-context", "context/company/overview.md")
        records.create(self.root, "product-context", "context/products/billing/overview.md", "Billing")
        record = "workspace/problems/bulk-export.md"
        records.create(self.root, "problem", record, "Bulk export")
        work = self.cli("handoff", "resume", "Bulk export")["work"]
        scope = work["journal_scope"]
        for client, receiver in (("Codex", "Claude"), ("Claude", "Codex")):
            with self.subTest(client=client):
                sid = "record-selection-" + client
                opening = self.exchange(client, sid, "open", f"Review {record} for Billing.",
                                        reply="The draft lists the export formats.")
                reference = self.cli("journal", "reference", "--client", client.lower(), "--session", sid, "--scope", scope)
                self.assertEqual(reference["id"], opening[-1]["id"])
                task = {"name": "Export checkpoint from " + client, "scope": work["scope"],
                        "objective": "Review the bulk export draft.", "open_question": "Which formats do we support?",
                        "next_step": "Confirm the supported formats.", "owner": {"record": record, "revision": work["revision"]},
                        "journal": [reference["id"]], "journal_reference_scope": scope}
                review = self.cli("handoff", "preview", payload=task)
                self.cli("handoff", "save", payload={"review": review, "approved": True})

                related = self.exchange(client, sid, "shorten", "Can you make it shorter?",
                                        reply="The two supported export formats are CSV and JSON.")
                email = self.exchange(client, sid, "email", "Draft a Billing email about annual renewals.",
                                      reply="The annual renewal letter includes the May deadline.")
                revision = self.exchange(client, sid, "edit-email", "Revise it.", reply="The revised renewal letter is ready.")
                output = self.turn(receiver, "UserPromptSubmit", "receive-" + client, prompt="Resume " + task["name"] + ".")
                guidance = output["hookSpecificOutput"]["additionalContext"]
                snapshots = [json.loads(line) for line in guidance.splitlines() if line.startswith("{")]
                resumed, = [row["work"] for row in snapshots if row.get("status") == "resume"]
                self.assertEqual(resumed["since_checkpoint"], related)
                self.assertEqual([row["scope"] for row in opening + related], [scope] * 4)
                self.assertEqual([row["scope"] for row in email + revision], [None] * 4)
                self.assertNotIn("renewal letter", guidance)
