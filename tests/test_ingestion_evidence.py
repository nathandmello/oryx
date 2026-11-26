"""Exercise the original-source review boundary through Studio's ordinary commands."""

import json
import subprocess
import sys
import unittest
from unittest.mock import patch

import test_pm
from onboarding_fixtures import reviewed_setup
import context_capture
import ingestion_signals
import offer_queue
import source_evidence
import stakeholder_profiles
import stakeholder_signals


def stalled_consumer(*args, **kwargs):
    from threading import Event
    Event().wait(15)
    raise AssertionError("Unresponsive subscriber ran past its deadline")


class IngestionEvidenceTests(unittest.TestCase):
    def setUp(self):
        reviewed_setup(self)
        # These meetings take place on the day after the onboarding offer.
        path = self.work / offer_queue.FILE
        if path.exists():
            receipts = json.loads(path.read_text())
            for receipt in receipts.values():
                receipt.update(at=0, status="presented")
            path.write_text(json.dumps(receipts))

    line = "[03:20] Jo Diaz: I do not want slides unless the customer asks."
    second = "[03:22] Arun Rao: I prefer cost comparisons for renewal reviews."

    def source(self, **changes):
        ref = "context/notes/meeting.txt"
        return {"reference": ref, "scope": ref, "kind": "transcript", "source_id": "meeting-28",
                "authorized": True, "purposes": ["stakeholder-profile"], "retention": "review", **changes}

    def transcript(self, text=None):
        path = self.work / self.source()["reference"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text((text or self.line) + "\n")
        return path

    def cli(self, args, body, *, ok=True):
        p = subprocess.run([sys.executable, "tools/pm.py", *args], cwd=self.root, text=True,
                           input=json.dumps(body), capture_output=True)
        self.assertEqual(p.returncode == 0, ok, p.stdout + p.stderr)
        return json.loads(p.stdout) if ok else p.stdout + p.stderr

    def as_change(self, found):
        return {"name": found["person"], "id": "jo", "role": "Service lead", **{k: found[k] for k in (
            "topic", "kind", "wording", "source", "excerpt", "scope", "subject", "observed_on", "attribution", "evidence")}}

    def test_pm_can_decline_a_pending_offer_found_by_request(self):
        other = "[03:22] Jo Diaz: I prefer cost comparisons for renewal reviews."
        self.transcript(self.line + "\n" + other)
        source = self.source(subject="product/billing")
        first = self.cli(["ingestion", "assess"], {"source": source, "moment": "pause", "observations": {
            "stakeholder-profile": [{"person": "Jo Diaz", "excerpt": self.line}]}})["selection"]
        self.cli(["offer", "presented", first["token"]], {})
        review = self.cli(["stakeholder-profile", "preview"], self.as_change(first))
        self.cli(["stakeholder-profile", "accept"], {"review": review, "approved_wording": first["wording"]})

        self.cli(["ingestion", "assess"], {"source": source, "moment": "busy"})
        held, = self.cli(["offer", "list"], {})["offers"]
        self.assertEqual(held["delivery"], "pending")
        token = held["token"]
        shown, = self.cli(["offer", "show", token], {})["offers"]
        self.assertEqual(shown["offer"]["excerpt"], other)
        self.assertIn("natural pause", self.cli(["offer", "presented", token], {}, ok=False))
        for _ in range(2):
            self.assertEqual(self.cli(["offer", "decline", token], {}), {"status": "declined"})
        self.assertNotIn("grant_ref", offer_queue.read(self.work)[1][token])
        self.assertEqual(self.cli(["offer", "show", token], {}), {"offers": []})
        self.assertEqual(self.cli(["offer", "list"], {}), {"offers": []})
        with patch.object(offer_queue, "time", return_value=offer_queue.time() + offer_queue.COOLDOWN + 1):
            replay = ingestion_signals.assess(self.work, {"source": source, "moment": "pause"})
        self.assertEqual(replay["selection"], {"status": "none"})
        context = self.cli(["task-context", "--product", "billing", "Draft an update for Jo Diaz."], {})
        person, = context["stakeholder_profiles"]["people"]
        self.assertEqual([entry["wording"] for entry in person["entries"]], [first["wording"]])
        self.assertNotIn("cost comparisons", json.dumps(context))

    def test_transcript_to_profile_rejects_forged_person_time_and_inverted_meaning(self):
        self.transcript(self.line + "\n" + self.second)
        wrong = {"person": "Arun Rao", "excerpt": "I do not want slides unless the customer asks.",
                 "wording": "Arun prefers slides.", "locator": "03:22", "significance": "material"}
        good = {"person": "Jo Diaz", "excerpt": self.line, "locator": "03:20"}
        rows = [wrong, {**good, "locator": "03:22"}, {**good, "wording": "Jo always wants slides."},
                {**good, "scope": "Every review"}, {**good, "observed_on": "2024-01-01"}, good]
        data = self.cli(["ingestion", "assess"], {"source": self.source(), "moment": "pause",
                        "observations": {"stakeholder-profile": rows}})
        self.assertEqual(data["consumers"]["stakeholder-profile"]["unsupported_rows"], 5)
        offer = data["selection"]
        self.assertEqual(offer["person"], "Jo Diaz")
        self.assertIn(self.line, offer["excerpt"])
        self.assertTrue(offer["conditional_or_uncertain"])
        change = self.as_change(offer)
        for edit in ({"name": "Arun Rao"}, {"wording": "Jo wants slides."}, {"observed_on": "2024-03-20"},
                     {"source": "Jo, 03:22"}, {"subject": "general"}):
            with self.subTest(edit=edit):
                with self.assertRaises(ValueError):
                    stakeholder_profiles.preview(self.work, {**change, **edit})
        change["wording"] = "At 03:20, Jo Diaz does not want slides unless the customer asks."
        review = self.cli(["stakeholder-profile", "preview"], change)
        result = self.cli(["stakeholder-profile", "accept"], {"review": review, "approved_wording": change["wording"]})
        self.assertTrue(result["written"])
        found = self.cli(["stakeholder-profile", "show", "jo"], {})["entries"][0]
        self.assertEqual(found["excerpt"], self.line)
        self.assertEqual(found["evidence"], offer["evidence"])

    def test_role_annotation_preserves_the_named_speaker_and_entire_passage(self):
        line = "09:01 Inez Vale (field maintenance crew): I need three options for roadmap reviews."
        self.transcript(line)
        result = self.cli(["ingestion", "assess"], {"source": self.source(), "moment": "pause",
                          "observations": {"stakeholder-profile": [
                              {"person": "Inez Vale", "excerpt": "I need three options for roadmap reviews."}]}})
        offer = result["selection"]
        self.assertEqual((offer["person"], offer["excerpt"]), ("Inez Vale", line))
        change = dict(self.as_change(offer), id="inez", name="Inez Vale", role="Designer")
        review = self.cli(["stakeholder-profile", "preview"], change)
        saved = self.cli(["stakeholder-profile", "accept"], {"review": review, "approved_wording": change["wording"]})
        self.assertTrue(saved["written"])
        self.transcript(line.replace("(field maintenance crew)", "(quoting the service team)"))
        ambiguous = self.cli(["ingestion", "assess"], {"source": self.source(), "moment": "busy",
                             "observations": {"stakeholder-profile": [{"person": "Inez Vale",
                                                                       "excerpt": "I need three options for roadmap reviews."}]}})
        self.assertEqual(ambiguous["consumers"]["stakeholder-profile"]["unsupported_rows"], 1)
        self.assertNotIn("selection", ambiguous)

    def test_unresolved_initiative_parent_preserves_the_source_and_defers_filing(self):
        quote = "Nia may approve copies for the trial week."
        source = {"reference": "Fictional review", "date": "unknown", "checked_on": "2025-11-25",
                  "coverage": "read", "text": quote}
        entry = {"scope": "initiative", "initiative": "checkout-notes", "topic": "decisions",
                 "source": 1, "location": "sentence 1", "quote": quote}
        target = self.work / "context/initiatives/checkout-notes/overview.md"
        payload = {"sources": [source], "entries": [entry]}
        deferred = self.cli(["route-context"], payload)["entries"][0]
        self.assertEqual((deferred["disposition"], deferred["destination"], deferred["quote"]),
                         ("deferred", None, quote))
        self.assertEqual(deferred["pending_initiative"], "checkout-notes")
        self.assertIn("product", deferred["follow_up"])
        self.assertFalse(target.exists())
        protected = dict(entry, record={"path": "context/initiatives/checkout-notes/overview.md"})
        message = self.cli(["route-context"], {**payload, "entries": [protected]}, ok=False)
        self.assertIn("owning product", message)
        self.assertFalse(target.exists())

    def test_accept_rechecks_current_bytes_revision_and_explicit_revocation(self):
        path = self.transcript()
        source = self.source(revision="v1")
        offer = ingestion_signals.assess(self.work, {"source": source, "moment": "pause"})["selection"]
        change = self.as_change(offer)
        review = stakeholder_profiles.preview(self.work, change)
        approved = {"review": review, "approved_wording": change["wording"]}
        path.write_text(self.line.replace("do not want", "prefer") + "\n")
        with self.assertRaisesRegex(ValueError, "changed"):
            stakeholder_profiles.accept(self.work, approved)
        self.assertFalse(stakeholder_signals.allowed_handle(self.work, offer["evidence"]))
        path.write_text(self.line + "\n")
        ingestion_signals.assess(self.work, {"source": {**source, "revision": "v2"}})
        with self.assertRaisesRegex(ValueError, "permission"):
            stakeholder_profiles.accept(self.work, approved)
        source_evidence.revoke(self.work, "meeting-28")
        with patch.object(source_evidence, "material", side_effect=AssertionError("reopened revoked text")):
            res = ingestion_signals.assess(self.work, {"source": source})
        self.assertEqual(res["consumers"]["stakeholder-profile"]["status"], "revoked")
        self.assertFalse(stakeholder_profiles.path_for(self.work, "jo").exists())

    def test_remote_article_requires_fresh_scoped_read_and_pm_interpretation(self):
        ref = "https://example.test/reviews/28"
        src = self.source(kind="article", reference=ref, scope="https://example.test/reviews/", revision="r4",
                          text='Jo Diaz wrote, “I prefer short written updates only for weekly reviews.”')
        offer = ingestion_signals.assess(self.work, {"source": src, "moment": "pause"})["selection"]
        handle = offer["evidence"]
        self.assertIsNone(stakeholder_signals.recall(self.work, handle))
        self.assertEqual(stakeholder_signals.source_request(self.work, handle)["reference"], ref)
        self.assertIsNone(stakeholder_signals.recall(self.work, handle, source={**src, "purposes": ["handoff"]}))
        self.assertIsNone(stakeholder_signals.recall(self.work, handle, source={**src, "revision": "r5"}))
        self.assertEqual(stakeholder_signals.recall(self.work, handle, source=src)["excerpt"], src["text"])
        change = {**self.as_change(offer), "kind": "hypothesis", "attribution": "PM",
                  "wording": "I think a short weekly email might work for Jo.", "source_read": src}
        review = stakeholder_profiles.preview(self.work, change)
        approved = {"review": review, "approved_wording": change["wording"]}
        with self.assertRaisesRegex(ValueError, "fresh authorized"):
            stakeholder_profiles.accept(self.work, approved)
        with self.assertRaises(ValueError):
            stakeholder_profiles.accept(self.work, {**approved, "source_read": {**src, "authorized": False}})
        stakeholder_profiles.accept(self.work, {**approved, "source_read": src})
        self.assertEqual(stakeholder_profiles.show(self.work, "jo")["pm_hypotheses"][0]["wording"], change["wording"])

    def test_replay_across_sources_preserves_new_sibling_and_writes_no_raw_text(self):
        self.transcript(self.line)
        src = self.source(event_id="ops-review")
        ingestion_signals.assess(self.work, {"source": src})
        mirror = self.source(kind="article", reference="article:ops", scope="article:ops", source_id="article-28",
                             event_id="ops-review", text='Jo Diaz wrote, “I do not want slides unless the customer asks.”\n'
                             'Arun Rao wrote, “I prefer cost comparisons for renewal reviews.”')
        ingestion_signals.assess(self.work, {"source": mirror})
        refs = offer_queue.discover(self.work)["offers"]
        self.assertEqual(len(refs), 2)
        self.assertNotIn("I prefer", (self.work / source_evidence.GRANTS).read_text())
        self.assertNotIn("Jo Diaz", (self.work / offer_queue.FILE).read_text())
        self.assertEqual(stakeholder_profiles.lookup(self.work), [])

    def test_partial_router_never_widens_and_discards_unsupported_prepared_claim(self):
        path = self.transcript(self.line + "\n" + self.second)
        meta = self.source()
        options = {k: meta[k] for k in ("kind", "retention", "purposes", "source_id")}
        src = {"reference": meta["reference"], "coverage": "read", "text": path.read_text(), "ingestion": options}
        rows = context_capture.ingestion_reviews(self.work, [src], [{"source": 1, "quote": self.second}], True)
        self.assertEqual(rows[0]["selection"]["status"], "deferred")
        _, state = source_evidence.state(self.work)
        grant, = state["grants"].values()
        self.assertEqual((grant["offset"], grant["length"]), (len(self.line.encode()), len(self.second.encode()) + 2))
        self.assertEqual(grant["coverage"], "partial")
        bad = context_capture.ingestion_reviews(self.work, [src], [{"source": 1, "quote": "prefer cost comparisons"}], True)
        self.assertEqual(bad, [])
        self.assertEqual(len(offer_queue.discover(self.work)["offers"]), 1)

    def test_silence_purpose_and_chat_only_gate_before_optional_sources_are_opened(self):
        base = self.source()
        for change in ({"purposes": []}, {"retention": "chat-only"}, {"coverage": "unavailable"}):
            with patch.object(source_evidence, "material", side_effect=AssertionError("opened excluded source")):
                ingestion_signals.assess(self.work, {"source": {**base, **change}})
        self.assertFalse((self.work / source_evidence.GRANTS).exists())
        src = self.source(kind="chat", reference="chat:a3", scope="chat:a3",
                          text="Off the record.\nJo Diaz prefers written weekly updates.")
        with patch("evidence_spans.attributed", side_effect=AssertionError("parsed restricted message")):
            res = ingestion_signals.assess(self.work, {"source": src})
        self.assertEqual(res["consumers"]["stakeholder-profile"]["status"], "excluded")

    def test_second_subscriber_gets_original_once_and_survives_unrelated_consumer_failure(self):
        self.transcript()
        def broken(private, packet, observations, **timing):
            packet["source"]["reference"] = "unrelated:record"
            raise LookupError("fault in subscriber")
        with patch("evidence_spans.attributed", wraps=ingestion_signals.evidence_spans.attributed) as parse:
            result = ingestion_signals.assess(self.work, {"source": self.source(purposes=["broken", "source-coverage"])},
                            consumers={"broken": broken, "source-coverage": ingestion_signals.coverage_review})
        self.assertEqual(parse.call_count, 1)
        self.assertEqual(result["consumers"]["broken"]["status"], "unavailable")
        self.assertEqual(result["consumers"]["source-coverage"]["source_id"], "meeting-28")

    def test_sender_authored_email_and_minutes_produce_grounded_offers_without_annotations(self):
        inputs = [
            ("email", "From: Uma Singh\nTo: Service Group\nSubject: Partner reviews\n\n"
             "Please send a comparison whenever a partner requests a rollout.", "Uma Singh"),
            ("minutes", "Planning session\nBea Cole requested a risk summary before each release review.\n"
             "Alex Eve will update the calendar tomorrow.", "Bea Cole"),
        ]
        for kind, original, person in inputs:
            with self.subTest(kind=kind):
                ref = kind + ":record"
                source = self.source(kind=kind, reference=ref, scope=ref, source_id=kind, text=original)
                # Force separate natural pauses for the two materials.
                with patch("offer_queue.time", return_value=2000000000 + inputs.index((kind, original, person)) * 86400):
                    result = ingestion_signals.assess(self.work, {"source": source, "moment": "pause"})
                offer = result["selection"]
                self.assertEqual((offer["status"], offer["person"], offer["kind"]), ("offer", person, "reported"))
                self.assertTrue(offer["conditional_or_uncertain"])
                self.assertIn(offer["excerpt"], original)
                if kind == "email":
                    self.assertIn("sender at byte 0", offer["locator"])
                    self.assertEqual(offer["attribution"], person)
                else:
                    self.assertEqual(offer["attribution"], ref)
                    self.assertNotIn("Alex", offer["wording"])

    def test_unfamiliar_work_criterion_private_review_round_trip(self):
        original = "Jo Diaz: My deciding factor is a named mechanic at shift change."
        self.transcript(original)
        source = self.source()
        review = self.cli(["ingestion", "assess"], {"source": source})["consumers"]["stakeholder-profile"]
        self.assertEqual(review["status"], "review")
        self.assertFalse((self.work / source_evidence.GRANTS).exists())
        passage, = review["passages"]
        output = self.cli(["ingestion", "assess"], {"source": source, "moment": "pause",
                          "observations": {"stakeholder-profile": [passage]}})
        offer = output["selection"]
        self.assertEqual(offer["person"], "Jo Diaz")
        self.assertEqual(offer["excerpt"], original)
        self.assertEqual(stakeholder_signals.recall(self.work, offer["evidence"])["wording"], offer["wording"])

    def test_partial_reread_cannot_construct_an_actor_or_drop_a_continuation(self):
        full = "It was not Jo Diaz: I prefer metrics.\nOnly when reporting to partners.\n"
        self.transcript(full.strip())
        excerpt = "Jo Diaz: I prefer metrics."
        src = self.source(coverage="partial", offset=full.index(excerpt), text=excerpt)
        result = ingestion_signals.assess(self.work, {"source": src, "moment": "pause"})
        self.assertNotIn("selection", result)
        self.assertFalse((self.work / source_evidence.GRANTS).exists())

    def test_hung_subscriber_cannot_delay_independent_coverage_or_foreground(self):
        from time import monotonic
        self.transcript()
        start = monotonic()
        with patch.object(ingestion_signals, "PER_CONSUMER_SECONDS", 0.12):
            result = ingestion_signals.for_task(self.work, {"source": self.source(purposes=["stalled", "source-coverage"])},
                        consumers={"stalled": stalled_consumer, "source-coverage": ingestion_signals.coverage_review})
        self.assertEqual(result["consumers"]["stalled"]["status"], "timed-out")
        self.assertEqual(result["consumers"]["source-coverage"]["status"], "checked")
        self.assertLess(monotonic() - start, 1.5)

    def test_reordered_mail_headers_cannot_become_speakers(self):
        ref = "email:team-review"
        source = self.source(reference=ref, scope=ref, kind="email", text=(
            "Date: Tue, 2 Jun 2026 09:10:00 GMT\n"
            "Subject: Please send rollout metrics before every review.\n"
            "From: Jo Diaz <jo@example.test>\nTo: team@example.test\n\n"
            "I prefer written updates for weekly reviews."))
        output = self.cli(["ingestion", "assess"], {"source": source, "moment": "pause"})
        self.assertEqual(output["selection"]["person"], "Jo Diaz")
        self.assertNotIn("rollout metrics", output["selection"]["excerpt"])
        forged = {"person": "Subject", "excerpt": "Please send rollout metrics before every review."}
        result = self.cli(["ingestion", "assess"], {"source": source, "moment": "pause",
                          "observations": {"stakeholder-profile": [forged]}})
        self.assertNotIn("selection", result)
        self.assertEqual(result["consumers"]["stakeholder-profile"]["unsupported_rows"], 1)

    def test_perspective_stays_in_quote_when_a_condition_refers_back_to_speaker(self):
        raw = "Jo Diaz: I prefer metrics only when I present the review."
        self.transcript(raw)
        source = self.source()
        offer = self.cli(["ingestion", "assess"], {"source": source, "moment": "pause"})["selection"]
        self.assertEqual(offer["wording"], "Jo Diaz said, “I prefer metrics only when I present the review.”")
        wrong = {**self.as_change(offer), "wording": "Jo Diaz prefers metrics only when I present the review."}
        self.assertIn("unsupported", self.cli(["stakeholder-profile", "preview"], wrong, ok=False))
        review = self.cli(["stakeholder-profile", "preview"], self.as_change(offer))
        saved = self.cli(["stakeholder-profile", "accept"], {"review": review, "approved_wording": offer["wording"]})
        self.assertTrue(saved["written"])


    def test_threaded_client_terminates_stalled_worker(self):
        from concurrent.futures import ThreadPoolExecutor
        from time import monotonic
        start = monotonic()
        with ThreadPoolExecutor(max_workers=1) as pool:
            blocked = pool.submit(ingestion_signals.evaluate_bounded, stalled_consumer, (), {}, 0.15)
            with self.assertRaises(ingestion_signals.SubscriberDeadline):
                blocked.result(timeout=2)
        self.assertLess(monotonic() - start, 2)

    def test_regrant_after_revocation_cannot_resurrect_previous_review(self):
        self.transcript()
        source = self.source()
        offer = ingestion_signals.assess(self.work, {"source": source, "moment": "pause"})["selection"]
        source_evidence.revoke(self.work, source["source_id"])
        source_evidence.revoke(self.work, source["source_id"], restore=True)
        ingestion_signals.assess(self.work, {"source": source})
        self.assertIsNone(stakeholder_signals.recall(self.work, offer["evidence"]))
        self.assertNotIn(offer["evidence"]["grant"], source_evidence.state(self.work)[1]["grants"])
