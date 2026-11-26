"""Exercise a draft and its next turn through both registered clients in a real private Git workspace."""

import json
import unittest

import test_conversation


class ProfileSessionHookTests(unittest.TestCase):
    setUp = test_conversation.ConversationTests.setUp
    cli = test_conversation.ConversationTests.cli
    turn = test_conversation.ConversationTests.turn
    prompt = test_conversation.ConversationTests.prompt

    def test_one_person_preview_approval_and_followup_without_cross_session_reuse(self):
        choice = self.cli("onboarding", "status")["stakeholder_profiles"]
        self.cli("onboarding", "profiles", payload={"revision": choice["revision"], "choice": "skip", "pm_reply": "Skip."})
        sentence = "For Billing reviews, Ren asked for the unowned escalations first."
        change = {"id": "ren-vale", "name": "Ren Vale", "role": "Service lead", "kind": "reported",
                  "topic": "communication", "subject": "product/billing", "scope": "Billing reviews",
                  "wording": sentence, "source": "PM account of the Billing review",
                  "excerpt": "Can we start with the escalations that still need an owner?"}
        path = self.work / "context/stakeholders/profiles/ren-vale.json"
        for client in ("Codex", "Claude"):
            route, _ = self.prompt(client, client, "Can we make just one profile for Ren Vale?")
            self.assertEqual(route["stakeholder_profiles"]["status"], "resolved" if path.exists() else "setup")
            self.assertEqual(self.cli("onboarding", "status")["stakeholder_profiles"]["status"], "skipped")
            if not path.exists():
                review = self.cli("stakeholder-profile", "preview", payload=change)
                self.assertFalse(path.exists())
                self.cli("stakeholder-profile", "accept", payload={"review": review, "approved_wording": "Changed."},
                         error="exact reviewed wording")
                self.assertFalse(path.exists())
                self.cli("stakeholder-profile", "accept", payload={"review": review, "approved_wording": sentence})
            first, _ = self.prompt(client, client, "Draft a Billing update for Ren Vale.")
            self.assertIn(sentence, json.dumps(first["stakeholder_profiles"]))
            self.turn(client, "Stop", client, last_assistant_message="Here is your draft.")
            following, _ = self.prompt(client, client, "Make it shorter.")
            self.assertIn(sentence, json.dumps(following["stakeholder_profiles"]))
            fresh, _ = self.prompt(client, "different-" + client, "Make it shorter.")
            self.assertNotIn("stakeholder_profiles", fresh)
            denied, _ = self.prompt(client, client, "Make it shorter without using a stakeholder profile.")
            self.assertNotIn("stakeholder_profiles", denied)
            next_turn, _ = self.prompt(client, client, "Make it shorter.")
            self.assertNotIn("stakeholder_profiles", next_turn)
