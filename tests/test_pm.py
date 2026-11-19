"""Exercise accepted and rejected changes in disposable checkouts."""

import json
import os
from datetime import date, timedelta
from html import unescape
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
import red_team_eval
import upgrades
import workspace


def legacy_product(root, private, name):
    path = private / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(records.draft_text(root, "product-context", path, "Earlier product brief"))
    return path


def use_previous_layout(private, version="0.2.0"):
    import layout_upgrade
    import upgrades
    settings = private / "settings.json"
    values = json.loads(settings.read_text())
    values.update(system_version=version, workspace_format=1)
    settings.write_text(json.dumps(values))
    ledger, values = upgrades.read_state(private)
    values.pop(layout_upgrade.RULE, None)
    if ledger is not None:
        (private / upgrades.LEDGER).write_text(upgrades.encode(values))


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

    def test_system_check_catches_stale_template_index_and_routing_guide(self):
        index = self.root / "templates/README.md"
        guide = self.root / "playbook/context.md"
        # Both links still resolve. The product template has disappeared from the index.
        index.write_text(index.read_text().replace("](product-context.md)", "](company-context.md)"))
        guide.write_text(guide.read_text().replace("`purpose`", "`old-purpose`"))
        errors = pm.check(self.root, include_workspace=False)
        self.assertTrue(any("templates/README.md" in e and "product-context.md" in e for e in errors), errors)
        self.assertTrue(any("product" in e and "missing" in e and "purpose" in e for e in errors), errors)
        self.assertTrue(any("product" in e and "unsupported" in e and "old-purpose" in e for e in errors), errors)

    def test_skill_drift_is_rejected_and_sync_is_idempotent(self):
        target = self.root / ".claude/skills/extend-hub/SKILL.md"
        target.write_text("Changed adapter.\n")
        self.assertTrue(any("sync-skills" in error for error in pm.check(self.root)))
        self.assertEqual(pm.sync_skills(self.root), 1)
        self.assertEqual(pm.sync_skills(self.root), 0)
        self.assertEqual(pm.check(self.root), [])

    def test_high_level_brief_passes_and_prd_copy_fails(self):
        brief = self.work / "workspace/initiatives/example/plan.md"
        brief.parent.mkdir(parents=True)
        brief.write_text("# Initiative\n\n## Scope\n\nHelp administrators choose their next action.\n\n"
                         "## Evidence\n\nAdministrator interviews are pending.\n\n## Next action\n\nSchedule two interviews.\n")
        self.assertEqual(pm.check(self.root), [])
        (brief.parent / "PRD-security-hub.md").write_text("# Product specification\n")
        self.assertTrue(any("engineering artifacts" in error for error in pm.check(self.root)))

    def test_writing_limits(self):
        self.assertEqual(pm.writing_errors("Use clear words.\n"), [])
        self.assertTrue(pm.writing_errors(" ".join(["word"] * 26) + "."))
        self.assertTrue(pm.writing_errors("1. " + " ".join(["word"] * 21) + "."))
        self.assertTrue(pm.writing_errors("- Check " + " ".join(["word"] * 20) + "."))
        self.assertTrue(pm.writing_errors("Short sentence. " * 7))
        self.assertTrue(pm.writing_errors("A word.\n\n" * 401))
        self.assertTrue(pm.writing_errors("Delve into the results."))
        self.assertEqual(pm.writing_errors("The board could raise prices if the regulator approves."), [])

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
        (self.work / "workspace/prd.md").write_text("# PRD\n")
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

    def test_hooks_load_ingestion_and_redirect_new_native_context_files(self):
        cwd = self.work / "context"
        startup = self.run_hook(json.dumps({"hook_event_name": "SessionStart", "cwd": str(cwd)}))
        self.assertEqual(startup.returncode, 0, startup.stderr)
        guidance = json.loads(startup.stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("automatically read", guidance)
        self.assertIn("ingest-context/SKILL.md", guidance)
        self.assertIn("summarize-meeting/SKILL.md before fetching sources", guidance)
        self.assertIn("ask for clarification and wait", guidance)
        self.assertIn("playbook/opportunities.md", guidance)
        for tool, inputs, denied in (
            ("apply_patch", {"command": "*** Begin Patch\n*** Add File: company-audit.md\n+x\n*** End Patch"}, True),
            ("apply_patch", {"command": "*** Add File: ../context/products/example/overview.md\n+x"}, True),
            ("apply_patch", {"command": "*** Add File: ../context/initiatives/pilot/overview.md\n+x"}, True),
            ("Write", {"file_path": str(cwd / "company-research.md")}, True),
            ("Write", {"file_path": str(cwd / "README.md")}, False),
            ("Write", {"file_path": str(self.work / "workspace/initiatives/example/plan.md")}, False),
            ("Write", {"file_path": str(self.work / "workspace/roadmaps/example.md")}, True),
            ("apply_patch", {"command": "*** Add File: ../../templates/new.md\n+x"}, False),
        ):
            with self.subTest(tool=tool, inputs=inputs):
                result = self.run_hook(json.dumps({"hook_event_name": "PreToolUse", "cwd": str(cwd),
                                                   "tool_name": tool, "tool_input": inputs}))
                self.assertEqual(result.returncode, 0, result.stderr)
                output = json.loads(result.stdout)
                if denied:
                    self.assertEqual(output["hookSpecificOutput"]["permissionDecision"], "deny")
                    self.assertIn("route-context", output["hookSpecificOutput"]["permissionDecisionReason"])
                else:
                    self.assertEqual(output, {})

    def test_hooks_route_registered_files_and_preserve_plain_work(self):
        register = self.work / "workspace/backlogs/alpha/initiatives.json"
        register.parent.mkdir(parents=True)
        register.write_text("{}")
        for action in ("Delete File", "Move to", "Add File", "Update File"):
            event = {"tool_name": "apply_patch", "tool_input": {"command": f"*** {action}: {register}"}}
            self.assertIn("initiative propose", hook.edit_guard(self.root, self.work, event)["hookSpecificOutput"]["permissionDecisionReason"])
        def reason(relative):
            event = {"tool_name": "Write", "tool_input": {"file_path": str(self.work / relative), "content": "Draft"}}
            return hook.edit_guard(self.root, self.work, event).get("hookSpecificOutput", {}).get("permissionDecisionReason", "")
        self.assertIn("initiative draft-experiment", reason("workspace/experiments/alpha/reminders/experiment.rate.draft.json"))
        self.assertIn("pm.py new", reason("workspace/initiatives/alpha/reminders/initiative-brief.md"))
        self.assertIn("pm.py new", reason("workspace/roadmaps/alpha/quarter-one.md"))
        self.assertIn("pm.py backlog", reason("workspace/backlogs/alpha.md"))
        self.assertIn("pm.py roadmap", reason("workspace/roadmaps/alpha.md"))
        self.assertEqual(reason("workspace/backlogs/support.md"), "")
        self.assertEqual(reason("workspace/initiatives/support/plan.md"), "")
        self.assertEqual(reason("context/company/sources/initiatives.json"), "")
        (self.work / "workspace/backlogs/alpha.md").write_text("# Historical working notes")
        self.assertEqual(reason("workspace/backlogs/alpha.md"), "")

    @unittest.skipUnless(os.name == "posix", "shared read-only POSIX locks")
    def test_shared_writer_holds_both_repository_locks_without_write_access(self):
        import fcntl
        import grp
        import storage
        paths = [repo / ".git" / "pm-hub-writer.lock" for repo in (self.root, self.work)]
        for path in paths:
            path.touch()
            path.chmod(0o440)
        group = grp.getgrgid(self.work.stat().st_gid).gr_name
        with patch.dict(os.environ, {storage.SHARED_GROUP: group}), storage.writer_lock(self.work):
            for path in paths:
                with path.open("rb") as independent:
                    with self.assertRaises(BlockingIOError):
                        fcntl.flock(independent, fcntl.LOCK_EX | fcntl.LOCK_NB)
        for path in paths:
            self.assertEqual(path.stat().st_mode & 0o777, 0o440)

    def test_each_template_creates_a_valid_unfinished_draft(self):
        import filing
        paths = {"company-context": "context/company/overview.md", "product-context": "context/products/example/overview.md",
                 "initiative-context": "context/initiatives/pilot/overview.md", "context-note": "context/company/rates.md",
                 "product-area-context": "context/products/example/areas/refunds/overview.md",
                 "goal": "workspace/goals/example.md", "problem": "workspace/problems/example.md",
                 "strategy": "workspace/strategies/example.md", "experiment": "workspace/experiments/example.md",
                 "roadmap": "workspace/roadmaps/example.md"}
        self.assertEqual(set(paths), set(records.KINDS) - set(records.OPPORTUNITY_KINDS))
        for kind, path in paths.items():
            args = {}
            if kind == "product-area-context":
                args["filing_contract"] = filing.area_contract(self.work, path, None, None,
                                                               "Support checks refund rules weekly.", "Finance changes the policy.")
            elif kind == "context-note":
                args["filing_contract"] = filing.note_contract(self.work, path, paths["company-context"], "maintained-reference",
                                                               "Finance reviews regional rates.", "New rates take effect.")
            elif kind == "initiative-context":
                args["product_parent"] = paths["product-context"]
            target = records.create(self.root, kind, path, "A draft", **args)
            values, errors = records.work_state(target.read_text())
            self.assertEqual(errors, [])
            self.assertEqual(values["State"], "draft")
            self.assertNotIn("{{", values["ID"])
        self.assertEqual(pm.check(self.root), [])

    def test_creation_never_overwrites_or_escapes(self):
        target = records.create(self.root, "problem", "workspace/problems/example.md")
        original = target.read_bytes()
        with self.assertRaises(FileExistsError):
            records.create(self.root, "problem", "workspace/problems/example.md")
        self.assertEqual(target.read_bytes(), original)
        for destination in ("../outside.md", "context/../../outside.md", "/tmp/outside.md", "README.md"):
            with self.assertRaises(ValueError):
                records.create(self.root, "problem", destination)

    def test_waiting_work_needs_a_concrete_dependency_and_resume_trigger(self):
        target = records.create(self.root, "problem", "workspace/problems/example.md")
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
        target = records.create(self.root, "goal", "workspace/goals/example.md")
        text = target.read_text().replace("| State | draft |", "| State | complete |")
        target.write_text(text)
        self.assertTrue(any("resolve placeholders" in error for error in pm.check(self.root)))
        text = records.PLACEHOLDER.sub("Explicit gap recorded for review.", text)
        target.write_text(text)
        self.assertEqual(pm.check(self.root), [])

    def test_invalid_modes_and_checkpoints_fail_without_changing_draft_rules(self):
        target = records.create(self.root, "problem", "workspace/problems/example.md")
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
        target = records.create(self.root, "goal", "workspace/goals/example.md")
        duplicate = self.work / "workspace/goals/duplicate.md"
        duplicate.write_text(target.read_text().replace("## Outcome", "## Other"))
        errors = pm.check(self.root)
        self.assertTrue(any("duplicate ID" in error for error in errors))
        self.assertTrue(any("missing section: Outcome" in error for error in errors))

    def test_strategy_timing_prompt_preserves_earlier_briefs(self):
        template = self.root / "templates/strategy.md"
        current = template.read_text()
        previous = re.sub(r"^## When\n.*?(?=^## )", "", current, flags=re.M | re.S)
        self.assertNotEqual(previous, current)
        template.write_text(previous)
        previous_draft = records.create(self.root, "strategy", "workspace/strategies/previous.md")
        self.assertIsNone(records.section(previous_draft.read_text(), "When"))

        template.write_text(current)
        current_draft = records.create(self.root, "strategy", "workspace/strategies/current.md")
        self.assertIn("consequence of waiting", records.section(current_draft.read_text(), "When"))
        self.assertEqual(pm.check(self.root), [])

    def test_nested_drafts_retarget_template_links(self):
        source = self.root / "templates/goal.md"
        source.write_text(source.read_text() + "\nRead [the framework](../playbook/framework.md).\n")
        target = records.create(self.root, "goal", "workspace/goals/example.md")
        self.assertIn("../../../playbook/framework.md", target.read_text())
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

    def context_record(self, kind="company-context", path="context/company/overview.md", parent="none"):
        target = records.create(self.root, kind, path, owner="Fixture PM")
        text = target.read_text()
        for name in re.findall(r"^## (.+)$", text, re.M):
            if name in records.CONTEXT_TABLES:
                text = re.sub(rf"^## {re.escape(name)}\n.*?(?=^## |\Z)", "", text, count=1, flags=re.M | re.S)
            elif name not in records.CONTEXT_METADATA:
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
        product = self.context_record("product-context", "context/products/example/overview.md",
                                      "[Company](../../company/overview.md)")
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

    def test_custom_section_claims_and_leads_are_checked(self):
        target = self.context_record()
        original = target.read_text()
        _, state = upgrades.read_state(self.work)
        state.pop(upgrades.STRUCTURE_RULE)
        (self.work / upgrades.LEDGER).write_text(upgrades.encode(state))
        heading = "UK rollout baseline"
        lead = "Consult when comparing UK adoption before and after rollout."
        for body, expected in (
            ("Historical context from an earlier brief.", None),
            ("- Fact: The UK had 2,000 active merchants.", None),
            (f"{records.CONTEXT_LEAD}\n{lead}\n\n- Fact: The UK had 2,000 active merchants. [S1]", None),
            (f"{records.CONTEXT_LEAD}\n{lead}\n\n- Fact: The UK had 2,000 active merchants.", "Fact entries need"),
            (f"{records.CONTEXT_LEAD}\n\n- Fact: The UK had 2,000 active merchants. [S1]", "short prose lead"),
            (f"{records.CONTEXT_LEAD}\n{lead}\n\nThe UK had 2,000 active merchants.", "labelled context bullets"),
        ):
            with self.subTest(body=body):
                target.write_text(original.replace("## Context controls", f"## {heading}\n\n{body}\n\n## Context controls"))
                errors = pm.check(self.root)
                if expected:
                    self.assertTrue(any(heading in error and expected in error for error in errors), errors)
                else:
                    self.assertEqual(errors, [])

    def test_context_capture_flags_ambiguous_and_legacy_section_bodies_in_preview(self):
        target = self.context_record()
        original = target.read_text()
        _, state = upgrades.read_state(self.work)
        state.pop(upgrades.STRUCTURE_RULE)
        (self.work / upgrades.LEDGER).write_text(upgrades.encode(state))
        destination = target.relative_to(self.work).as_posix()
        heading = "UK rollout history"
        section = f"## {heading}\n\nThe UK pilot ended in May.\n\n## Background\n\nThis is an example."
        payload = {"sources": [], "entries": [{
            "scope": "company", "heading": heading, "lead": "Consult when preparing a UK rollout review.",
            "question": "Which region participated in the pilot?",
        }]}
        fenced = f"```markdown\n{section}\n```"
        for body, expected in (
            (section, "verify and label legacy claims"),
            (section.replace("The UK pilot", "- Fact: The UK pilot"), "verify and label legacy claims"),
            (f"## Examples\n\n{fenced}", "Ambiguous context section boundary"),
            (f"## Examples\n\n<!--\n{section}\n-->", "Ambiguous context section boundary"),
            (f"## Examples\n\n{fenced}\n<!-- Fixture -->## {heading}\n<!-- Fixture -->## Background",
             "Ambiguous context section boundary"),
            (f"## Examples\n\n```text\nA note\n```\n<custom-example>\n{section}\n</custom-example>",
             "Ambiguous context section boundary"),
            *((f"## Examples\n\n<{tag}>\n{section}\n</{tag}>", "Ambiguous context section boundary")
              for tag in ("pre", "script", "style", "textarea", "div", "custom-example")),
        ):
            with self.subTest(body=body):
                text = original.replace("## Context controls", f"{body}\n\n## Context controls")
                target.write_text(text)
                self.assertEqual(pm.check(self.root), [])
                for args in ((), ("--write", destination)):
                    result = self.context_capture(payload, *args)
                    self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                    self.assertIn(expected, result.stdout)
                    self.assertEqual(target.read_text(), text)
        for example in ("Use `<pre>` in the publishing example.", "```html\n<textarea>\n<!--\n````"):
            with self.subTest(example=example):
                target.write_text(original.replace("## Context controls", f"{example}\n\n## Context controls"))
                result = self.context_capture(payload)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

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
        product = self.context_record("product-context", "context/products/example/overview.md",
                                      "[Company](../../company/overview.md)")
        original = product.read_text()
        for parent in ("none", "[Missing](../../context/missing.md)", "[Readme](../../context/README.md)",
                       "[Template](../../templates/company-context.md)",
                       "[External](https://example.com/company.md)"):
            with self.subTest(parent=parent):
                product.write_text(original.replace("[Company](../../company/overview.md)", parent))
                self.assertTrue(any("Parent context" in error for error in pm.check(self.root)))
        product.write_text(original)
        company.write_text(company.read_text().replace("| Parent context | none |", "| Parent context | [Self](overview.md) |"))
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
        target.rename(self.work / "workspace/company.md")
        self.assertTrue(any("canonical entity overview path" in error for error in pm.check(self.root)))

    def test_context_can_wait_across_sessions_with_explicit_gaps(self):
        target = self.context_record()
        text = target.read_text().replace("| State | active |", "| State | waiting |")
        text = text.replace("| Waiting on | none |", "| Waiting on | Fixture PM's company goals. |")
        text = text.replace("| Resume when | none |", "| Resume when | Fixture PM supplies the goals. |")
        target.write_text(text)
        self.assertEqual(pm.check(self.root), [])

    def context_capture(self, payload, *args):
        return subprocess.run(
            [sys.executable, "-B", str(self.root / "tools/pm.py"), "route-context", *args],
            input=json.dumps(payload), text=True, capture_output=True, cwd=self.work,
        )

    def test_capture_routes_mixed_sources_and_writes_only_the_requested_brief(self):
        stamp = date.today().isoformat()
        exclusion = "We will not enter the data centre business or create or own LLMs."
        rental = "We will rent capacity as required and use existing models."
        product_detail = "Example offers branch reporting."
        data = {
            "sources": [
                {"reference": "Fictional strategy, section 3", "date": "undated",
                 "coverage": "read", "checked_on": stamp},
                {"reference": "Fictional appendix", "date": "unknown", "coverage": "unavailable"},
            ],
            "entries": [
                {"scope": "company", "topic": "constraints", "source": 1, "location": "Section 3",
                 "quote": exclusion},
                {"scope": "product", "product": "example", "topic": "offer", "source": 1,
                 "location": "Section 3", "quote": product_detail},
                {"scope": "company", "topic": "constraints", "source": 1, "location": "Section 3",
                 "quote": rental},
                {"scope": "delivery", "source": 1, "location": "Section 4",
                 "quote": "Validate each branch ID."},
            ],
        }
        before = set(pm.inventory(self.work))
        preview = self.context_capture(data)
        self.assertEqual(preview.returncode, 0, preview.stdout + preview.stderr)
        plan = json.loads(preview.stdout)
        self.assertEqual([row["destination"] for row in plan["entries"]],
                         ["context/company/overview.md", "context/products/example/overview.md", "context/company/overview.md", None])
        self.assertEqual([row["coverage"] for row in plan["sources"]], ["read", "unavailable"])
        self.assertEqual(set(pm.inventory(self.work)), before)

        def write(destination):
            result = self.context_capture(data, "--write", destination)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return json.loads(result.stdout)["written"]

        self.assertEqual(write("context/company/overview.md"), "context/company/overview.md")
        company = self.work / "context/company/overview.md"
        company_text = company.read_text()
        constraints = records.section(company_text, "Constraints and open questions")
        self.assertIn(exclusion, constraints)
        self.assertIn(rental, constraints)
        self.assertNotIn(product_detail, company_text)
        self.assertEqual(set(pm.inventory(self.work)) - before, {company})
        self.assertIsNone(write("context/company/overview.md"))
        self.assertEqual(company.read_text(), company_text)

        self.assertEqual(write("context/products/example/overview.md"), "context/products/example/overview.md")
        product = self.work / "context/products/example/overview.md"
        self.assertIn(product_detail, records.section(product.read_text(), "The product"))
        self.assertNotIn(exclusion, product.read_text())
        self.assertEqual(company.read_text(), company_text)
        self.assertEqual(set(pm.inventory(self.work)) - before, {company, product})
        self.assertEqual(pm.check(self.root), [])

    def test_capture_previews_and_reuses_a_custom_section(self):
        target = self.context_record()
        original = target.read_bytes()
        heading = "UK rollout baseline"
        lead = "Consult when comparing UK adoption before and after rollout."
        quote = "The company reported 2,000 active UK merchants before rollout."
        payload = {
            "sources": [{"reference": "Fictional UK rollout announcement", "date": "undated",
                         "coverage": "read", "checked_on": date.today().isoformat(), "text": quote}],
            "entries": [{"scope": "company", "heading": heading, "lead": lead,
                         "source": 1, "location": "Paragraph 1", "quote": quote}],
        }
        destination = target.relative_to(self.work).as_posix()
        entry = payload["entries"][0]
        for changes, message in (({"heading": "sources"}, "reserved context metadata"),
                                 ({"lead": "- Fact: Invalid as a lead."}, "short prose lead")):
            with self.subTest(changes=changes):
                result = self.context_capture(dict(payload, entries=[{**entry, **changes}]), "--write", destination)
                self.assertEqual(result.returncode, 1, result.stdout)
                self.assertIn(message, result.stdout)
                self.assertEqual(target.read_bytes(), original)
        entry.pop("lead")
        result = self.context_capture(payload)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("Give UK rollout baseline a short lead", result.stdout)
        entry["lead"] = lead

        result = self.context_capture(payload)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        preview = json.loads(result.stdout)["entries"][0]
        self.assertEqual((preview["section"], preview["section_lead"], preview["section_action"]),
                         (heading, lead, "create"))
        self.assertEqual(target.read_bytes(), original)

        result = self.context_capture(payload, "--write", destination)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)["written"], destination)
        captured = target.read_text()
        self.assertEqual(records.split_context_lead(records.section(captured, heading))[0], lead)
        self.assertIn(quote, records.section(captured, heading))
        self.assertIsNone(records.split_context_lead(records.section(captured, "Customers and markets"))[0])
        self.assertEqual(pm.check(self.root), [])

        entry.pop("lead")
        result = self.context_capture(payload, "--write", destination)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        replay = json.loads(result.stdout)
        self.assertEqual((replay["entries"][0]["section_action"], replay["entries"][0]["section_lead"]), ("reuse", lead))
        self.assertIsNone(replay["written"])
        self.assertEqual(target.read_text(), captured)

        entry["lead"] = "Consult when comparing active merchant counts for the UK pilot."
        result = self.context_capture(payload, "--write", destination)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        text = target.read_text()
        self.assertEqual(records.split_context_lead(records.section(text, heading))[0], entry["lead"])
        self.assertEqual(text.count(quote), 1)
        self.assertEqual(pm.check(self.root), [])

    def evaluate_real_world_context_capture(self, case_id):
        manifest = pm.ROOT / red_team_eval.SUITES["context-sections"]
        case = red_team_eval.load_manifest(manifest)["cases"][case_id]
        capture = case["capture"]
        sources = [
            {"reference": f"[{source['title']} (benchmark paraphrase)]({source['url']})",
             "date": source["date"], "checked_on": date.today().isoformat(), "coverage": "partial",
             "text": source["summary"]}
            for source in case["sources"]
        ]
        entries = [
            {**entry, "location": case["sources"][entry["source"] - 1]["location"],
             "quote": sources[entry["source"] - 1]["text"]}
            for entry in capture["entries"]
        ]
        payload = {"sources": sources, "entries": entries}
        destination = capture["destination"]
        target = self.work / destination
        if destination.startswith("context/products/"):
            records.create(self.root, "company-context", "context/company/overview.md")
        before = {path: path.read_bytes() for path in pm.inventory(self.work) if path.is_file()}

        preview = self.context_capture(payload)
        self.assertEqual(preview.returncode, 0, preview.stdout + preview.stderr)
        plan = json.loads(preview.stdout)
        self.assertEqual({path: path.read_bytes() for path in before}, before)
        self.assertFalse(target.exists())
        self.assertEqual(len(plan["entries"]), len(entries))
        self.assertTrue(all(row["verification"] == "supplied text" for row in plan["source_checks"]),
                        plan["source_checks"])
        proposed = {}
        for given, row in zip(entries, plan["entries"]):
            if given["scope"] == "detail":
                self.assertEqual(row["disposition"], "deferred")
                self.assertIsNone(row["destination"])
                continue
            self.assertEqual(row["destination"], destination)
            expected = given.get("heading") or records.CONTEXT_TOPICS[given["scope"]][given["topic"]]
            self.assertEqual(row["section"], expected)
            self.assertEqual(row["section_action"], "create")
            if "lead" in given:
                self.assertEqual(row["section_lead"], given["lead"])
            self.assertTrue(row["section_lead"])
            proposed[expected] = row["section_lead"]

        result = self.context_capture(payload, "--write", destination)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        text = target.read_text(encoding="utf-8")
        self.assertEqual(set(pm.inventory(self.work)) - before.keys(), {target})
        self.assertEqual({path: path.read_bytes() for path in before}, before)
        found, errors = records.table(text, "Sources", records.SOURCE_COLUMNS)
        self.assertEqual(errors, [])
        references = {reference: (identifier, published) for identifier, reference, published, _ in found}
        self.assertEqual(references.keys(), {
            sources[row["source"] - 1]["reference"] for row in plan["entries"] if row["destination"]
        })
        for row in plan["entries"]:
            if row["destination"] is None:
                self.assertNotIn(row["quote"], unescape(text))
                continue
            heading = row["section"]
            lead, body = records.split_context_lead(records.section(text, heading))
            source = sources[row["source"] - 1]
            identifier, published = references[source["reference"]]
            self.assertEqual(published, source["date"])
            self.assertEqual(lead, proposed[heading])
            self.assertIn(f"[{identifier}] ({row['location']})\n  > {row['quote']}", unescape(body))
        self.assertEqual(pm.check(self.root), [])

        replay = self.context_capture(payload, "--write", destination)
        self.assertEqual(replay.returncode, 0, replay.stdout + replay.stderr)
        replay_plan = json.loads(replay.stdout)
        self.assertIsNone(replay_plan["written"])
        self.assertTrue(all(row["section_action"] == "reuse" for row in replay_plan["entries"] if row["destination"]))

        wrong_source = {**payload, "entries": [{**entries[0], "source": 2}, *entries[1:]]}
        rejected = self.context_capture(wrong_source, "--write", destination)
        self.assertEqual(rejected.returncode, 1, rejected.stdout + rejected.stderr)
        self.assertIn("differs from the supplied text", rejected.stdout)
        self.assertEqual(target.read_text(encoding="utf-8"), text)

    def test_real_world_context_shopify_annual_gmv(self):
        self.evaluate_real_world_context_capture("shopify-annual-gmv")

    def test_real_world_context_gitlab_renewal(self):
        self.evaluate_real_world_context_capture("gitlab-premium-renewal")

    def test_real_world_context_apple_storefronts(self):
        self.evaluate_real_world_context_capture("apple-storefront-purchase-links")

    def test_real_world_context_stripe_versions(self):
        self.evaluate_real_world_context_capture("stripe-billing-period-versions")

    def test_capture_keeps_open_questions_and_resolves_only_the_addressed_question(self):
        company = self.context_record()
        prior = company.read_text()
        question = "Who approves capacity purchases?"
        other = "Who owns supplier reviews?"
        questions = {"sources": [], "entries": [
            {"scope": "company", "topic": "operations", "question": item}
            for item in (question, other)
        ]}
        result = self.context_capture(questions, "--write", "context/company/overview.md")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        text = company.read_text()
        self.assertIn(f"- Unknown: {question}", text)
        self.assertIn(f"- Unknown: {other}", text)
        self.assertEqual(records.work_state(text)[0]["ID"], records.work_state(prior)[0]["ID"])
        self.assertEqual(records.section(text, "Context controls"), records.section(prior, "Context controls"))

        answer = "The procurement lead approves capacity purchases."
        resolved = {
            "sources": [{"reference": "Fictional procurement notes", "date": "undated",
                         "coverage": "partial", "checked_on": date.today().isoformat()}],
            "entries": [{"scope": "company", "topic": "operations", "source": 1,
                         "location": "Page 2", "quote": answer, "answers": question}],
        }
        result = self.context_capture(resolved, "--write", "context/company/overview.md")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        text = company.read_text()
        self.assertIn(answer, text)
        self.assertNotIn(question, text)
        self.assertIn(other, text)
        self.assertIn("Page 2", text)
        self.assertEqual(pm.check(self.root), [])

    def test_capture_rejects_companion_files_and_unavailable_citations(self):
        payload = {"sources": [], "entries": [
            {"scope": "company", "topic": "operations", "question": "Who owns procurement?"}
        ]}
        before = set(pm.inventory(self.work))
        for target in ("context/company-audit.md", "context/company-research.md",
                       "context/company-north-star.md", "context/../company.md"):
            with self.subTest(target=target):
                result = self.context_capture(payload, "--write", target)
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        payload["sources"] = [{"reference": "Unavailable source", "date": "unknown", "coverage": "unavailable"}]
        payload["entries"] = [{"scope": "company", "topic": "direction", "source": 1,
                               "location": "Page 1", "quote": "No source read."}]
        result = self.context_capture(payload, "--write", "context/company/overview.md")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("cannot supply an excerpt", result.stdout)
        self.assertEqual(set(pm.inventory(self.work)), before)

    def save_remit(self, remit):
        return subprocess.run(
            [sys.executable, "-B", str(self.root / "tools/pm.py"), "set-remit"],
            input=json.dumps(remit), text=True, capture_output=True, cwd=self.work,
        )

    def test_pm_remit_changes_relevance_without_moving_records(self):
        records.create(self.root, "goal", "workspace/goals/checkout.md")
        records.create(self.root, "company-context", "context/company/overview.md")
        remit = {
            "responsibilities": [
                {"subject": "product/checkout", "role": "owner", "goals": ["workspace/goals/checkout.md"],
                 "depends_on": ["product/billing"]},
                {"subject": "area/pricing", "role": "shared", "goals": [], "depends_on": []},
            ],
            "follow": ["topic/benchmarks"],
        }
        result = self.save_remit(remit)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        sources = [{"reference": "Fixture company update", "date": "undated", "coverage": "read",
                    "checked_on": date.today().isoformat()}]
        entries = [
            {"scope": "product", "product": "checkout", "topic": "offer", "quote": "Checkout supports invoicing."},
            {"scope": "product", "product": "billing", "quote": "Billing will retire its old API."},
            {"scope": "company", "topic": "direction", "quote": "The company will change its pricing.",
             "affects": {"product/checkout": "Checkout fees change."}},
            {"scope": "area", "subject": "area/pricing", "quote": "Pricing reviews occur quarterly.",
             "record": {"path": "context/company/pricing-review.md", "parent": "context/company/overview.md",
                        "basis": "maintained-reference", "trigger": "Finance publishes a price change.",
                        "reason": "Track the recurring reviews."}},
            {"scope": "reference", "subject": "topic/benchmarks", "quote": "New benchmarks are available."},
            {"scope": "product", "product": "search", "quote": "Search released saved filters."},
        ]
        payload = {"sources": sources, "entries": [dict(entry, source=1, location="Page 1") for entry in entries]}

        def preview():
            result = self.context_capture(payload)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return json.loads(result.stdout)["entries"]

        initial = preview()
        self.assertEqual([entry["relevance"] for entry in initial],
                         ["owned", "dependency", "affected", "shared", "following", "fyi"])
        self.assertEqual(initial[1]["responsibilities"][0]["goals"], ["workspace/goals/checkout.md"])
        self.assertEqual(initial[1]["disposition"], "source")
        self.assertEqual(initial[5]["disposition"], "source")
        remit["responsibilities"].pop(0)
        result = self.save_remit(remit)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        updated = preview()
        self.assertEqual([entry["relevance"] for entry in updated],
                         ["fyi", "fyi", "company", "shared", "following", "fyi"])
        self.assertEqual([entry["destination"] for entry in updated],
                         [entry["destination"] for entry in initial])
        self.assertEqual(pm.check(self.root), [])

    def test_context_capture_reuses_records_and_creates_only_an_authorised_note(self):
        goal = records.create(self.root, "goal", "workspace/goals/renewal.md")
        original = goal.read_text()
        source = {"reference": "Fixture supplier memo", "date": "undated", "coverage": "read",
                  "checked_on": date.today().isoformat()}
        entry = {"scope": "area", "subject": "area/vendor-risk", "source": 1, "location": "Section 2",
                 "quote": "We will review contracts every quarter."}
        records.create(self.root, "company-context", "context/company/overview.md")
        paths = "context/company/vendor-reviews.md", "workspace/goals/renewal.md"
        payload = {"sources": [source], "entries": [
            dict(entry, record={"path": path, "reason": "(Pilot phase) Track review obligations.", "parent": "context/company/overview.md",
                                "basis": "maintained-reference", "trigger": "The vendor renews a contract."}) for path in paths
        ]}
        before = set(pm.inventory(self.work))
        preview = self.context_capture(payload)
        self.assertEqual(preview.returncode, 0, preview.stdout + preview.stderr)
        self.assertEqual([item["disposition"] for item in json.loads(preview.stdout)["entries"]],
                         ["new-note", "existing"])
        self.assertEqual(set(pm.inventory(self.work)), before)
        result = self.context_capture(payload, "--write", paths[1])
        self.assertEqual(result.returncode, 1)
        self.assertEqual(goal.read_text(), original)
        result = self.context_capture(payload, "--write", paths[0])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        note = self.work / paths[0]
        self.assertIn(entry["quote"], note.read_text())
        self.assertEqual(set(pm.inventory(self.work)) - before, {note})
        preview = self.context_capture(payload)
        self.assertEqual(json.loads(preview.stdout)["entries"][0]["disposition"], "existing")
        result = self.context_capture(payload, "--write", paths[0])
        self.assertIsNone(json.loads(result.stdout)["written"])
        self.assertEqual(pm.check(self.root), [])

        # Older notes could include structured sections without a navigation lead.
        legacy_row = "| pilot | A limited programme. [S1] | Product | launch |"
        table = "## Vocabulary\n\n| Term | Meaning | Owner | Avoid |\n| --- | --- | --- | --- |\n" + legacy_row
        note.write_text(note.read_text().replace("## Context controls", f"{table}\n\n## Context controls"))
        self.assertEqual(pm.check(self.root), [])
        glossary = {"sources": [source], "entries": [dict(
            payload["entries"][0], heading="Vocabulary", quote="A workspace is the access boundary.",
            term={"name": "workspace", "owner": "Product", "avoid": "account"},
        )]}
        for args in ((), ("--write", paths[0])):
            result = self.context_capture(glossary, *args)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(json.loads(result.stdout)["entries"][0]["section_action"], "reuse")
        lead, body = records.split_context_lead(records.section(note.read_text(), "Vocabulary"))
        self.assertIn("Consult when", lead)
        self.assertIn(legacy_row, body)
        self.assertIn("| workspace | A workspace is the access boundary.", body)
        self.assertEqual(pm.check(self.root), [])

    def test_capture_records_a_product_implication_with_its_source(self):
        cite = {"reference": "Fixture Billing retirement announcement", "date": "undated",
                "coverage": "read", "checked_on": date.today().isoformat()}
        quote = "Billing will retire the legacy API in June."
        effect = "Checkout needs to migrate before the Billing API retirement."
        payload = {"sources": [cite], "entries": [
            {"scope": "product", "product": "billing", "source": 1, "location": "Announcement", "quote": quote},
            {"scope": "product", "product": "checkout", "topic": "ownership", "source": 1,
             "location": "Announcement", "quote": quote, "interpretation": effect},
        ]}
        result = self.context_capture(payload, "--write", "context/products/checkout/overview.md")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        context = self.work / "context/products/checkout/overview.md"
        text = context.read_text()
        self.assertIn(f"- Interpretation: {effect} [S1] (Announcement)", text)
        self.assertIn(f"  > {quote}", text)
        self.assertIn(cite["reference"], text)
        self.assertFalse((self.work / "context/products/billing").exists())
        self.assertEqual(pm.check(self.root), [])

    def test_lean_context_keeps_optional_sections_out_and_accepts_event_review(self):
        company = self.context_record()
        text = company.read_text()
        names = set(re.findall(r"^## (.+)$", text, re.M))
        for name in names - records.CONTEXT_METADATA - {"Constraints and open questions"}:
            text = re.sub(rf"^## {re.escape(name)}\n.*?(?=^## |\Z)", "", text, count=1, flags=re.M | re.S)
        text = re.sub(r"\| Review by \| .* \|", "| Review by | event-driven |", text)
        company.write_text(text)
        payload = {"sources": [], "entries": [
            {"scope": "company", "topic": "constraints", "question": "Who owns the pricing exception?"}
        ]}
        result = self.context_capture(payload, "--write", "context/company/overview.md")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Who owns the pricing exception?", company.read_text())
        lead, _ = records.split_context_lead(records.section(company.read_text(), "Constraints and open questions"))
        self.assertEqual(lead, records.CONTEXT_LEADS["Constraints and open questions"])
        self.assertEqual(set(re.findall(r"^## (.+)$", company.read_text(), re.M)),
                         records.CONTEXT_METADATA | {"Constraints and open questions"})
        self.assertEqual(pm.check(self.root), [])
        company.write_text(company.read_text().replace("| State | active |", "| State | complete |"))
        self.assertTrue(any("complete context needs" in error for error in pm.check(self.root)))

    def test_capture_keeps_legacy_product_routes_without_adding_duplicate_sections(self):
        target = records.create(self.root, "product-context", "context/products/example/overview.md")
        target.write_text(target.read_text().replace("## The product", "## Current offer"))
        stamp = date.today().isoformat()
        payload = {
            "sources": [{"reference": "Fixture offer summary", "date": "undated",
                         "checked_on": stamp, "coverage": "read"}],
            "entries": [{"scope": "product", "product": "example", "topic": "offer",
                         "source": 1, "location": "Page 1", "quote": "It supports branch reporting."}],
        }
        result = self.context_capture(payload, "--write", "context/products/example/overview.md")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        text = target.read_text()
        self.assertIn("It supports branch reporting.", records.section(text, "Current offer"))
        self.assertIsNone(records.section(text, "The product"))
        self.assertEqual(pm.check(self.root), [])

    def test_capture_routes_structured_context_across_company_product_and_initiative(self):
        stamp = date.today().isoformat()
        paths = ("context/company/overview.md", "context/products/example/overview.md",
                 "context/products/example/initiatives/renewals/overview.md")
        person = "Fixture PM"
        payload = {
            "sources": [{"reference": "Fixture approved decisions", "date": stamp,
                         "checked_on": stamp, "coverage": "read"}],
            "entries": [
                {"scope": "company", "topic": "data-boundaries", "rule": "Use approved usage summaries.",
                 "quote": "We permit approved usage summaries for planning."},
                {"scope": "product", "product": "example", "topic": "vocabulary",
                 "term": {"name": "workspace", "owner": "Product", "avoid": "account"},
                 "quote": "A workspace is the access boundary."},
                {"scope": "initiative", "product": "example", "initiative": "renewals", "topic": "decisions",
                 "decision": {"question": "How do users authenticate?", "scope": "Renewal pilot", "person": person,
                              "date": stamp, "next_step": "Brief the pilot team."},
                 "quote": "Use existing sessions because renewal needs no new login."},
                {"scope": "initiative", "product": "example", "initiative": "renewals", "topic": "examples",
                 "quote": "Pilot instructions use the approved renewal wording."},
            ],
        }
        payload["entries"] = [dict(entry, source=1, location="Page 1") for entry in payload["entries"]]
        for path in paths:
            before = set(pm.inventory(self.work))
            result = self.context_capture(payload, "--write", path)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(set(pm.inventory(self.work)) - before, {self.work / path})
        company, product, initiative = (self.work / path for path in paths)
        self.assertIn("- Rule: Use approved usage summaries.", company.read_text())
        self.assertIn("| workspace | A workspace is the access boundary.", product.read_text())
        self.assertIsNone(records.section(product.read_text(), "The users"))
        self.assertIn("[Product context](../../overview.md)", initiative.read_text())
        decisions = records.section(initiative.read_text(), "Decisions already closed")
        self.assertIn(f"| How do users authenticate? | Renewal pilot | {person}, {stamp} |", decisions)
        self.assertIn("Use existing sessions because renewal needs no new login. [S1]", decisions)
        self.assertIn("| Brief the pilot team. |", decisions)
        self.assertIn("- Example: Source excerpt [S1]", initiative.read_text())
        self.assertEqual(pm.check(self.root), [])

        original = initiative.read_text()
        invalid = original.replace("| Brief the pilot team. |", "|  |")
        initiative.write_text(invalid)
        self.assertTrue(any("need every field" in error for error in pm.check(self.root)))
        initiative.write_text(original.replace("[Product context](../../overview.md)", "[Company](../../../../company/overview.md)"))
        self.assertTrue(any("same product" in error for error in pm.check(self.root)))
        initiative.write_text(original)
        payload["entries"][2]["decision"].pop("next_step")
        result = self.context_capture(payload, "--write", paths[2])
        self.assertEqual(result.returncode, 1)
        self.assertEqual(initiative.read_text(), original)

    def test_invalid_pm_remit_keeps_the_previous_profile(self):
        blank = {"responsibilities": [], "follow": []}
        result = self.save_remit(blank)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        target = self.work / "context/pm/context.md"
        before = target.read_bytes()
        blank["responsibilities"] = [
            {"subject": "area/pricing", "role": "owner", "goals": ["context/missing.md"], "depends_on": []}
        ]
        result = self.save_remit(blank)
        self.assertEqual(result.returncode, 1)
        self.assertIn("has no private record", result.stdout)
        self.assertEqual(target.read_bytes(), before)

    def run_hook(self, payload):
        return subprocess.run(
            [sys.executable, "-B", str(self.root / "tools/hook.py")],
            input=payload, text=True, capture_output=True, cwd=self.root,
        )


if __name__ == "__main__":
    unittest.main()
