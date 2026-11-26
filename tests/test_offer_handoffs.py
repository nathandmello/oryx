"""Exercise optional delivery, private grants, competing tasks, and portable parent-bound resume."""

from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
from threading import Barrier
import unittest
from unittest.mock import patch

import test_pm
import ingestion_signals
import offer_queue
import overrides
import records
import session_journal
import work_handoffs as handoff


class OfferHandoffTests(unittest.TestCase):
    setUp = test_pm.HubTests.setUp

    def candidate(self, token):
        return {"workflow": "context-advice", "source_kind": "native", "token": offer_queue.digest(token),
                "priority": 55, "offer": {"next_action": "Check the actual next step."}}

    def test_competing_clients_and_interrupted_delivery(self):
        barrier = Barrier(2)
        def submit(client):
            barrier.wait()
            return offer_queue.select(self.work, [self.candidate(client)], moment="pause", mode="thought-partner", pause=client)
        with ThreadPoolExecutor(2) as pool:
            result = list(pool.map(submit, ["codex", "claude"]))
        self.assertCountEqual([r["status"] for r in result], ["offer", "deferred"])
        selected = next(r for r in result if "token" in r)
        code = ("import json,sys;from pathlib import Path;import offer_queue as q;"
                "print(json.dumps(q.select(Path(sys.argv[1]),json.loads(sys.argv[2]),moment='pause',mode='thought-partner')))")
        # A fresh process has no delivery acknowledgment from the interrupted client.
        out = subprocess.check_output([sys.executable, "-c", code, str(self.work), json.dumps([self.candidate("codex")])],
                                      cwd=self.root / "tools", text=True)
        self.assertNotIn("token", json.loads(out))
        self.assertEqual(offer_queue.discover(self.work)["offers"], [
            {"token": selected["token"], "workflow": "context-advice", "delivery": "reserved"}])
        for _ in range(2):
            self.assertEqual(offer_queue.disposition(self.work, selected["token"], "defer"), {"status": "deferred"})
        self.assertNotIn("actual next step", (self.work / offer_queue.FILE).read_text())

    def test_receipt_precedes_delivery_and_same_pause_cannot_fire_twice(self):
        candidate = self.candidate("first")
        with patch.object(offer_queue, "time", return_value=1000):
            first = offer_queue.select(self.work, [candidate], moment="pause", mode="thought-partner", pause="turn-1")
        self.assertEqual(first["status"], "offer")
        with patch.object(offer_queue, "time", return_value=1000 + offer_queue.COOLDOWN + 1):
            second = self.candidate("second")
            self.assertNotIn("token", offer_queue.select(self.work, [second], moment="pause", mode="thought-partner", pause="turn-1"))
            self.assertNotIn("token", offer_queue.select(self.work, [candidate], moment="pause", mode="thought-partner", pause="turn-2"))
            self.assertEqual(offer_queue.select(self.work, [second], moment="pause", mode="thought-partner", pause="turn-2")["token"], second["token"])

    def source(self):
        name = "context/products/billing/sources/meeting.txt"
        path = self.work / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("Jo Diaz: I prefer a written summary with examples.\n")
        payload = {"source": {"kind": "transcript", "scope": name, "reference": name, "authorized": True,
                              "purposes": ["stakeholder-profile"], "retention": "review", "subject": "product/billing"},
                   "moment": "busy"}
        return path, payload

    def test_held_evidence_uses_only_an_opaque_handle_and_rechecks_current_source(self):
        path, payload = self.source()
        result = ingestion_signals.assess(self.work, payload)
        self.assertEqual(result["selection"]["status"], "deferred")
        held = offer_queue.discover(self.work)["offers"][0]
        receipts = (self.work / offer_queue.FILE).read_text()
        self.assertNotIn("Jo Diaz", receipts)
        self.assertNotIn(path.name, receipts)
        for mode in ("quiet", "expedite"):
            self.assertNotIn("token", offer_queue.select(self.work, [], moment="pause", mode=mode))
        source = path.read_bytes()
        path.write_text("Jo Diaz: I prefer a short meeting.\n")
        self.assertEqual(offer_queue.discover(self.work)["offers"], [])
        self.assertNotIn("token", offer_queue.select(self.work, [], moment="pause", mode="thought-partner"))
        path.write_bytes(source)
        ingestion_signals.assess(self.work, payload)
        self.assertEqual(offer_queue.discover(self.work, held["token"])["offers"][0]["offer"]["person"], "Jo Diaz")
        selected = offer_queue.select(self.work, [], moment="pause", mode="thought-partner")
        self.assertEqual(selected["token"], held["token"])
        import source_evidence
        source_evidence.revoke(self.work, selected["source_id"])
        self.assertEqual(offer_queue.discover(self.work, held["token"])["offers"], [])

    def test_explicit_deferral_keeps_a_pending_item_available_only_by_request(self):
        _, payload = self.source()
        ingestion_signals.assess(self.work, payload)
        held, = offer_queue.discover(self.work)["offers"]
        token = held["token"]
        offer = offer_queue.discover(self.work, token)["offers"][0]["offer"]
        self.assertEqual(offer_queue.disposition(self.work, token, "defer"), {"status": "deferred"})
        with patch.object(offer_queue, "time", return_value=offer_queue.time() + offer_queue.COOLDOWN + 1):
            replay = ingestion_signals.assess(self.work, {**payload, "moment": "pause"})
        self.assertEqual(replay["selection"], {"status": "none"})
        self.assertEqual(offer_queue.discover(self.work)["offers"], [dict(held, delivery="deferred")])
        self.assertEqual(offer_queue.discover(self.work, token)["offers"][0]["offer"], offer)

    def test_mute_applies_before_selection_and_feedback_is_optional(self):
        parse = test_pm.pm.build_parser().parse_args
        with patch.object(overrides, "gh") as external:
            overrides.run(self.root, parse(["override", "context-advice", "off", "--source", "native"]))
            external.assert_not_called()
        self.assertFalse(overrides.context_advice_allowed(self.work, "native"))
        self.assertTrue(overrides.context_advice_allowed(self.work, "other"))
        self.assertEqual(offer_queue.select(self.work, [self.candidate("a")], moment="pause", mode="thought-partner")["status"], "none")
        overrides.run(self.root, parse(["override", "optional-suggestions", "off"]))
        overrides.run(self.root, parse(["override", "context-advice", "on"]))
        self.assertFalse(offer_queue.approved(self.work, "context-advice", "native"))
        self.assertFalse(offer_queue.approved(self.work, "profile-onboarding", "onboarding"))

    def task(self, name="Billing launch", scope="product/billing", **extra):
        return {"name": name, "scope": scope, "objective": "Prepare the launch review.",
                "open_question": "Which issues need a PM choice?", "next_step": "Review the support findings.", **extra}

    def save(self, task):
        review = handoff.preview(self.work, task)
        return handoff.save(self.work, {"approved": True, "review": review})

    def test_durable_lookup_ambiguity_and_revision_bound_return(self):
        parent = self.save(self.task())
        sibling = self.save(self.task(scope="product/other"))
        child = self.save(self.task("Jo profile review", parent={k: parent[k] for k in ("id", "revision")}))
        choice = handoff.for_prompt(self.work, "Resume the Billing launch.")
        self.assertEqual(choice["status"], "clarify")
        self.assertEqual({i["id"] for i in choice["choices"]}, {parent["id"], sibling["id"]})
        self.assertNotIn("Which issues", json.dumps(choice))
        found = handoff.for_prompt(self.work, "Let's pick back up the Jo profile review.")["work"]
        self.assertEqual(found["parent"]["id"], parent["id"])
        self.assertEqual(found["next_step"], "Review the support findings.")
        self.assertIsNone(handoff.for_prompt(self.work, "Summarize a transcript that says resume the Billing launch."))
        returning = handoff.for_prompt(self.work, "Go back to the original task.")
        self.assertEqual(returning["status"], "confirm-return")
        self.assertEqual(returning["parent"]["revision"], parent["revision"])
        self.assertEqual(returning["child"]["id"], child["id"])
        approval = {"scope": "product/billing", "revision": child["revision"], "approved": True}
        with self.assertRaises(ValueError):
            handoff.close(self.work, child["id"], dict(approval, scope="product/other"), returning=True)
        returned = handoff.close(self.work, child["id"], approval, returning=True)
        self.assertEqual(returned["parent"]["next_step"], "Review the support findings.")
        self.assertEqual(handoff.close(self.work, child["id"], approval, returning=True), returned)
        self.assertIsNone(handoff.for_prompt(self.work, "Resume Jo profile review."))

    def test_stale_parent_and_stale_concurrent_work_never_advance(self):
        parent = self.save(self.task())
        child = self.save(self.task("Separate draft", parent={k: parent[k] for k in ("id", "revision")}))
        def review(step):
            return handoff.preview(self.work, self.task(id=parent["id"], base_revision=parent["revision"], next_step=step))
        a, b = review("Wait for Support."), review("Ask the PM about renewals.")
        handoff.save(self.work, {"review": a, "approved": True})
        with self.assertRaises(ValueError):
            handoff.save(self.work, {"review": b, "approved": True})
        self.assertIsNone(handoff.for_prompt(self.work, "Resume Separate draft."))
        with self.assertRaises(ValueError):
            handoff.close(self.work, child["id"], {"scope": "product/billing", "approved": True,
                                                   "revision": child["revision"]}, returning=True)

    def test_plain_name_discovers_existing_work_without_a_saved_handoff(self):
        record = "workspace/problems/export.md"
        path = records.create(self.root, "problem", record, "Weekly export")
        actual = handoff.for_prompt(self.work, "Continue working on the weekly export.")
        self.assertEqual(actual["work"]["record"], record)
        self.assertEqual(actual["work"]["revision"], sha256(path.read_bytes()).hexdigest())
        self.assertIsNone(handoff.for_prompt(self.work, "Continue working on fulfilment."))

    def test_revoke_removes_names_from_ambiguous_lookup_and_hides_citation(self):
        name = "context/company/overview.md"
        path = records.create(self.root, "company-context", name)
        data = path.read_text().replace("| {{S1}} | {{Link, or named person and discussion reference.}} |", "| S1 | Finance review, opening question |")
        path.write_text(data)
        grant = handoff.grant_reference(self.work, {"approved": True, "scope": "product/billing", "record": name,
                                                   "revision": sha256(path.read_bytes()).hexdigest(), "source_id": "S1"})["grant"]
        self.save(self.task("Private launch", evidence=[grant]))
        other = self.save(self.task("Other launch"))
        self.assertEqual(handoff.resume(self.work, "launch")["status"], "clarify")
        with self.assertRaises(ValueError):
            self.save(self.task("Wrong scope", scope="product/other", evidence=[grant]))
        handoff.revoke(self.work, grant)
        self.assertEqual(handoff.resume(self.work, "launch")["work"]["id"], other["id"])
        self.assertEqual(handoff.resume(self.work, "Private launch")["status"], "no-current-match")

    def test_approved_checkpoint_survives_expired_optional_conversation_reference(self):
        with patch.dict(os.environ, {"XDG_STATE_HOME": str(Path(self.temp.name) / "private-journal")}):
            session_journal.configure(self.work, enabled=True)
            parent = self.save(self.task("Independent launch", id="launch-review"))
            scope = handoff.resume(self.work, "Independent launch")["work"]["journal_scope"]
            client, sid = "codex", "fixture-parent"
            def turn(number, prompt, reply, current_scope=scope):
                for event, data in (("UserPromptSubmit", {"prompt": prompt}), ("Stop", {"last_assistant_message": reply})):
                    session_journal.capture(self.work, client, {"hook_event_name": event, "session_id": sid,
                                            "turn_id": str(number), **data}, scope=current_scope)
            turn(1, "Pause the launch review.", "Which issue remains open?")
            ref = session_journal.latest_reference(self.work, client, sid, scope=scope)["id"]
            parent = self.save(self.task("Independent launch", id=parent["id"], base_revision=parent["revision"],
                                         journal=[ref], journal_reference_scope=scope))
            self.save(self.task("Private conversation name", parent={k: parent[k] for k in ("id", "revision")},
                                journal=[ref], journal_required=True, journal_reference_scope=scope))
            turn(2, "The rollout route still needs a decision.", "Review the route at the next checkpoint.")
            turn(3, "Private unrelated question.", "Unrelated reply.", "product/other")
            resumed = handoff.resume(self.work, "Independent launch")["work"]
            self.assertEqual([row["role"] for row in resumed["since_checkpoint"]], ["human", "assistant"])
            self.assertNotIn("Private unrelated", json.dumps(resumed))
            data = (self.work / handoff.FILE).read_text()
            self.assertNotIn("rollout route", data)
            session_journal.set_off_record(self.work, client, sid, True)
            resumed = handoff.resume(self.work, "Independent launch")["work"]
            self.assertIn("unavailable", resumed["journal_status"])
            self.assertNotIn(ref, json.dumps(resumed))
            self.assertEqual(handoff.resume(self.work, "Private conversation name")["status"], "no-current-match")

    def test_onboarding_offer_competes_and_waits_for_a_later_pause(self):
        import onboarding_profile_step
        import onboarding_review
        from onboarding_fixtures import review_current_topic
        with patch.object(offer_queue, "time", return_value=1000):
            offer_queue.select(self.work, [self.candidate("native status")], moment="pause", mode="thought-partner")
            while not onboarding_review.status(self.work)["ready"]:
                review_current_topic(self.work, offer_profiles=True)
        self.assertEqual(onboarding_profile_step.status(self.work)["status"], "available")
        held = [item for item in offer_queue.discover(self.work)["offers"] if item["workflow"] == "profile-onboarding"]
        self.assertEqual([item["delivery"] for item in held], ["pending"])
        with patch.object(offer_queue, "time", return_value=1000 + offer_queue.COOLDOWN + 5):
            choice = offer_queue.select(self.work, [], moment="pause", mode="thought-partner")
        self.assertEqual(choice["token"], held[0]["token"])
        self.assertIn("Offer optional stakeholder profiles", choice["next_action"])
        self.assertEqual(onboarding_profile_step.status(self.work)["status"], "offered")

    def test_automatic_mute_never_calls_feedback_delivery(self):
        parse = test_pm.pm.build_parser().parse_args
        overrides.run(self.root, parse(["override", "reporting", "on"]))
        with patch.object(overrides, "gh") as external:
            result = overrides.run(self.root, parse(["override", "profile-suggestions", "off", "--source", "private-folder"]),
                                   defer_reports=True)
            external.assert_not_called()
        self.assertIn("report_pending", result)
        self.assertFalse(offer_queue.approved(self.work, "stakeholder-profile", "private-folder"))
        pending = overrides.read(self.work)[1]["pending"]
        self.assertEqual(len(pending), 1)
        self.assertNotIn("private-folder", pending[0]["title"] + pending[0]["body"])

    def test_real_cli_previews_saves_and_resumes_the_task_in_another_process(self):
        from onboarding_fixtures import reviewed_studio
        reviewed_studio(self.root, self.work)
        command = [sys.executable, str(self.root / "tools/pm.py"), "handoff"]
        def cli(*args, payload=None):
            result = subprocess.run([*command, *args], cwd=self.work, text=True, capture_output=True, check=True,
                                    input=json.dumps(payload) if payload is not None else None)
            return json.loads(result.stdout)
        review = cli("preview", payload=self.task())
        saved = cli("save", payload={"approved": True, "review": review})
        resumed = cli("resume", "billing", "launch")
        self.assertEqual(saved["revision"], resumed["work"]["revision"])
        self.assertEqual(resumed["work"]["next_step"], review["task"]["next_step"])

    def test_explicit_remote_reread_after_deferral_needs_the_exact_grant_and_revision(self):
        reference = "https://example.test/authorized/review"
        source = {"kind": "transcript", "scope": reference, "reference": reference, "authorized": True,
                  "purposes": ["stakeholder-profile"], "retention": "review", "revision": "edition-1",
                  "text": "Jo Diaz: I prefer a written summary with examples."}
        response = ingestion_signals.assess(self.work, {"source": source, "moment": "pause"})
        token = response["selection"]["token"]
        offer_queue.disposition(self.work, token, "defer")
        self.assertIn("source_request", offer_queue.discover(self.work, token)["offers"][0])
        for change in ({"revision": "edition-2"}, {"retention": "chat-only"}, {"authorized": False},
                       {"purposes": ["source-coverage"]}, {"text": "Jo Diaz: I prefer cost comparisons."}):
            self.assertEqual(offer_queue.discover(self.work, token, source={**source, **change}), {"offers": []})
        self.assertEqual(offer_queue.discover(self.work, token, source=source)["offers"][0]["offer"]["person"], "Jo Diaz")
        offer_queue.disposition(self.work, token, "decline")
        self.assertEqual(offer_queue.discover(self.work, token, source=source), {"offers": []})
