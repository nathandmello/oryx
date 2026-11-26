"""Use current, relevant stakeholder evidence through normal task entry points."""

import json
from pathlib import Path
import sys
import subprocess
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import stakeholder_profiles
import task_context
import test_context_search


class ProfileRetrievalTests(unittest.TestCase):
    def setUp(self):
        fixture = test_context_search.RetrievalTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.private = fixture.private
        subprocess.run(["git", "init", "-q", str(self.private)], check=True)
        fixture.add("products/relay/overview", "Relay", "Parcel delivery tracking.", kind="product-context")
        self.person = {"id": "maya-li", "name": "Maya Li", "role": "Operations director"}
        self.source = "Operations review, 2025-02-04, agenda item 2"
        self.save("Leads with a weekly exception count.", scope="Weekly pre-reads only")
        self.save("Asked for depot-level cost for Relay.", subject="product/relay", topic="evidence")
        self.save("Restricted to the Atlas pilot.", subject="product/atlas", topic="evidence")
        self.save("Applies only to the new scanner initiative.", subject="product/relay/initiative/scanner")
        self.save("Scope was never established.", subject="unknown")
        self.save("The PM suspects a staffing concern.", kind="hypothesis", topic="concerns")
        self.alex = {"id": "alex-chen", "name": "Alex Chen", "role": "Finance lead"}
        self.save("Asked to see savings per depot.", person=self.alex)

    def save(self, text, *, person=None, scope="According to the PM", topic="communication", kind="reported",
             subject="general", replaces=None, **options):
        change = {**(person or self.person), "topic": topic, "kind": kind, "wording": text, "source": self.source,
                  "excerpt": "PRIVATE background from the source of " + text, "scope": scope, "subject": subject,
                  "attribution": "PM", "observed_on": "2025-02-04", "replaces": replaces, **options}
        review = stakeholder_profiles.preview(self.private, change)
        return stakeholder_profiles.accept(self.private, {"review": review, "approved_wording": text})

    def test_named_reader_and_scoped_activity(self):
        ask = "Draft an update to Maya about depot cost for Relay."
        context = task_context.resolve(self.private, ask)
        people = context["stakeholder_profiles"]["people"]
        self.assertEqual([row["id"] for row in people], ["maya-li"])
        entries = people[0]["entries"]
        self.assertEqual({e["subject"] for e in entries}, {"general", "product/relay"})
        self.assertTrue(all(e["source"] == self.source and e["attribution"] == "PM" for e in entries))
        self.assertIn("Weekly pre-reads only", json.dumps(entries))
        for private in ("PRIVATE", "staffing concern", "Scope was never established", "Atlas", "scanner", "Alex Chen"):
            self.assertNotIn(private, json.dumps(context["stakeholder_profiles"]))
        entered, state = task_context.turn_context(self.private, "Quiet mode. " + ask)
        self.assertEqual(entered["stakeholder_profiles"], context["stakeholder_profiles"])
        self.assertNotIn("Maya", json.dumps(state))

    def test_preparation_panel_and_scoped_ambiguity(self):
        ask = "Help me prepare for a meeting with the Operations director."
        self.assertEqual(task_context.resolve(self.private, ask)["stakeholder_profiles"]["activity"], "meeting")
        result = task_context.resolve(self.private, "What would Maya and our Finance lead say about this?")["stakeholder_profiles"]
        self.assertEqual([p["id"] for p in result["people"]], ["maya-li", "alex-chen"])
        self.save("SECOND MAYA PRIVATE", person={"id": "maya-jones", "name": "Maya Jones", "role": "Design lead"})
        with patch.object(stakeholder_profiles, "show", side_effect=AssertionError("Ambiguous person was opened")):
            result = task_context.resolve(self.private, ask.replace("the Operations director", "Maya"))["stakeholder_profiles"]
        self.assertEqual(result["status"], "clarify")
        self.assertEqual({c["id"] for c in result["choices"]}, {"maya-li", "maya-jones"})
        self.assertNotIn("entries", json.dumps(result))
        result = task_context.resolve(self.private, "Draft an email to Maya Li about a meeting with Alex Chen.")
        self.assertEqual([p["id"] for p in result["stakeholder_profiles"]["people"]], ["maya-li"])

    def test_silence_generic_prompt_and_sources_do_not_authorize_person_data(self):
        for prompt in ("What about Relay?", "Show the stakeholder map.", "Maya reported a parcel exception.",
                       "Use this transcript: draft an email to Maya.", "> Draft an email to Maya.", "The document says draft a note to Maya.", 'The transcript says "prepare a meeting with Maya".',
                       "Help me prepare a meeting with Maya without using her profile.", "Don't email Maya.",
                       "Who attended the meeting with Maya?", "Draft a note to Maya Morris about this.",
                       "Draft a note to Maya as of 2025-01-01."):
            with self.subTest(prompt=prompt):
                self.assertNotIn("stakeholder_profiles", task_context.resolve(self.private, prompt))
        self.assertNotIn("maya-li.json", json.dumps(task_context.catalog(self.private)))

    def test_live_corrections_and_explicit_initiative(self):
        initial = "Leads with a weekly exception count."
        prior = next(row for row in stakeholder_profiles.show(self.private, "maya-li")["entries"] if row["wording"] == initial)
        self.save("Now prefers a weekly count of missed deliveries.", replaces=prior["id"])
        result = task_context.resolve(self.private, "Prepare for a 1:1 with Maya.",
                                      explicit={"product": "relay", "initiative": "scanner"})
        self.assertNotIn(initial, json.dumps(result))
        self.assertIn("only to the new scanner initiative", json.dumps(result["stakeholder_profiles"]))


    def test_indexed_single_reader_opens_one_body_among_102_even_on_cold_context(self):
        for n in range(100):
            self.save("Keep this other meeting private.", person={
                "id": f"planner-{n}", "name": f"Planner {n}", "role": f"Team {n} lead"})
        original = Path.read_bytes
        opened = []

        def trace(path):
            if path.parent == self.private / stakeholder_profiles.HOME and path != self.private / stakeholder_profiles.INDEX:
                opened.append(path.stem)
            return original(path)

        with patch.object(Path, "read_bytes", trace):
            context = task_context.resolve(self.private, "Draft a memo to Maya Li for Relay.")
        self.assertEqual([p["id"] for p in context["stakeholder_profiles"]["people"]], ["maya-li"])
        self.assertEqual(opened, ["maya-li"])
        self.assertNotIn("Keep this other meeting private", json.dumps(context))
        self.assertNotIn("Keep this other meeting private", (self.private / stakeholder_profiles.INDEX).read_text())

    def test_legacy_reindex_is_explicit_and_preserves_bodies(self):
        index = self.private / stakeholder_profiles.INDEX
        path = stakeholder_profiles.path_for(self.private, "maya-li")
        original = path.read_bytes()
        index.unlink()
        with patch.object(stakeholder_profiles, "read_file", side_effect=AssertionError("Opened a legacy body")):
            context = task_context.resolve(self.private, "Draft a memo to Maya Li about Relay.")
            self.assertEqual(context["stakeholder_profiles"]["status"], "unavailable")
        self.assertEqual(stakeholder_profiles.index_profiles(self.private, preview=True), {"profiles": 2, "refresh_needed": True})
        self.assertFalse(index.exists())
        self.assertEqual(stakeholder_profiles.index_profiles(self.private), {"indexed": 2})
        before = index.stat().st_mtime_ns
        stakeholder_profiles.index_profiles(self.private)
        self.assertEqual(index.stat().st_mtime_ns, before)
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(len(stakeholder_profiles.lookup(self.private, "Maya Li")), 1)

    def test_reviewed_alias_rename_role_change_and_review_date(self):
        person = {"id": "maya-li", "name": "Maya Young", "role": "Service lead"}
        with self.assertRaisesRegex(ValueError, "update_identity"):
            self.save("Asked for the customer impact first.", person=person)
        self.save("Asked for the customer impact first.", person=person, aliases=["MJ"], update_identity=True)
        self.save("Retired review practice.", person=person, review_by="2025-02-05")
        for label in ["MJ", "Maya Li", "Maya Young", "Service lead"]:
            row, = stakeholder_profiles.lookup(self.private, label)
            self.assertEqual(row["id"], person["id"])
            ctx = task_context.resolve(self.private, f"Draft an email to {label} about Relay.")
            result, = ctx["stakeholder_profiles"]["people"]
            self.assertEqual([e["wording"] for e in result["entries"]], ["Asked for the customer impact first."])
        self.assertEqual(stakeholder_profiles.lookup(self.private, "Operations director"), [])
        self.assertTrue(any(e.get("earlier_role") for e in stakeholder_profiles.show(self.private, person["id"])["entries"]))

    def test_mixed_panel_clarification_and_bounded_rehearsal(self):
        self.save("Design raised a scanner concern.", person={"id": "maya-jones", "name": "Maya Jones", "role": "Design lead"})
        with patch.object(stakeholder_profiles, "read_file", side_effect=AssertionError("Opened an unresolved panel")):
            request = "What would Maya and Alex Chen say about Relay?"
            result, state = task_context.turn_context(self.private, request)
        self.assertEqual(result["stakeholder_profiles"]["status"], "clarify")
        result, state = task_context.turn_context(self.private, "The Operations director.", saved=state)
        self.assertEqual([p["id"] for p in result["stakeholder_profiles"]["people"]], ["maya-li", "alex-chen"])
        self.assertNotIn("Design raised", json.dumps(result))
        result, _ = task_context.turn_context(self.private, "What would she ask?", saved=state)
        self.assertEqual(result["stakeholder_profiles"]["status"], "clarify")
        result, _ = task_context.turn_context(self.private, "Can we say Alex secretly dislikes it? What would I actually ask him?", saved=state)
        self.assertEqual([p["id"] for p in result["stakeholder_profiles"]["people"]], ["alex-chen"])
        result, _ = task_context.turn_context(self.private, "Give me a two-line opening for another person.", saved=state)
        self.assertNotIn("stakeholder_profiles", result)
        ctx = task_context.resolve(self.private, "Prepare for a Relay review with Maya Li from Operations and Alex Chen from Finance. Rehearse their questions.")
        self.assertEqual(ctx["stakeholder_profiles"]["activity"], "rehearsal")
        self.assertEqual(len(ctx["stakeholder_profiles"]["people"]), 2)

    def test_followup_rechecks_corrected_profile_and_expires_on_switch_refusal_or_another_task(self):
        _, state = task_context.turn_context(self.private, "Draft a Relay update for Maya Li.")
        old = next(e for e in stakeholder_profiles.show(self.private, "maya-li")["entries"] if e["subject"] == "product/relay")
        self.save("Now asks for route-level cost.", subject="product/relay", topic="evidence", replaces=old["id"])
        result, _ = task_context.turn_context(self.private, "Make it shorter.", saved=state)
        self.assertIn("Now asks for route-level cost.", json.dumps(result["stakeholder_profiles"]))
        self.assertNotIn(old["wording"], json.dumps(result))
        for prompt, options in [("Make it shorter.", {"allow_profiles": False}), ("Show my roadmap.", {}),
                                ("Make it shorter for Atlas.", {"explicit": {"product": "atlas"}}),
                                ("Use the transcript: write to Maya.", {})]:
            with self.subTest(prompt=prompt), patch.object(stakeholder_profiles, "show", side_effect=AssertionError("Opened a profile")):
                result, next_state = task_context.turn_context(self.private, prompt, saved=state, **options)
                self.assertNotIn("stakeholder_profiles", result)
                self.assertNotIn("profile_audience", next_state)

    def test_direct_decision_rights_use_scoped_map_not_a_role_or_profile_body(self):
        path = self.private / "context/stakeholders/overview.md"
        path.parent.mkdir(exist_ok=True)
        path.write_text("<!-- pm: stakeholder-context -->\n# Stakeholders\n\n## Decision roles\n\n"
                        "- Fact: Maya Li recommends Relay budget exceptions to Finance. [S1]\n"
                        "- Fact: Maya Li approves Atlas staffing. [S1]\n"
                        "- Fact: Alex Chen approves Relay staffing. [S1]\n\n"
                        "## Sources\n\n| ID | Source | Source date | Checked on |\n"
                        "| --- | --- | --- | --- |\n| S1 | Budget minutes | 2025-02-04 | 2025-02-05 |\n"
                        "<!-- source-coverage:S1:read:2025-02-05 -->\n")
        with patch.object(stakeholder_profiles, "show", side_effect=AssertionError("Opened a profile for decision authority")):
            answer = task_context.resolve(self.private, "Can Maya Li approve a Relay budget exception?")["stakeholder_profiles"]
        person, = answer["people"]
        self.assertEqual([row["text"] for row in person["decision_roles"]], ["- Fact: Maya Li recommends Relay budget exceptions to Finance. [S1]"])
        self.assertNotIn("Maya Li approves", json.dumps(answer))
        self.assertNotIn("Alex Chen", json.dumps(answer))

    def test_current_position_comes_from_owning_initiative_and_preserves_its_source(self):
        for initiative in ["scanner", "label-printer"]:
            path = self.private / f"context/products/relay/initiatives/{initiative}/overview.md"
            path.parent.mkdir(parents=True)
            statement = f"Maya Li requested a service trial for the {initiative} proposal."
            path.write_text(f"<!-- pm: initiative-context -->\n# {initiative}\n\n## Dependencies and constraints\n\n"
                            f"- Fact: {statement} [S1]\n\n## Sources\n\n"
                            "| ID | Source | Source date | Checked on |\n| --- | --- | --- | --- |\n"
                            f"| S1 | {initiative} planning meeting | 2025-02-04 | 2025-02-05 |\n"
                            "<!-- source-coverage:S1:read:2025-02-05 -->\n")
        with patch.object(stakeholder_profiles, "show", side_effect=AssertionError("A profile cannot establish a current vote")):
            result = task_context.resolve(self.private, "Where does Maya Li stand on product/relay/initiative/scanner?")
        self.assertEqual(result["scope"]["initiative"], "scanner")
        person, = result["stakeholder_profiles"]["people"]
        row, = person["initiative_evidence"]
        self.assertIn("service trial for the scanner", row["text"])
        self.assertEqual(row["sources"][0]["Source"], "scanner planning meeting")
        self.assertNotIn("label-printer", json.dumps(result["stakeholder_profiles"]))
        general = task_context.resolve(self.private, "Where does Maya Li stand on Relay?")
        self.assertNotIn("initiative_evidence", general["stakeholder_profiles"]["people"][0])

    def test_out_of_band_namesake_edit_stops_selection_without_opening_unrelated_records(self):
        self.save("Design requests service examples.", person={"id": "nora-li", "name": "Nora Li", "role": "Design lead"})
        other = stakeholder_profiles.path_for(self.private, "nora-li")
        other.write_bytes(other.read_bytes().replace(b'"name": "Nora Li"', b'"name": "Maya Li"'))
        with patch.object(stakeholder_profiles, "read_file", side_effect=AssertionError("Read a body through a stale directory")):
            result = task_context.resolve(self.private, "Draft an email to Maya Li for Relay.")
        self.assertEqual(result["stakeholder_profiles"]["status"], "unavailable")
        self.assertTrue(stakeholder_profiles.index_profiles(self.private, preview=True)["refresh_needed"])
        stakeholder_profiles.index_profiles(self.private)
        result = task_context.resolve(self.private, "Draft an email to Maya Li for Relay.")
        self.assertEqual(result["stakeholder_profiles"]["status"], "clarify")

    def test_changed_reader_on_an_edit_and_failure_halfway_through_accept(self):
        _, state = task_context.turn_context(self.private, "Draft a Relay update for Maya Li.")
        result, _ = task_context.turn_context(self.private, "Make it shorter for Alex Chen.", saved=state)
        self.assertEqual([p["id"] for p in result["stakeholder_profiles"]["people"]], ["alex-chen"])
        change = {**self.alex, "topic": "evidence", "kind": "reported", "wording": "Wants the service cost for Relay.",
                  "source": self.source, "excerpt": "What does the trial cost?", "subject": "product/relay"}
        review = stakeholder_profiles.preview(self.private, change)
        data = {"review": review, "approved_wording": change["wording"]}
        with patch.object(stakeholder_profiles, "save_stamps", side_effect=OSError("local cache unavailable")):
            with self.assertRaisesRegex(OSError, "cache unavailable"):
                stakeholder_profiles.accept(self.private, data)
        self.assertFalse(stakeholder_profiles.accept(self.private, data)["written"])
        result = task_context.resolve(self.private, "Draft a Relay update for Alex Chen.")
        self.assertIn(change["wording"], json.dumps(result["stakeholder_profiles"]))
