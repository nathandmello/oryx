"""Exercise the physical checkout transition and the client boundaries that protect it."""

import json
from pathlib import Path
import subprocess
import sys
import unittest

import test_pm
import context_capture
import hook
import pm
import storage
import upgrades


class LayoutEntrypointTests(unittest.TestCase):
    setUp = test_pm.HubTests.setUp

    def cli(self, *args, payload=None):
        return subprocess.run([sys.executable, str(self.root / "tools/pm.py"), *args], cwd=self.root,
                              input=json.dumps(payload) if payload else None, capture_output=True, text=True)

    def test_move_and_review_old_assets_with_clean_restart(self):
        previous = self.root / "workspace"
        self.work.rename(previous)
        test_pm.use_previous_layout(previous)
        product = previous / "products/basket"
        product.mkdir(parents=True)
        hidden = product / ".editor-private"
        hidden.write_bytes(b"local metadata\r\n")
        asset = product / "settlement.csv"
        original = b"amount,unit\r\n42,USD\r\n"
        asset.write_bytes(original)
        choice = self.cli("align", "--status")
        self.assertEqual(choice.returncode, 0, choice.stdout)
        self.assertFalse(self.work.exists())
        first = self.cli("align")
        self.assertEqual(first.returncode, 0, first.stdout)
        result = json.loads(first.stdout)
        self.assertEqual(result["private_root_move"], {"from": "workspace", "to": "private"})
        self.assertTrue(Path(result["installation_backup"]).is_file())
        self.assertFalse(previous.exists())
        path = self.work / asset.relative_to(previous)
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual((self.work / hidden.relative_to(previous)).read_bytes(), b"local metadata\r\n")
        row = next(r for r in result["outstanding"] if r["path"] == "products/basket/settlement.csv")
        receipt = self.cli("align", "--record", row["path"], "--outcome", "source", "--digest", row["digest"],
                           "--note", "Original settlement statement from Finance.")
        self.assertEqual(receipt.returncode, 0, receipt.stdout)
        second = self.cli("align")
        self.assertEqual(second.returncode, 0, second.stdout)
        self.assertNotIn(row["path"], [item["path"] for item in json.loads(second.stdout)["outstanding"]])
        self.assertIn(row["path"], upgrades.source_paths(self.work))
        self.assertFalse(json.loads(second.stdout)["layout"]["changed"])
        self.assertEqual(self.cli("check").returncode, 0)

    def test_native_work_and_profile_source_guards(self):
        old = self.root / "workspace/products/obsolete.md"
        backlog = self.work / "workspace/backlogs/refunds.md"
        plan = self.work / "workspace/initiatives/refunds/plan.md"
        for dest, content, blocked in ((old, "Draft", True), (backlog, "# Backlog", False),
                                       (plan, "<!-- pm: context-note -->", True)):
            payload = {"tool_name": "Write", "tool_input": {"file_path": str(dest), "content": content}}
            self.assertEqual(bool(hook.edit_guard(self.root, self.root, payload)), blocked)
        bad = self.work / "workspace/goals/unfinished.md"
        bad.parent.mkdir(parents=True)
        bad.write_text("# A draft goal\n")
        self.assertTrue(any("matching typed artifact" in err for err in pm.check(self.root)))
        profile = self.work / context_capture.REMIT_PATH
        profile.parent.mkdir(parents=True)
        profile.write_bytes(b"# Original interview\r\n")
        ledger = self.work / upgrades.LEDGER
        state = upgrades.read_state(self.work)[1]
        state[upgrades.RULE][context_capture.REMIT_PATH] = {
            "status": "reviewed", "role": "source", "note": "Original interview record.",
            "digest": upgrades.fingerprint(profile)}
        storage.replace_text(ledger, ledger.read_text(), upgrades.encode(state))
        saved = self.cli("set-remit", payload={"status": "confirmed", "responsibilities": [], "follow": []})
        self.assertNotEqual(saved.returncode, 0)
        self.assertEqual(profile.read_bytes(), b"# Original interview\r\n")
