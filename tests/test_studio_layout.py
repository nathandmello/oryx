"""Exercise Studio upgrades using populated, isolated repositories."""

import errno
import json
import os
from pathlib import Path
import subprocess
import tarfile
import unittest
from unittest.mock import patch

import test_pm

import customizations
import hook
import overrides
import pm
import storage
import studio_layout


class StudioLayoutTests(unittest.TestCase):
    setUp = test_pm.HubTests.setUp

    def install_legacy(self):
        rule = {"scope": "Portfolio reviews", "behavior": "Open with pending decisions."}
        state = {"rules": {"review-order": rule}, "reporting": False, "reports": {
            "review-order": {"fictional-digest": "fictional receipt"}}, "retired": [], "pending": []}
        settings = {"version": 1, "config": {}, "values": {}, "retired": []}
        contents = {".hub-overrides.json": json.dumps(state), ".hub-customizations.json": json.dumps(settings),
                    "workspace/.views/board.html": "<!-- pm:roadmap-data -->",
                    "workspace/.views/assets/panel.css": "p { color: black; }"}
        for name, content in contents.items():
            file = self.work / name
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(content.encode() + b"\r\n")
        return contents

    def test_preview_reads_legacy_then_moves_bytes_and_history(self):
        contents = self.install_legacy()
        original = {k: (self.work / k).read_bytes() for k in contents}
        self.assertIn("Open with pending decisions.", overrides.guidance(self.work))
        self.assertIn("pm:roadmap-data", customizations.page_template(self.root, "board"))
        preview = pm.alignment(self.root)
        self.assertTrue(preview["needs_setup"])
        self.assertEqual(set(preview["studio_moves"]), set(studio_layout.LEGACY.values()))
        result = pm.alignment(self.root, True)
        self.assertEqual(result["studio_moves"], preview["studio_moves"])
        with tarfile.open(result["installation_backup"]) as archive:
            for name, data in original.items():
                self.assertEqual(archive.extractfile(f"studio/{name}").read(), data)
                old = Path(name)
                base = next(prefix for prefix in preview["studio_moves"] if old.is_relative_to(prefix))
                new = self.work / preview["studio_moves"][base] / old.relative_to(base)
                self.assertEqual(new.read_bytes(), data)
                self.assertFalse((self.work / old).exists())
        self.assertIn("fictional receipt", overrides.read(self.work)[1]["reports"]["review-order"].values())
        self.assertEqual(pm.alignment(self.root, True)["studio_moves"], {})
        self.assertEqual(pm.check(self.root), [])

    def test_personal_skill_is_editable_and_kept_out_of_evidence(self):
        article = self.work / "customizations/skills/friday/SKILL.md"
        relative = article.relative_to(self.root).as_posix()
        content = "# Friday handoff\n\nLead with decisions.\n"
        for event in [
            {"tool_name": "Write", "tool_input": {"file_path": str(article), "content": content}},
            {"tool_name": "apply_patch", "tool_input": {"input": "*** Begin Patch\n*** Add File: " + relative +
                                                        "\n+# Friday handoff\n*** End Patch"}},
        ]:
            self.assertEqual(hook.edit_guard(self.root, self.root, event), {})
        article.parent.mkdir(parents=True)
        article.write_text(content)
        args = pm.build_parser().parse_args(["override", "set", "friday", "--scope", "Friday handoff",
                                             "--behavior", "Use my handoff format.", "--steps", f"Read {relative}."])
        overrides.run(self.root, args)
        self.assertIn("pm.py override show friday", overrides.guidance(self.work))
        show = pm.build_parser().parse_args(["override", "show", "friday"])
        self.assertIn(relative, overrides.run(self.root, show)["effective"][0]["behavior"])
        self.assertNotIn("friday", str(pm.task_context.catalog(self.work)).lower())
        self.assertEqual(pm.check(self.root), [])

    def test_failure_after_one_move_can_resume(self):
        self.install_legacy()
        rename = storage.rename_exclusive
        def interrupt(path, destination):
            if path.name == ".hub-customizations.json":
                raise OSError("interrupted")
            return rename(path, destination)
        with patch.object(storage, "rename_exclusive", interrupt), self.assertRaisesRegex(OSError, "interrupted"):
            pm.alignment(self.root, True)
        self.assertIn("Open with pending decisions.", overrides.guidance(self.work))
        self.assertEqual(len(pm.alignment(self.root)["studio_moves"]), 2)
        pm.alignment(self.root, True)
        self.assertEqual(pm.alignment(self.root)["studio_moves"], {})

    def test_editor_creating_destination_cannot_be_overwritten(self):
        self.install_legacy()
        source = self.work / ".hub-overrides.json"
        destination = self.work / studio_layout.RULES
        original = source.read_bytes()
        rename = storage.rename_exclusive
        def publish_at_last_moment(old, new):
            new.write_text("Concurrent edit")
            return rename(old, new)
        with patch.object(storage, "rename_exclusive", publish_at_last_moment), self.assertRaises(OSError):
            pm.alignment(self.root, True)
        self.assertEqual(source.read_bytes(), original)
        self.assertEqual(destination.read_text(), "Concurrent edit")

    def test_preflight_preserves_every_original_on_conflict(self):
        contents = self.install_legacy()
        destination = self.work / studio_layout.SETTINGS
        destination.write_text("An independent PM edit")
        with self.assertRaisesRegex(ValueError, "Both"):
            pm.alignment(self.root, True)
        self.assertTrue(all((self.work / name).is_file() for name in contents))
        subprocess.run(["git", "-C", str(self.work), "add", studio_layout.SETTINGS], check=True)
        destination.unlink()
        with self.assertRaisesRegex(ValueError, "occupied"):
            pm.alignment(self.root, True)
        self.assertTrue(all((self.work / name).is_file() for name in contents))

    def test_staged_file_ancestor_and_missing_destination_children_stay_reserved(self):
        self.install_legacy()
        for name in ("customizations", "customizations/rules.json/other",
                     "customizations/views/staged-only.css", "CustomizationS/other"):
            with self.subTest(name=name):
                path = self.work / name
                if name == "customizations" and path.exists():
                    path.rmdir()
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("staged work")
                subprocess.run(["git", "-C", str(self.work), "add", "--", name], check=True)
                path.unlink()
                parent = path.parent
                while parent != self.work:
                    parent.rmdir()
                    parent = parent.parent
                with self.assertRaisesRegex(ValueError, "occupied"):
                    pm.alignment(self.root, True)
                self.assertTrue((self.work / ".hub-overrides.json").is_file())
                blob = subprocess.check_output(["git", "-C", str(self.work), "show", ":" + name])
                self.assertEqual(blob, b"staged work")
                subprocess.run(["git", "-C", str(self.work), "rm", "--quiet", "--cached", "--", name], check=True)
                (self.work / "customizations").mkdir(exist_ok=True)

    def test_a_staged_destination_deletion_is_preserved(self):
        self.install_legacy()
        dest = self.work / studio_layout.RULES
        dest.parent.mkdir(exist_ok=True)
        dest.write_text("personal rule scheduled for deletion")
        def git(*args):
            return subprocess.check_output(["git", "-C", str(self.work), "-c", "user.name=QA",
                                            "-c", "user.email=qa@example.invalid", *args])
        git("add", "--", studio_layout.RULES)
        git("commit", "--quiet", "--no-gpg-sign", "-m", "Prior Studio rule")
        git("rm", "--", studio_layout.RULES)
        staged = git("write-tree")
        with self.assertRaisesRegex(ValueError, "occupied"):
            pm.alignment(self.root, True)
        self.assertFalse(dest.exists())
        self.assertEqual(git("write-tree"), staged)
        self.assertTrue((self.work / ".hub-overrides.json").is_file())

    @unittest.skipUnless(os.name == "posix", "Exercise POSIX asset filenames")
    def test_opaque_view_asset_names_survive_alignment_and_inventory(self):
        self.install_legacy()
        assets = self.work / "workspace/.views/assets"
        names = ["palette-色.css", "two\rlines.css"]
        for name in names:
            (assets / name).write_bytes(b"raw\xffasset")
        opaque_name = os.fsdecode(b"colour-\xff.css")
        try:
            (assets / opaque_name).write_bytes(b"raw\xffasset")
        except OSError as exc:
            if exc.errno != errno.EILSEQ:  # Some filesystems require UTF-8 filenames.
                raise
        else:
            names.append(opaque_name)
        result = pm.alignment(self.root, True)
        self.assertTrue(result["studio_moves"])
        visible = set(storage.inventory(self.work))
        for name in names:
            path = self.work / studio_layout.VIEWS / "assets" / name
            self.assertIn(path, visible)
            self.assertEqual(path.read_bytes(), b"raw\xffasset")
        self.assertEqual(pm.alignment(self.root)["studio_moves"], {})

    def test_ignored_files_and_redirected_views_stop_before_moving(self):
        self.install_legacy()
        ignore = self.work / ".gitignore"
        original = ignore.read_text()
        for name in ("workspace/.views/assets/", "customizations/views/assets/"):
            ignore.write_text(original + "\n" + name + "\n")
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "ignore"):
                pm.alignment(self.root, True)
            self.assertTrue((self.work / ".hub-overrides.json").exists())
        ignore.write_text(original)
        asset = self.work / "workspace/.views/alias"
        try:
            asset.symlink_to(self.root / "README.md")
        except OSError:
            self.skipTest("Symbolic links unavailable")
        with self.assertRaisesRegex(ValueError, "regular"):
            pm.alignment(self.root, True)
        self.assertTrue((self.work / ".hub-overrides.json").exists())
