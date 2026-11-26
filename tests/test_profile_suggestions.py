"""Check that private suggestion preferences apply before any unsolicited offer."""

import json
import subprocess
import sys
import unittest
from unittest.mock import patch

import test_pm
from onboarding_fixtures import reviewed_setup
import company_source
import overrides
import pm


class ProfileSuggestionPreferenceTests(unittest.TestCase):
    setUp = reviewed_setup

    def edit(self, mode, *scope):
        result = subprocess.run([sys.executable, "tools/pm.py", "override", "profile-suggestions", mode, *scope],
                                cwd=self.root, capture_output=True, text=True, check=True)
        return json.loads(result.stdout)

    def test_muting_a_source_and_every_source_with_later_explicit_exceptions(self):
        self.assertTrue(overrides.profile_suggestions_allowed(self.work, "transcript"))
        self.assertEqual(self.edit("off", "--source", "transcript")["rule_id"],
                         "stakeholder-profile-suggestions-transcript")
        self.assertFalse(overrides.profile_suggestions_allowed(self.work, "transcript"))
        self.assertTrue(overrides.profile_suggestions_allowed(self.work, "chat"))
        self.edit("off")
        self.edit("on", "--source", "wiki")
        self.assertTrue(overrides.profile_suggestions_allowed(self.work, "wiki"))
        self.assertFalse(overrides.profile_suggestions_allowed(self.work, "onboarding"))
        self.edit("off")
        self.assertFalse(overrides.profile_suggestions_allowed(self.work, "wiki"))
        self.edit("on")
        self.assertTrue(overrides.profile_suggestions_allowed(self.work, "transcript"))

    def test_reinstates_inherited_behavior_and_preserves_unrelated_ids(self):
        parse = pm.build_parser().parse_args
        overrides.run(self.root, parse(["override", "set", overrides.PROFILE_TARGET, "--target", "meeting-style",
                                        "--scope", "Meeting notes", "--behavior", "Use prose."]))
        company_source.install(self.work, json.dumps({
            "id": "product-ops", "revision": 1, "format": 1,
            "rules": {"team-note-policy": {"target": overrides.PROFILE_TARGET, "scope": "Source: chat",
                                           "behavior": overrides.PROFILE_OFF}}}))
        self.assertFalse(overrides.profile_suggestions_allowed(self.work, "chat"))
        alias = self.edit("on")["rule_id"]
        self.assertNotEqual(alias, overrides.PROFILE_TARGET)
        self.assertTrue(overrides.profile_suggestions_allowed(self.work, "chat"))
        self.assertEqual(self.edit("inherit")["removed"], alias)
        self.assertFalse(overrides.profile_suggestions_allowed(self.work, "chat"))
        self.assertTrue(overrides.profile_suggestions_allowed(self.work, "email"))
        self.assertEqual(overrides.read(self.work)[1]["rules"][overrides.PROFILE_TARGET]["target"], "meeting-style")

    def test_private_source_and_reason_never_go_in_the_builtin_public_report(self):
        parse = pm.build_parser().parse_args
        args = parse(["override", "profile-suggestions", "off", "--source", "confidential-team-wiki"])
        with patch.object(overrides, "gh") as api:
            saved = overrides.run(self.root, args)
            api.assert_not_called()
        self.assertFalse(saved["reporting"])
        overrides.run(self.root, parse(["override", "reporting", "on"]))
        with patch.object(overrides, "gh", side_effect=ValueError("offline")):
            self.assertIn("report_pending", overrides.run(self.root, args))
        self.assertFalse(overrides.profile_suggestions_allowed(self.work, "confidential-team-wiki"))
        queued = overrides.read(self.work)[1]["pending"][0]
        self.assertNotIn("confidential", queued["title"] + queued["body"])
        self.assertFalse(queued["reviewed"])
        identity = json.dumps({"id": overrides.REPO_ID, "full_name": overrides.FEEDBACK_REPOS[-1],
                               "owner": overrides.REPO_OWNER})
        receipt = "https://github.com/" + overrides.FEEDBACK_REPOS[-1] + "/issues/1"
        with patch.object(overrides, "gh", side_effect=[identity, "", receipt]) as api:
            self.assertEqual(overrides.run(self.root, parse(["override", "sync"]))["urls"], [receipt])
            self.assertNotIn("confidential", repr(api.call_args_list))
        with self.assertRaisesRegex(ValueError, "Approve the exact public"):
            overrides.run(self.root, parse(["override", "report", saved["rule_id"], "--title", "Changed timing",
                                            "--body", "Explain the general concern."]))

    def test_unreadable_rule_store_withholds_optional_offer(self):
        self.edit("off")
        (self.work / overrides.FILE).write_text("Unfinished edit.")
        self.assertFalse(overrides.profile_suggestions_allowed(self.work, "chat"))
