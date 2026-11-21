"""Check launch evidence and exceptions through the PM signing workflow."""

from datetime import date, timedelta
import json
import os
import unittest
from unittest.mock import patch

import test_opportunities


class ShipReadinessTests(unittest.TestCase):
    monitor = "regional-monitor"
    monitor_gap = "check:regional-monitor"
    task = "regional-canary"
    proof = "The EU on-call team received the canary alert."
    withdrawal = "The drill reached the wrong region."

    def setUp(self):
        self.hub = test_opportunities.InitiativeTests()
        self.addCleanup(self.hub.doCleanups)
        self.hub.setUp()
        self.checklist = self.hub.work / "workspace/initiatives/example/renewal/launch-checklist.json"
        self.tasks = self.checklist.with_name("tasks.json")
        self.delivery_on = (date.today() - timedelta(days=2)).isoformat()
        self.hub.submit(
            self.hub.setup_event(),
            {**self.hub.capture(), "observed_on": self.delivery_on},
            self.hub.decision(
                "expedite", on=self.delivery_on, delivery="https://example.com/delivery/42",
                owner="Incident PM", obligation="Restore renewal alerts", deadline=self.hub.today,
                scope="Renewal notices for the EU pilot", review_on=self.hub.today,
            ),
        )

    @staticmethod
    def edit(identifier, action="update", **fields):
        return {"id": identifier, "action": action, "fields": fields}

    def work_list(self, kind, operation="list", *args, value=None):
        return json.loads(self.hub.cli(kind, operation, "example", "renewal", *args, value=value))

    def change(self, kind, *edits, preview=False):
        options = ["--revision", self.work_list(kind)["revision"]]
        if preview:
            options.append("--preview")
        return self.work_list(kind, "apply", *options, value=edits)

    def verification(self, evidence, **fields):
        return {"evidence": evidence, "by": "On-call lead", "on": self.hub.today, **fields}

    def record_checks(self):
        self.change("task", self.edit(
            self.task, "add", title="Exercise the regional canary", owner="On-call lead",
            completion_criteria="The EU on-call team acknowledges the alert.",
            status="done", resolution=self.proof, source="EU canary report 42",
        ))
        self.change(
            "launch-checklist",
            self.edit("release-scope", "add", title="Confirm release scope", phase="upstream",
                      criterion="The launch owner confirms the pilot audience.", owner="Launch lead",
                      status="verified", verification=self.verification("The launch owner approved the EU pilot.")),
            self.edit(self.monitor, "add", title="Verify regional monitoring", phase="launch",
                      criterion="The launch owner has a tested alert path.", owner="On-call lead",
                      status="verified", tasks=[self.task], verification=self.verification(self.proof)),
            self.edit("support-handoff", "add", title="Confirm support handoff", phase="downstream",
                      criterion="Support acknowledges the handoff."),
        )

    def withdraw(self):
        self.change("task", self.edit(
            self.task, status="blocked", resolution=None, blocked_reason=self.withdrawal,
        ))

    def ship(self, **fields):
        return self.hub.decision("ship", review_on=self.hub.today, **fields)

    @staticmethod
    def readiness(proposal):
        return proposal["reviewed_transactions"][0]["readiness"]

    def current_initiative(self):
        return json.loads(self.hub.cli(
            "action", "initiative", "record", "show", "example", self.hub.i,
        ))["initiative"]

    def test_recompleted_task_with_same_text_requires_fresh_verification(self):
        self.record_checks()
        first = self.hub.preview(self.ship())
        self.assertEqual(self.readiness(first)["outstanding"], {})

        self.withdraw()
        checklist = self.work_list("launch-checklist")
        monitor = next(row for row in checklist["checkpoints"] if row["id"] == self.monitor)
        self.assertEqual(monitor["status"], "verified")
        self.assertEqual(monitor["verification"]["evidence"], self.proof)
        self.assertIn(self.withdrawal, " ".join(monitor["review_issues"]))
        self.assertEqual(checklist["launch_readiness"], "pending")

        self.change("task", self.edit(self.task, status="done", resolution=self.proof, blocked_reason=None))
        replay = self.hub.preview(self.ship())
        replay_readiness = self.readiness(replay)
        original_task = self.readiness(first)["linked_tasks"][self.task]["current"]
        current_task = replay_readiness["linked_tasks"][self.task]
        self.assertEqual(current_task["current"], original_task)
        self.assertEqual([entry["state"]["status"] for entry in current_task["history"]],
                         ["done", "blocked", "done"])
        self.assertIn(self.monitor_gap, replay_readiness["outstanding"])
        self.assertNotEqual(replay_readiness["revision"], self.readiness(first)["revision"])
        self.hub.apply(first, error="proposal is stale")
        self.hub.apply(replay, error=self.monitor_gap)
        self.assertEqual(self.current_initiative()["phase"], "delivery")

        self.change("launch-checklist", self.edit(
            self.monitor, verification=self.verification("Regional canary report 43 confirms the EU alert receipt."),
        ))
        refreshed = self.hub.preview(self.ship())
        self.assertEqual(self.readiness(refreshed)["outstanding"], {})
        self.hub.apply(refreshed)
        self.assertEqual(self.current_initiative()["phase"], "shipped")

    def test_scoped_exception_preserves_signed_evidence_after_live_edits(self):
        self.record_checks()
        self.withdraw()
        reason = {"reason": "The incident commander approved a one-account pilot with manual monitoring.",
                  "authority": "Incident commander, approval 117"}
        self.hub.preview(self.ship(exceptions={"check:support-handoff": reason}),
                         error="current outstanding launch risks")
        accepted = self.hub.preview(self.ship(exceptions={self.monitor_gap: reason}))
        self.assertIn(self.withdrawal, " ".join(self.readiness(accepted)["outstanding"][self.monitor_gap]))
        self.hub.apply(accepted)
        signed = self.hub.ledger.read_bytes()

        checklist = self.change("launch-checklist", self.edit(
            self.monitor, verification=self.verification("Support confirmed the independent alert feed.", basis_tasks=[]),
        ))
        self.assertEqual(checklist["launch_readiness"], "ready for launch decision")
        monitor = next(row for row in checklist["checkpoints"] if row["id"] == self.monitor)
        self.assertEqual(monitor["task_status"], {self.task: "blocked"})
        self.assertEqual(monitor["review_issues"], [])

        initiative = self.current_initiative()
        self.assertEqual(initiative["phase"], "shipped")
        self.assertEqual(initiative["decisions"][-1], accepted["reviewed_transactions"][0])
        self.assertEqual(initiative["decisions"][-1]["exceptions"], {self.monitor_gap: reason})
        self.assertEqual(self.hub.ledger.read_bytes(), signed)

    def test_unrelated_edits_and_draft_previews_preserve_ship_approval(self):
        self.record_checks()
        files = (self.hub.ledger, self.tasks, self.checklist)
        originals = [path.read_bytes() for path in files]
        guided = json.loads(self.hub.cli("action", "delivery", "launch", "review", "example", "renewal"))
        self.assertEqual(guided["effect"], "guided")
        self.assertEqual(guided["guide"], ".agents/skills/manage-initiative-work/SKILL.md")
        self.assertEqual(guided["arguments"], ["example", "renewal"])

        original = self.hub.preview(self.ship())
        reviewed_on = self.readiness(original)["reviewed_on"]
        self.change("task", self.edit(
            self.task, source="New canary report", resolution="The test alert reached the escalation lead.",
        ), preview=True)
        self.change("launch-checklist", self.edit(
            self.monitor, status="blocked", blocked_reason=self.withdrawal, verification=None,
        ), preview=True)
        self.assertEqual([path.read_bytes() for path in files], originals)

        self.change("launch-checklist", self.edit("support-handoff", title="Confirm EU support handoff"))
        self.change("task", self.edit(self.task, due_on=self.hub.today, priority="high"), self.edit(
            "support-demo", "add", title="Schedule the support demo",
            completion_criteria="The support lead accepts the invitation.",
        ))
        with patch.dict(os.environ, self.hub.env):
            refreshed, *_ = test_opportunities.pm.initiative_store.prepare(
                self.hub.root, "example", [self.ship()], review_dates={0: reviewed_on},
            )
        self.assertEqual(refreshed, original)
        self.hub.apply(original)
        self.assertEqual(self.current_initiative()["phase"], "shipped")

    def test_missing_checklist_is_a_visible_exception_without_creating_files(self):
        original = self.hub.ledger.read_bytes()
        proposal = self.hub.preview(self.ship())
        self.assertEqual(set(self.readiness(proposal)["outstanding"]), {"missing:checklist"})
        self.hub.apply(proposal, error="missing:checklist")
        self.assertEqual(self.hub.ledger.read_bytes(), original)
        self.assertFalse(self.tasks.exists())
        self.assertFalse(self.checklist.exists())

        reason = {"reason": "Incident command recorded the rollback test in the restoration log.",
                  "authority": "Incident commander, restoration log 31"}
        approved = self.hub.preview(self.ship(exceptions={"missing:checklist": reason}))
        self.hub.apply(approved)
        self.assertEqual(self.current_initiative()["decisions"][-1], approved["reviewed_transactions"][0])
        self.assertFalse(self.checklist.exists())

    def test_attestation_after_effective_ship_date_remains_outstanding(self):
        self.record_checks()
        prior_date = self.hub.decision("ship", on=self.delivery_on, review_on=self.hub.today)
        proposal = self.hub.preview(prior_date)
        outstanding = self.readiness(proposal)["outstanding"]
        self.assertEqual(set(outstanding), {"check:release-scope", self.monitor_gap})
        self.assertIn("after the effective ship date", " ".join(outstanding[self.monitor_gap]))
        self.hub.apply(proposal, error=self.monitor_gap)

    def test_legacy_verification_is_visible_and_keeps_preexisting_evidence(self):
        self.record_checks()
        for path in (self.tasks, self.checklist):
            original = json.loads(path.read_text(encoding="utf-8"))
            original["version"] = 1
            del original["history"]
            path.write_text(json.dumps(original), encoding="utf-8")
        legacy = self.checklist.read_bytes()

        proposal = self.hub.preview(self.ship())
        self.assertEqual(set(self.readiness(proposal)["outstanding"]), {self.monitor_gap})
        self.hub.apply(proposal, error=self.monitor_gap)
        self.assertEqual(self.checklist.read_bytes(), legacy)

        replacement = "A new alert reached the regional escalation lead."
        self.change("launch-checklist", self.edit(self.monitor, verification=self.verification(replacement)))
        refreshed = self.readiness(self.hub.preview(self.ship()))
        self.assertEqual(refreshed["outstanding"], {})
        saved = refreshed["checkpoints"][self.monitor]
        self.assertEqual(saved["current"]["verification"]["evidence"], replacement)
        self.assertEqual(saved["history"][0]["state"]["verification"]["evidence"], self.proof)
