"""Exercise the strategy contract through the private workspace commands."""

import json
import re
import subprocess
import sys
import unittest

import test_pm
from test_pm import pm, records


class StrategyFrameworkTests(unittest.TestCase):
    setUp = test_pm.HubTests.setUp
    destination = "workspace/strategies/orchid.md"

    def strategy_status(self):
        result = subprocess.run(
            [sys.executable, "-B", str(self.root / "tools/pm.py"), "strategy", self.destination],
            cwd=self.work, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def strategy_draft(self):
        path = records.create(self.root, "strategy", self.destination, title="Orchid invitations")
        answers = iter((
            "Teams need to activate new administrators faster [S1].",
            "Gap: The PM has yet to approve an activation target.",
            "New Orchid team administrators [S1].",
            "Administrators lose track of pending invitations [S1].",
            "Failed invitations prevent teams from activating.",
            "Improve exports after the invitation pilot.",
            "Administrators tracked pending invites in a spreadsheet [S1].",
            "Gap: The interview did not cover successful invitations.",
            "Review the pilot in May after invitations close. Delaying keeps new administrators blocked.",
            "Show pending invitations in the team console.",
            "Administrators resend more invitations before they expire.",
            "Share of invited administrators activated within seven days.",
            "Pilot the pending list with five administrators and measure activation against the baseline.",
            "Gap: The pilot has yet to run.",
            "open", "Will administrators use the list to resend invitations?",
            "open", "Can administrators find the pending list?",
            "open", "Can expired links be regenerated safely?",
            "open", "Would the pilot meet the support budget?",
            "none", "open",
            "proposed", "Pilot a pending invitation list", "pending", "New Orchid teams",
            "Reduce lost invitations during activation", "pending",
            "S1", "Pat, Orchid administrator interview", "undated", "2024-01-03",
            "Review the pilot with Product.",
        ))
        path.write_text(re.sub(r"{{[^{}]+}}", lambda _: next(answers), path.read_text()))
        self.assertEqual(list(answers), [])
        return path

    def test_readiness_uses_saved_record_and_preserves_the_file(self):
        path = self.strategy_draft()
        original = path.read_text()
        self.assertEqual(self.strategy_status()["step"], "ready-for-pm-review")
        self.assertEqual(path.read_text(), original)
        path.write_text(original.replace("Viability | Product", "Viability | Finance"))
        status = self.strategy_status()
        self.assertEqual(status["step"], "Risks and tradeoffs")
        self.assertIn("Viability lead must be Product", status["issues"])

    def test_planned_experiment_cannot_clear_value_risk(self):
        path = self.strategy_draft()
        original = path.read_text()
        validated = original.replace("Value validation: open", "Value validation: validated")
        path.write_text(validated)
        issues = pm.check(self.root)
        self.assertTrue(any("validated value needs a sourced test result" in issue for issue in issues), issues)
        self.assertTrue(any("validated value needs Product's sourced value assessment" in issue
                            for issue in issues), issues)

        assessed = validated.replace("open | Will administrators use the list to resend invitations?",
                                     "assessed | Product supported the approach after the pilot [S1].")
        path.write_text(assessed.replace("Gap: The pilot has yet to run.",
                                         "Four of five pilot administrators activated within seven days [S1]."))
        self.assertEqual(pm.check(self.root), [])
        self.assertEqual(self.strategy_status()["step"], "ready-for-pm-review")

    def test_existing_strategy_without_contract_remains_supported(self):
        path = self.strategy_draft()
        original = path.read_text()
        path.write_text(original.replace("<!-- pm-contract: strategy-v2 -->\n", ""))
        self.assertEqual(pm.check(self.root), [])
        self.assertEqual(self.strategy_status()["step"], "legacy-record")

    def test_hub_action_uses_the_same_strategy_check(self):
        self.strategy_draft()
        command = [sys.executable, "-B", str(self.root / "tools/pm.py"), "action", "strategy", "brief", "check"]
        result = subprocess.run([*command, self.destination], cwd=self.work, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout), self.strategy_status())
        missing = subprocess.run([*command, "workspace/strategies/missing.md"],
                                 cwd=self.work, capture_output=True, text=True)
        self.assertEqual(missing.returncode, 1, missing.stdout + missing.stderr)
        self.assertIn("Select an existing record", missing.stdout)
