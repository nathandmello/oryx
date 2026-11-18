"""Exercise accepted and rejected changes in disposable checkouts."""

import json
from datetime import date, timedelta
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import hook
import pm
import records
import workspace


class HubTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve() / "hub with spaces"
        self.root.mkdir()
        for source in pm.inventory(pm.ROOT):
            if source.is_file() and not source.is_symlink():
                target = self.root / source.relative_to(pm.ROOT)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
        subprocess.run(["git", "init", "--quiet", "--initial-branch=main", str(self.root)], check=True)
        self.work = workspace.initialise(self.root, owner="Fixture PM", delivery_system="Fixture delivery")

    def test_scaffold_passes(self):
        self.assertEqual(pm.check(self.root), [])

    def test_skill_drift_is_rejected_and_sync_is_idempotent(self):
        target = self.root / ".claude/skills/extend-hub/SKILL.md"
        target.write_text("Changed adapter.\n")
        self.assertTrue(any("sync-skills" in error for error in pm.check(self.root)))
        self.assertEqual(pm.sync_skills(self.root), 1)
        self.assertEqual(pm.sync_skills(self.root), 0)
        self.assertEqual(pm.check(self.root), [])

    def test_high_level_brief_passes_and_prd_copy_fails(self):
        brief = self.work / "products/initiative.md"
        brief.write_text("# Initiative\n\nHelp administrators choose their next action.\n")
        self.assertEqual(pm.check(self.root), [])
        (self.work / "products/PRD-security-hub.md").write_text("# Product specification\n")
        self.assertTrue(any("engineering artifacts" in error for error in pm.check(self.root)))

    def test_writing_limits(self):
        self.assertEqual(pm.writing_errors("Use clear words.\n"), [])
        self.assertTrue(pm.writing_errors(" ".join(["word"] * 26) + "."))
        self.assertTrue(pm.writing_errors("1. " + " ".join(["word"] * 21) + "."))
        self.assertTrue(pm.writing_errors("Short sentence. " * 7))
        self.assertTrue(pm.writing_errors("A word.\n\n" * 401))
        self.assertTrue(pm.writing_errors("We should add this."))

    def test_source_quotes_and_code_keep_their_words(self):
        text = '> We should preserve this quote.\n\n```text\n' + 'long ' * 50 + '\n```\n'
        self.assertEqual(pm.writing_errors(text), [])

    def test_broken_and_external_local_links_fail(self):
        path = self.work / "context/README.md"
        path.write_text("Read the [missing source](absent.md).\n")
        self.assertTrue(any("broken link" in error for error in pm.check(self.root)))
        path.write_text("Read the [shared document](../../../plesk-hub/README.md).\n")
        self.assertTrue(any("link leaves" in error for error in pm.check(self.root)))
        path.write_text("| Source |\n| --- |\n| [Missing](absent.md) |\n")
        self.assertTrue(any("broken link" in error for error in pm.check(self.root)))

    def test_disabled_or_filtered_hooks_fail(self):
        path = self.root / ".claude/settings.json"
        config = json.loads(path.read_text())
        config["disableAllHooks"] = True
        path.write_text(json.dumps(config))
        self.assertTrue(any("client configuration" in error for error in pm.check(self.root)))
        path = self.root / ".codex/hooks.json"
        config = json.loads(path.read_text())
        config["hooks"]["SessionStart"][0]["matcher"] = "never"
        path.write_text(json.dumps(config))
        self.assertTrue(any("without a matcher" in error for error in pm.check(self.root)))

    def test_split_agent_instructions_fail(self):
        (self.root / "CLAUDE.md").write_text("Different rules.\n")
        self.assertTrue(any("duplicate instructions" in error for error in pm.check(self.root)))

    def test_secret_contents_are_never_read(self):
        private = self.root / ".env"
        private.write_text("DISPOSABLE_FIXTURE=1\n")
        subprocess.run(["git", "-C", str(self.root), "add", "--force", ".env"], check=True)
        original = Path.read_text

        def read(path, *args, **kwargs):
            if path == private:
                raise AssertionError("Private file was read")
            return original(path, *args, **kwargs)

        with patch.object(Path, "read_text", read):
            self.assertTrue(any("private file" in error for error in pm.check(self.root)))

    def test_symlinks_cannot_escape_the_checkout(self):
        outside = self.root.parent / "outside.md"
        outside.write_text("External fixture.\n")
        (self.work / "context/escape.md").symlink_to(outside)
        self.assertTrue(any("regular files" in error for error in pm.check(self.root)))
        source = self.root / ".agents/skills/extend-hub/escape.md"
        source.symlink_to(outside)
        with self.assertRaises(ValueError):
            pm.sync_skills(self.root)

    def test_hook_checks_a_nested_session_and_returns_valid_json(self):
        payload = {"hook_event_name": "Stop", "cwd": str(self.work / "context")}
        result = self.run_hook(json.dumps(payload))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {})
        (self.work / "products/prd.md").write_text("# PRD\n")
        result = self.run_hook(json.dumps(payload))
        self.assertEqual(json.loads(result.stdout)["decision"], "block")

    def test_hook_failure_is_bounded_and_visible(self):
        first = hook.response("Stop", ["A failed check."])
        self.assertEqual(first["decision"], "block")
        retry = hook.response("Stop", ["A failed check."], retry=True)
        self.assertNotIn("decision", retry)
        self.assertIn("failed", retry["systemMessage"])
        self.assertIn("systemMessage", hook.response("SessionStart", ["A failed check."]))
        self.assertEqual(self.run_hook("invalid json").returncode, 2)

    def test_each_template_creates_a_valid_unfinished_draft(self):
        for kind in records.KINDS:
            home = "context" if kind == "company-context" else "products/example"
            target = records.create(self.root, kind, f"{home}/{kind}.md", "A draft")
            values, errors = records.work_state(target.read_text())
            self.assertEqual(errors, [])
            self.assertEqual(values["State"], "draft")
            self.assertNotIn("{{", values["ID"])
        self.assertEqual(pm.check(self.root), [])

    def test_creation_never_overwrites_or_escapes(self):
        target = records.create(self.root, "problem", "context/example.md")
        original = target.read_bytes()
        with self.assertRaises(FileExistsError):
            records.create(self.root, "problem", "context/example.md")
        self.assertEqual(target.read_bytes(), original)
        for destination in ("../outside.md", "context/../../outside.md", "/tmp/outside.md", "README.md"):
            with self.assertRaises(ValueError):
                records.create(self.root, "problem", destination)

    def test_waiting_work_needs_a_concrete_dependency_and_resume_trigger(self):
        target = records.create(self.root, "problem", "products/example/problem.md")
        text = target.read_text().replace("| State | draft |", "| State | waiting |")
        target.write_text(text)
        self.assertTrue(any("Next action" in error for error in pm.check(self.root)))
        self.assertTrue(any("Waiting on" in error for error in pm.check(self.root)))
        text = text.replace("{{one concrete step}}", "Compare the interview findings.")
        text = text.replace("| Waiting on | none |", "| Waiting on | Two customer interviews. |")
        text = text.replace("| Resume when | none |", "| Resume when | Both interview notes arrive. |")
        text = text.replace("| Mode | thought-partner |", "| Mode | quiet |")
        target.write_text(text)
        self.assertEqual(pm.check(self.root), [])

    def test_complete_artifacts_cannot_hide_placeholders(self):
        target = records.create(self.root, "goal", "context/example.md")
        text = target.read_text().replace("| State | draft |", "| State | complete |")
        target.write_text(text)
        self.assertTrue(any("resolve placeholders" in error for error in pm.check(self.root)))
        text = records.PLACEHOLDER.sub("Explicit gap recorded for review.", text)
        target.write_text(text)
        self.assertEqual(pm.check(self.root), [])

    def test_invalid_modes_and_checkpoints_fail_without_changing_draft_rules(self):
        target = records.create(self.root, "problem", "context/example.md")
        text = target.read_text().replace("| State | draft |", "| State | active |")
        text = text.replace("{{one concrete step}}", "Compare the interview findings.")
        text = text.replace("| Mode | thought-partner |", "| Mode | silent-forever |")
        target.write_text(text)
        self.assertTrue(any("Mode must" in error for error in pm.check(self.root)))
        text = text.replace("silent-forever", "quiet")
        text = re.sub(r"\| Last checkpoint \| .+? \|", "| Last checkpoint | 2026-02-31: Notes read. |", text)
        target.write_text(text)
        self.assertTrue(any("valid ISO date" in error for error in pm.check(self.root)))

    def test_artifact_ids_are_unique_and_sections_are_present(self):
        target = records.create(self.root, "goal", "context/example.md")
        duplicate = self.work / "context/duplicate.md"
        duplicate.write_text(target.read_text().replace("## Outcome", "## Other"))
        errors = pm.check(self.root)
        self.assertTrue(any("duplicate ID" in error for error in errors))
        self.assertTrue(any("missing section: Outcome" in error for error in errors))

    def test_nested_drafts_retarget_template_links(self):
        source = self.root / "templates/goal.md"
        source.write_text(source.read_text() + "\nRead [the framework](../playbook/framework.md).\n")
        target = records.create(self.root, "goal", "products/example/goals/goal.md")
        self.assertIn("../../../../playbook/framework.md", target.read_text())
        self.assertEqual(pm.check(self.root), [])

    def test_guidance_cannot_accumulate_at_the_root(self):
        source = self.root / "playbook/framework.md"
        moved = self.root / "framework.md"
        source.rename(moved)
        self.assertTrue(any("placement map" in error for error in pm.check(self.root)))
        moved.rename(source)
        self.assertEqual(pm.check(self.root), [])

    def test_unrequested_templates_are_rejected(self):
        extra = self.root / "templates/persona.md"
        extra.write_text("# Persona\n")
        self.assertTrue(any("unregistered template" in error for error in pm.check(self.root)))

    def context_record(self, kind="company-context", path="context/company.md", parent="none"):
        target = records.create(self.root, kind, path, owner="Fixture PM")
        text = target.read_text()
        for name in re.findall(r"^## (.+)$", text, re.M):
            if name not in {"Context controls", "Sources", "Work state"}:
                text = text.replace(records.section(text, name), "\n- Unknown: Evidence has not arrived.\n\n")
        today = date.today().isoformat()
        values = {
            "Parent context": parent,
            "Last reviewed": today,
            "Review by": (date.today() + timedelta(days=30)).isoformat(),
            "Review triggers": "Review after a company goal changes.",
            "Next action": "Ask Fixture PM about the current scope.",
            "State": "active",
        }
        for name, value in values.items():
            text = re.sub(r"\| " + name + r" \| [^\n]+ \|", f"| {name} | {value} |", text)
        body = "\n| ID | Source | Source date | Checked on |\n| --- | --- | --- | --- |\n"
        body += f"| S1 | Fixture PM, fixture discussion | {today} | {today} |\n\n"
        text = text.replace(records.section(text, "Sources"), body)
        target.write_text(text)
        return target

    def test_contexts_can_record_gaps_and_link_to_parent_without_copies(self):
        self.context_record()
        product = self.context_record("product-context", "products/example/context.md",
                                      "[Company](../../context/company.md)")
        text = product.read_text().replace("- Unknown: Evidence has not arrived.",
                                           "- Fact: This is a fixture. [S1]", 1)
        text = text.replace("| State | active |", "| State | complete |")
        product.write_text(text)
        self.assertEqual(pm.check(self.root), [])

    def test_context_claims_need_labels_and_valid_source_references(self):
        target = self.context_record()
        original = target.read_text()
        for entry, expected in (
            ("This claim has no label.", "labelled"),
            ("- Fact: This claim has no source.", "Fact entries need"),
            ("- Fact: This claim cites a missing source. [S2]", "unknown source reference"),
        ):
            with self.subTest(entry=entry):
                target.write_text(original.replace("- Unknown: Evidence has not arrived.", entry, 1))
                self.assertTrue(any(expected in error for error in pm.check(self.root)))
        target.write_text(original.replace("- Unknown: Evidence has not arrived.",
                                           "- Fact: This claim continues\n  with its source. [S1]", 1))
        self.assertEqual(pm.check(self.root), [])

    def test_context_sources_require_unique_ids_and_honest_dates(self):
        target = self.context_record()
        original = target.read_text()
        today = date.today().isoformat()
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        row = f"| S1 | Fixture PM, fixture discussion | {today} | {today} |"
        for replacement, expected in (
            (row + "\n" + row, "duplicate source ID"),
            (row.replace(f"| {today} | {today} |", f"| {today} | unknown |"), "Checked on needs"),
            (row.replace(f"| {today} | {today} |", f"| {tomorrow} | {tomorrow} |"), "future"),
            (row.replace(f"| {today} | {today} |", f"| {today} | {yesterday} |"), "cannot follow"),
            (row.replace("Fixture PM, fixture discussion", "{{source}}"), "Source needs"),
        ):
            with self.subTest(replacement=replacement):
                target.write_text(original.replace(row, replacement))
                self.assertTrue(any(expected in error for error in pm.check(self.root)))
        for value in ("unknown", "undated"):
            target.write_text(original.replace(row, row.replace(f"| {today} | {today} |", f"| {value} | {today} |")))
            self.assertEqual(pm.check(self.root), [])

    def test_context_reviews_expire_and_require_controls_after_draft(self):
        target = self.context_record()
        original = target.read_text()
        today = date.today().isoformat()
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        due = (date.today() + timedelta(days=30)).isoformat()
        for old, new, expected in (
            (f"| Review by | {due} |", f"| Review by | {yesterday} |", "overdue"),
            (f"| Last reviewed | {today} |", "| Last reviewed | not reviewed |", "Last reviewed needs"),
            (f"| Last reviewed | {today} |", f"| Last reviewed | {tomorrow} |", "future"),
            ("| Maintainer | Fixture PM |", "| Maintainer | unknown |", "Maintainer needs"),
            ("Review after a company goal changes.", "{{trigger}}", "Review triggers needs"),
        ):
            with self.subTest(expected=expected):
                target.write_text(original.replace(old, new))
                self.assertTrue(any(expected in error for error in pm.check(self.root)))

    def test_context_parent_must_exist_have_right_type_and_avoid_cycles(self):
        company = self.context_record()
        product = self.context_record("product-context", "products/example/context.md",
                                      "[Company](../../context/company.md)")
        original = product.read_text()
        for parent in ("none", "[Missing](../../context/missing.md)", "[Readme](../../context/README.md)",
                       "[Template](../../templates/company-context.md)",
                       "[External](https://example.com/company.md)"):
            with self.subTest(parent=parent):
                product.write_text(original.replace("[Company](../../context/company.md)", parent))
                self.assertTrue(any("Parent context" in error for error in pm.check(self.root)))
        product.write_text(original)
        self.context_record(path="context/unit.md", parent="[Company](company.md)")
        company.write_text(company.read_text().replace("| Parent context | none |", "| Parent context | [Unit](unit.md) |"))
        self.assertTrue(any("forms a cycle" in error for error in pm.check(self.root)))

    def test_context_location_and_control_structure_are_enforced(self):
        for kind, destination in (("company-context", "products/example/company.md"),
                                  ("product-context", "context/product.md"),
                                  ("product-context", "products/context.md")):
            with self.subTest(destination=destination), self.assertRaises(ValueError):
                records.create(self.root, kind, destination)
        target = self.context_record()
        original = target.read_text()
        target.write_text(original.replace("| Maintainer | Fixture PM |\n", ""))
        self.assertTrue(any("missing context control" in error for error in pm.check(self.root)))
        target.write_text(original.replace("| Maintainer | Fixture PM |", "| Maintainer | Fixture PM |\n| Maintainer | Fixture PM |"))
        self.assertTrue(any("duplicate context control" in error for error in pm.check(self.root)))
        target.write_text(original)
        target.rename(self.work / "products/company.md")
        self.assertTrue(any("company context belongs" in error for error in pm.check(self.root)))

    def test_context_can_wait_across_sessions_with_explicit_gaps(self):
        target = self.context_record()
        text = target.read_text().replace("| State | active |", "| State | waiting |")
        text = text.replace("| Waiting on | none |", "| Waiting on | Fixture PM's company goals. |")
        text = text.replace("| Resume when | none |", "| Resume when | Fixture PM supplies the goals. |")
        target.write_text(text)
        self.assertEqual(pm.check(self.root), [])

    def run_hook(self, payload):
        return subprocess.run(
            [sys.executable, "-B", str(self.root / "tools/hook.py")],
            input=payload, text=True, capture_output=True, cwd=self.root,
        )


if __name__ == "__main__":
    unittest.main()
