"""Exercise the physical checkout transition and the client boundaries that protect it."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import unittest
from unittest.mock import patch

import test_pm
from onboarding_fixtures import reviewed_setup
import context_capture
import hook
import pm
import snapshots
import storage
import upgrades


class LayoutEntrypointTests(unittest.TestCase):
    setUp = reviewed_setup

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
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        result = json.loads(first.stdout)
        self.assertEqual(result["private_root_move"], {"from": "workspace", "to": "studio"})
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
        checked = self.cli("check")
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)

    def test_private_rename_rejects_bound_worktrees_before_any_migration(self):
        previous = self.root / "private"
        self.work.rename(previous)
        settings = previous / "settings.json"
        original = settings.read_bytes()
        (previous / ".git/worktrees").mkdir()
        result = self.cli("align")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("worktree bindings", result.stdout + result.stderr)
        self.assertEqual(settings.read_bytes(), original)
        self.assertFalse(self.work.exists())
        self.assertFalse((self.root / ".git/pm-hub-backups").exists())

    def test_unignored_studio_stops_before_opening_a_new_checkout(self):
        rules = self.root / ".gitignore"
        rules.write_text("\n".join(row for row in rules.read_text().splitlines()
                                   if row not in {"/studio/", "/[Ss][Tt][Uu][Dd][Ii][Oo]/"}) + "\n")
        previous = self.root / "private"
        self.work.rename(previous)
        settings = (previous / "settings.json").read_bytes()
        result = self.cli("align")
        self.assertIn("Add /studio/ to the system .gitignore", result.stdout + result.stderr)
        self.assertEqual((previous / "settings.json").read_bytes(), settings)
        self.assertFalse(self.work.exists())

    def test_exclusive_rename_preserves_competing_file_and_empty_directory(self):
        for directory in (False, True):
            with self.subTest(directory=directory):
                source = self.work / f"source-{directory}"
                target = self.work / f"destination-{directory}"
                if directory:
                    source.mkdir()
                    (source / "note").write_bytes(b"old data")
                    target.mkdir()
                else:
                    source.write_bytes(b"old data")
                    target.write_bytes(b"new data")
                with self.assertRaises(FileExistsError):
                    storage.rename_exclusive(source, target)
                if directory:
                    self.assertEqual((source / "note").read_bytes(), b"old data")
                    self.assertEqual(list(target.iterdir()), [])
                else:
                    self.assertEqual(source.read_bytes(), b"old data")
                    self.assertEqual(target.read_bytes(), b"new data")

    def test_backup_reads_both_locked_files_through_their_own_handles(self):
        locks = {self.root / ".git/pm-hub-writer.lock": b"outer lock\x00\x17",
                 self.work / ".git/pm-hub-writer.lock": b"private lock\xff\r\n"}
        for path, data in locks.items():
            path.write_bytes(data)
        regular_open = Path.open

        def guarded_open(path, *args, **kwargs):
            if path in locks:
                raise PermissionError("A separate handle cannot read this locked byte range")
            return regular_open(path, *args, **kwargs)

        with storage.writer_lock(self.work), patch.object(Path, "open", guarded_open):
            archive = snapshots.ensure(self.root, "0.3.0", layout_change=True)
        with tarfile.open(archive, "r:gz") as saved:
            for path, data in locks.items():
                member = path.relative_to(self.root).as_posix()
                self.assertEqual(saved.extractfile(member).read(), data)
                self.assertEqual(path.read_bytes(), data)

    @unittest.skipUnless(os.name == "posix", "Windows excludes replacement of the open lock file")
    def test_snapshot_detects_lockfile_replaced_before_backup_inventory(self):
        path = self.work / ".git/pm-hub-writer.lock"
        with storage.writer_lock(self.work):
            replacement = path.with_suffix(".replacement")
            replacement.write_bytes(b"new file at the locked path")
            replacement.replace(path)
            with self.assertRaisesRegex(ValueError, "lock was replaced"):
                snapshots.ensure(self.root, "0.3.0", layout_change=True)
        self.assertEqual(path.read_bytes(), b"new file at the locked path")
        self.assertEqual(list((self.root / ".git/pm-hub-backups").glob("*/hub.tar.gz")), [])

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
