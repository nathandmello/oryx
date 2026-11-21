"""Verify upgrade choices, recovery and strict structure after alignment."""

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
from unittest.mock import patch
import zipfile

import test_pm
from onboarding_fixtures import reviewed_studio
from test_pm import pm, records, workspace
import storage
import upgrades


PUBLISHED = "1cc646a048d7aa0ac69ac2f3c2e08ed0c0bf078d"
SECTION_RELEASE = "433ebd28749e6c3ec4fedf0bd64e81a13049ac43"
PLAN = "workspace/initiatives/renewals/old-working-plan.md"


class StructureUpdateTests(unittest.TestCase):
    setUp = test_pm.HubTests.setUp
    run_hook = test_pm.HubTests.run_hook
    context_capture = test_pm.HubTests.context_capture

    def old_workspace(self):
        ledger, state = upgrades.read_state(self.work)
        state.pop(upgrades.STRUCTURE_RULE)
        storage.replace_text(self.work / upgrades.LEDGER, ledger, upgrades.encode(state))

    def plan(self, private):
        path = private / PLAN
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"# Renewal tracker\r\n\r\nDiscuss the support handoff.\r\n")
        return path

    def check_cli(self, root, *args, data=None, success=True):
        proc = subprocess.run([sys.executable, "-B", str(root / "tools/pm.py"), *args], cwd=root,
                              input=json.dumps(data), text=True, capture_output=True, timeout=50)
        self.assertEqual(proc.returncode == 0, success, proc.stdout + proc.stderr)
        return proc.stdout

    def git(self, root, *args):
        return subprocess.run(["git", "-C", str(root), "-c", "user.name=Fixture PM",
                               "-c", "user.email=pm@example.test", "-c", "commit.gpgsign=false", *args],
                              text=True, capture_output=True, check=True, timeout=30).stdout.strip()

    def test_preview_handoff_and_opt_in_conversion(self):
        self.old_workspace()
        plan = self.plan(self.work)
        original = plan.read_bytes()
        fingerprint = hashlib.sha256(original).hexdigest()
        ledger = self.work / upgrades.LEDGER
        before = ledger.read_bytes()
        status = json.loads(self.check_cli(self.root, "align", "--status"))
        self.assertTrue(status["structure_review"]["needs_scan"])
        self.assertEqual(status["structure_review"]["records"][0]["path"], PLAN)
        self.assertEqual(ledger.read_bytes(), before)
        self.assertEqual(pm.check(self.root), [])
        start = self.run_hook(json.dumps({"hook_event_name": "SessionStart", "cwd": str(self.root)}))
        guidance = json.loads(start.stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("1 existing record(s)", guidance)
        self.assertIn("review-hub-upgrade/SKILL.md", guidance)
        self.assertIn("explicitly approves", guidance)
        self.assertEqual(plan.read_bytes(), original)
        backup = self.work / ".git/pm-hub-recovery" / upgrades.RULE / fingerprint / PLAN
        self.assertEqual(backup.read_bytes(), original)

        inventoried = ledger.read_bytes()
        status = json.loads(self.check_cli(self.root, "align"))
        self.assertFalse(status["structure_review"]["inventoried_now"])
        self.assertEqual(ledger.read_bytes(), inventoried)
        stop = self.run_hook(json.dumps({"hook_event_name": "Stop", "cwd": str(self.root)}))
        self.assertEqual(json.loads(stop.stdout), {})

        updated = ("# Renewal tracker\n\n## Scope\n\nRenewal handoff.\n\n## Evidence\n\n"
                   "Discuss the support handoff.\n\n## Next action\n\nConfirm the handoff owner.\n")
        change = {"id": "renewal-format", "reason": "Make the handoff scope and next action easy to find.",
                  "changes": [{"path": PLAN, "before": fingerprint, "text": updated}]}
        self.check_cli(self.root, "align", "--preview-plan", data=change)
        self.assertEqual(plan.read_bytes(), original)
        self.check_cli(self.root, "align", "--apply-plan", data=change)
        self.assertEqual(plan.read_text(), updated)
        self.assertEqual(pm.alignment(self.root)["structure_review"]["records"], [])
        self.assertEqual(pm.check(self.root), [])

    def test_interrupted_inventory_recovers_and_new_artifacts_are_checked(self):
        self.old_workspace()
        plan = self.plan(self.work)
        before = plan.read_bytes()
        ledger = self.work / upgrades.LEDGER
        replace = storage.replace_text

        def interrupted(target, original, candidate, **kwargs):
            if target == ledger and upgrades.STRUCTURE_RULE in candidate:
                raise OSError("interrupted audit")
            return replace(target, original, candidate, **kwargs)

        with patch.object(storage, "replace_text", side_effect=interrupted):
            with self.assertRaisesRegex(OSError, "interrupted audit"):
                pm.alignment(self.root, prepare=True)
        self.assertEqual(plan.read_bytes(), before)
        self.assertTrue(pm.alignment(self.root)["structure_review"]["needs_scan"])
        result = pm.alignment(self.root, prepare=True)["structure_review"]
        self.assertEqual((self.work / result["backups"][PLAN]).read_bytes(), before)

        created = plan.with_name("new-plan.md")
        created.write_text("# New plan\n")
        self.assertEqual(len(pm.check(self.root)), 1)
        self.assertIn("new-plan.md", pm.check(self.root)[0])
        created.unlink()
        plan.write_text("# Edited older plan\n")
        self.assertIn(PLAN, pm.check(self.root)[0])

    def test_capture_preserves_the_users_choice_on_older_brief(self):
        reviewed_studio(self.root, self.work)
        self.old_workspace()
        company = records.create(self.root, "company-context", "context/company/overview.md")
        text = company.read_text().replace("## Sources", "## Historical evidence\n\nPending source review.\n\n## Sources")
        company.write_text(text)
        pm.alignment(self.root, prepare=True)
        data = {"sources": [], "entries": [{"scope": "company", "topic": "constraints",
                                            "question": "Who owns the policy?"}]}
        result = self.context_capture(data, "--write", "context/company/overview.md")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("approve a conversion", result.stdout)
        self.assertEqual(company.read_text(), text)

    def test_company_capture_preserves_an_earlier_portfolio_section_position(self):
        reviewed_studio(self.root, self.work)
        path = "context/company/overview.md"
        company = records.create(self.root, "company-context", path)
        text = company.read_text()
        blocks = {name: (start, end) for name, start, _, end in records.section_blocks(text)}
        start, end = blocks["Product portfolio"]
        section = f"## Product portfolio\n\n{records.CONTEXT_LEAD}\nConsult when comparing offerings.\n\n"
        section += "- Unknown: Which products work together?\n\n"
        text = (text[:start] + text[end:]).replace("## Context controls", section + "## Context controls")
        company.write_text(text)
        payload = {"sources": [], "entries": [{"scope": "company", "topic": "portfolio",
                                                "question": "Who uses both offerings?"}]}
        result = self.context_capture(payload, "--write", path)
        self.assertEqual(result.returncode, 0, result.stdout)
        revised = company.read_text()
        self.assertLess(revised.index("## Review and approvals"), revised.index("## Product portfolio"))
        self.assertIn("Who uses both offerings?", records.section(revised, "Product portfolio"))

    def test_empty_format_two_audit_still_offers_update_handoff_after_cli_alignment(self):
        self.old_workspace()
        result = json.loads(self.check_cli(self.root, "align"))
        self.assertEqual(result["structure_review"]["records"], [])
        start = self.run_hook(json.dumps({"hook_event_name": "SessionStart", "cwd": str(self.root)}))
        notice = json.loads(start.stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("Artifact audit found 0", notice)
        self.assertIn("Explain the benefits", notice)

    def interrupt_published_filing(self, consumer, path):
        original = path.read_bytes()
        updated = path.read_text() + "\nInvite the billing owner to the review.\n"
        change = {"id": "historical-filing", "reason": "Clarify who needs to attend.",
                  "changes": [{"path": PLAN, "before": hashlib.sha256(original).hexdigest(), "text": updated}]}
        script = """
import json, sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, 'tools')
import conversion, pm, storage
private = Path('private').resolve()
def interrupt(private, identifier, name, before, candidate):
    displaced = private / '.git' / 'pm-hub-recovery' / 'filing' / identifier / name
    displaced.parent.mkdir(parents=True, exist_ok=True)
    (private / name).replace(displaced)
    raise OSError('simulated interrupted swap')
with storage.writer_lock(private), patch.object(conversion, 'recoverable_swap', side_effect=interrupt):
    try:
        conversion.apply(private, json.load(sys.stdin), pm.filing_validator(private.parent), pm.LINK)
    except OSError as exc:
        assert str(exc) == 'simulated interrupted swap'
    else:
        raise AssertionError('expected a journaled, interrupted swap')
"""
        proc = subprocess.run([sys.executable, "-B", "-c", script], cwd=consumer, input=json.dumps(change),
                              text=True, capture_output=True, timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertFalse(path.exists())
        return original, updated.encode()

    def test_published_format_two_direct_and_wrapped_updates(self):
        # Build the candidate after the exact shared release in disposable local repositories.
        parent = self.root.parent
        publisher = parent / "publisher"
        self.git(parent, "clone", "--quiet", "--no-local", "--no-checkout", str(pm.ROOT), str(publisher))
        self.git(publisher, "checkout", "--quiet", "-B", "main", SECTION_RELEASE)
        self.git(publisher, "rm", "-qr", ".")
        for path in pm.inventory(pm.ROOT):
            if path.is_file():
                target = publisher / path.relative_to(pm.ROOT)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, target)
        next_version = workspace.release(pm.ROOT)["system_version"]
        self.git(publisher, "add", ".")
        self.git(publisher, "commit", "-qm", "Fixture format-two update")
        remote = parent / "release.git"
        self.git(parent, "clone", "--quiet", "--bare", str(publisher), str(remote))

        for method in ("direct", "wrapper", "interrupted", "section-lead"):
            with self.subTest(method=method):
                consumer = parent / method
                self.git(parent, "clone", "--quiet", str(remote), str(consumer))
                self.git(consumer, "reset", "--hard", SECTION_RELEASE if method == "section-lead" else PUBLISHED)
                self.check_cli(consumer, "init-workspace", "--owner", "Fixture PM")
                private = consumer / "private"
                self.assertEqual(workspace.settings(consumer)["workspace_format"], 2)
                file = private / "settings.json"
                data = json.loads(file.read_text())
                data["remotes"]["system"] = str(remote)
                file.write_text(json.dumps(data) + "\n")
                plan = self.plan(private)
                original = plan.read_bytes()
                expected = original
                if method == "interrupted":
                    original, expected = self.interrupt_published_filing(consumer, plan)
                if method == "section-lead":
                    company = private / "context/company/overview.md"
                    fact = "Use the company-approved order for partner handoffs."
                    data = {"sources": [{"reference": "Approved company handoff policy", "date": "undated",
                                         "checked_on": "2025-03-01", "coverage": "read", "text": fact}],
                            "entries": [{"scope": "company", "heading": "Partner handoff sequence",
                                         "lead": "Consult before preparing a partner handoff.", "source": 1,
                                         "location": "Policy, first paragraph", "quote": fact}]}
                    self.check_cli(consumer, "route-context", "--write", "context/company/overview.md", data=data)
                    company_before = company.read_bytes()
                offered = ("align", "--status")
                if method == "direct":
                    self.git(consumer, "pull", "--ff-only")
                    preview = json.loads(self.check_cli(consumer, *offered))
                    self.assertTrue(preview["structure_review"]["needs_scan"])
                    pending = self.check_cli(consumer, "check", success=False)
                    self.assertIn("Workspace system_version differs", pending)
                    self.assertNotIn("Use Scope, Evidence, and Next action", pending)
                    self.check_cli(consumer, "align")
                else:
                    self.check_cli(consumer, "git", "system", "pull")
                self.assertFalse(private.exists())
                private = consumer / "studio"
                plan = private / PLAN
                preview = json.loads(self.check_cli(consumer, *offered))
                self.assertFalse(preview["structure_review"]["needs_scan"])
                self.assertEqual(preview["structure_review"]["records"][0]["path"], PLAN)
                self.assertEqual(plan.read_bytes(), expected)
                if method == "interrupted":
                    self.assertFalse((private / ".hub-filing-pending.json").exists())
                    with zipfile.ZipFile(private / ".hub-history/historical-filing.zip") as recovery:
                        self.assertEqual(recovery.read("original/" + PLAN), original)
                if method == "section-lead":
                    self.assertEqual((private / "context/company/overview.md").read_bytes(), company_before)
                    held = self.check_cli(consumer, "task-context", "--company", "Prepare a partner handoff.")
                    self.assertEqual(json.loads(held)["status"], "onboarding_required")
                    reviewed_studio(consumer, private)
                    context = self.check_cli(consumer, "task-context", "--company", "Prepare a partner handoff.")
                    self.assertIn(fact, context)
                installed = workspace.settings(consumer)
                self.assertEqual((installed["system_version"], installed["workspace_format"]), (next_version, 2))
                self.assertIn("PASS", self.check_cli(consumer, "check"))
