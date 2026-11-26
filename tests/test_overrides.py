"""Exercise protected PM sessions, shared rules, updates and reporting."""

import itertools
import json
import os
import shlex
import shutil
import subprocess
import sys
import unittest
from unittest.mock import patch

import test_pm
from onboarding_fixtures import reviewed_setup
import hook
import overrides
import pm


class OverrideTests(unittest.TestCase):
    setUp = reviewed_setup

    def cli(self, *args):
        result = subprocess.run([sys.executable, str(self.root / "tools/pm.py"), *args],
                                cwd=self.root, capture_output=True, text=True, check=True)
        return json.loads(result.stdout)

    def registered_hook(self, client, cwd, payload, bound=None):
        config_path = ".codex/hooks.json" if client == "codex" else ".claude/settings.json"
        config = json.loads((self.root / config_path).read_text())
        handler = config["hooks"][payload["hook_event_name"]][0]["hooks"][0]
        command = ([handler["command"], *handler["args"]] if "args" in handler
                   else ["sh", "-c", handler["command"]])
        env = os.environ.copy()
        env.pop("PM_HUB_PROTECTED_ROOT", None)
        if bound is not None:
            env["PM_HUB_PROTECTED_ROOT"] = str(bound)
        return subprocess.run(command, cwd=cwd, env=env, input=json.dumps(payload), capture_output=True, text=True)

    def test_coverage_through_installed_cli(self):
        before = self.work / overrides.FILE
        self.assertFalse(before.exists())
        self.cli("override", "set", "weekly-review-order", "--scope", "Weekly reviews",
                 "--behavior", "Start with the single recommended check. Add a decision table.")
        self.assertEqual(self.cli("align")["covered_overrides"], [])
        partial = overrides.guidance(self.work)
        self.assertIn("Add a decision table.", partial)
        # A later core release supplies every clause. The PM edits nothing.
        core = self.root / overrides.DEFAULTS_FILE
        core.write_text(json.dumps({"weekly-review-order": {
            "scope": "Weekly reviews", "behavior": "Start with the single recommended check. Add a decision table."}}))
        prior = overrides.guidance(self.work)
        self.assertEqual(self.cli("align", "--status")["covered_overrides"], ["weekly-review-order"])
        self.assertEqual(len(self.cli("override", "list")["rules"]), 1)
        self.assertEqual(self.cli("align")["covered_overrides"], ["weekly-review-order"])
        self.assertEqual(overrides.guidance(self.work), prior)
        self.assertEqual(self.cli("align")["covered_overrides"], [])
        self.assertEqual(len(self.cli("override", "list")["retired"]), 1)

    def test_narrow_scope_preserves_core_elsewhere(self):
        self.cli("override", "set", "weekly-review-order", "--scope", "Quarter-end weekly reviews",
                 "--behavior", "Start with pending decisions.")
        rules = self.cli("override", "list")["effective"]["weekly-review-order"]
        self.assertEqual([rule["scope"] for rule in rules], ["Weekly reviews", "Quarter-end weekly reviews"])
        self.assertEqual(self.cli("align")["covered_overrides"], [])

    def test_revise_specific_scope_via_independent_local_id(self):
        workflow = "weekly-review-order"
        base = "Weekly reviews"
        exception = "Quarter-end weekly reviews"
        self.cli("override", "set", "my-order", "--target", workflow, "--scope", base,
                 "--behavior", "Start with decisions.")
        self.cli("override", "set", "quarter-close", "--target", workflow, "--scope", exception,
                 "--behavior", "Start with revenue.", "--steps", "Show refunds separately.")
        self.cli("override", "set", "quarter-close", "--scope", exception,
                 "--behavior", "Start with invoices.", "--steps", "Include paid invoices only.")
        shown = self.cli("override", "show", "quarter-close")
        self.assertEqual(shown["target"], workflow)
        self.assertEqual(shown["effective"], [
            {"scope": base, "behavior": "Start with decisions."},
            {"scope": exception, "behavior": "Start with invoices.\nInclude paid invoices only."}])
        guide = self.cli("action", "context", "meeting", "summarize")["workflow_guidance"]
        self.assertNotIn("Start with the single recommended check.", guide)
        self.assertIn("Start with invoices.", guide)
        self.assertIn(f"override show {workflow}", guide)
        self.assertIn(guide, hook.reply_preferences(self.root)["hookSpecificOutput"]["additionalContext"])
        cwd = self.work / "workspace"
        payload = {"hook_event_name": "UserPromptSubmit", "cwd": str(cwd), "prompt": "Prepare the quarter-end weekly review."}
        for client in ("claude", "codex"):
            with self.subTest(client=client):
                reply = self.registered_hook(client, cwd, payload)
                self.assertEqual(reply.returncode, 0, reply.stderr)
                self.assertIn(guide, json.loads(reply.stdout)["hookSpecificOutput"]["additionalContext"])
        parse = pm.build_parser().parse_args
        for cli, error in (
                (["set", "my-order", "--scope", exception, "--behavior", "Change only this."], "--move-scope"),
                (["set", "replacement", "--target", workflow, "--scope", exception,
                  "--behavior", "Change only this."], "Revise quarter-close")):
            with self.assertRaisesRegex(ValueError, error):
                overrides.run(self.root, parse(["override", *cli]))
        self.assertEqual(self.cli("override", "show", workflow)["effective"], shown["effective"])
        self.cli("override", "set", "quarter-close", "--scope", "Board reviews", "--move-scope",
                 "--behavior", "Skip the invoice review.")
        self.assertEqual(self.cli("override", "remove", "quarter-close")["effective"], shown["effective"][:1])
        self.assertEqual(self.cli("override", "remove", "my-order")["effective"],
                         [{"scope": base, "behavior": "Start with the single recommended check."}])

    def test_company_priority_and_update_preserve_behavior_for_overlapping_scopes(self):
        workflow = "weekly-review-order"
        base = {"scope": "Weekly reviews", "behavior": "Start with refunds."}
        close = {"scope": "Quarter-end weekly reviews", "behavior": "Start with forecast."}
        unrelated = {"scope": "Weekly reviews", "behavior": "End with named owners."}
        core = self.root / overrides.DEFAULTS_FILE
        core.write_text(json.dumps({"upstream-order": dict(base, target=workflow), "owners": unrelated}))
        self.cli("override", "set", "my-order", "--target", workflow, "--scope", base["scope"],
                 "--behavior", base["behavior"])
        self.cli("override", "set", "close", "--target", workflow, "--scope", close["scope"],
                 "--behavior", close["behavior"])
        company = {"company-order": dict(base, target=workflow, behavior="Open with ARR."),
                   "company-close": dict(close, target=workflow, behavior="Open with expenses.")}
        with patch.object(overrides.company_source, "inspection", return_value=({"rules": company}, None)):
            _, state = overrides.read(self.work)
            self.assertEqual(overrides.effective_rules(self.work, state)[workflow], [base, close])
            self.assertIn(unrelated["behavior"], overrides.guidance(self.work))
            self.assertEqual(overrides.reconcile(self.work, "2", True), [])
            self.assertEqual(set(overrides.read(self.work)[1]["rules"]), {"my-order", "close"})
        # Even with no company rule, retiring just the broad personal rule
        # could reverse precedence when two personal scopes are applicable.
        self.assertEqual(overrides.reconcile(self.work, "2", True), [])
        core.write_text(json.dumps({"upstream-order": dict(base, target=workflow),
                                   "upstream-close": dict(close, target=workflow), "owners": unrelated}))
        self.assertEqual(set(overrides.reconcile(self.work, "3", True)), {"my-order", "close"})
        self.assertEqual(overrides.effective_rules(self.work, overrides.read(self.work)[1])[workflow], [base, close])
        self.assertEqual(len(overrides.read(self.work)[1]["retired"]), 2)

    def test_guidance_identifies_company_core_and_personal_scope_authority(self):
        target = "weekly-review-order"
        self.cli("override", "set", "my-board", "--target", target, "--scope", "Board prep",
                 "--behavior", "Use runway first.")
        company = {"company-close": {"scope": "Quarter close", "target": target, "behavior": "Use bookings first."}}
        with patch.object(overrides.company_source, "inspection", return_value=({"rules": company}, None)):
            shown = overrides.run(self.root, pm.build_parser().parse_args(["override", "show", target]))
            self.assertEqual(shown["sources"], {"Weekly reviews": "core", "Quarter close": "company", "Board prep": "personal"})
            guide = overrides.guidance(self.work)
            for entry in shown["effective"]:
                self.assertIn(json.dumps(dict(entry, source=shown["sources"][entry["scope"]])), guide)

    def test_show_distinguishes_target_from_personal_id_of_another_habit(self):
        self.cli("override", "set", "weekly-review-order", "--target", "calendar-order", "--scope",
                 "Calendar review", "--behavior", "Order by time zone.")
        shown = self.cli("override", "show", "weekly-review-order")
        self.assertEqual(shown["target"], "weekly-review-order")
        self.assertEqual(shown["also_personal_target"], "calendar-order")
        by_id = self.cli("override", "show", "weekly-review-order", "--personal-id")
        self.assertEqual(by_id["effective"], [{"scope": "Calendar review", "behavior": "Order by time zone."}])
        self.assertEqual(by_id["target"], "calendar-order")
        self.assertEqual(self.cli("override", "remove", "weekly-review-order")["effective"], [])
        self.assertEqual(self.cli("override", "show", "weekly-review-order")["target"], "weekly-review-order")

    def test_retirement_preserves_every_two_scope_three_source_combination(self):
        scopes = ("Leadership reviews", "Quarter close")
        # These can each apply alone, or coincide with either scope the more specific one.
        applicable = [(scopes[0],), (scopes[1],), scopes, scopes[::-1]]

        def outcome(sources, matching):
            for rules in reversed(sources):
                for scope in matching:
                    for row in rules.values():
                        if row["scope"] == scope:
                            return row["behavior"]
            return None

        for values in itertools.product((None, "Discuss revenue.", "Discuss decisions."), repeat=6):
            sources = []
            for i, layer in enumerate(("core", "company", "personal")):
                rules = {}
                for j, scope in enumerate(scopes):
                    behavior = values[i * 2 + j]
                    if behavior:
                        rules[f"{layer}-{j}"] = {"target": "review-topic", "scope": scope, "behavior": behavior}
                sources.append(rules)
            core, company, personal = sources
            retired = overrides.covered_rules(core, company, personal)
            # A matching company row alone never establishes adoption by core.
            for key in retired:
                self.assertIn(personal[key], core.values())
            remaining = {key: rule for key, rule in personal.items() if key not in retired}
            for matching in applicable:
                self.assertEqual(outcome(sources, matching), outcome([core, company, remaining], matching),
                                 (values, matching, retired))
            eligible = [key for key, rule in personal.items() if rule in core.values()]
            for count in range(len(retired) + 1, len(eligible) + 1):
                for subset in itertools.combinations(eligible, count):
                    alternative = {key: rule for key, rule in personal.items() if key not in subset}
                    self.assertTrue(any(outcome(sources, matching) != outcome([core, company, alternative], matching)
                                        for matching in applicable), (values, subset, retired))

    def test_named_procedure_reaches_guided_skills_and_survives_partial_adoption(self):
        name = "friday-handoff"
        scope = "Friday handoff for a PM's weekly review"
        summary = "Draft my Friday handoff."
        steps = "List decisions first.\nName the owner of each blocker.\nLeave the update as a draft."
        self.cli("override", "set", name, "--scope", scope, "--behavior", summary, "--steps", steps)
        handoff = self.cli("action", "workspace", "workflow", "open", name)
        self.assertEqual(handoff["arguments"], [name])
        guide = handoff["workflow_guidance"]
        self.assertIn("override show friday-handoff", guide)
        self.assertNotIn(steps, guide)
        self.assertIn(guide, hook.reply_preferences(self.root)["hookSpecificOutput"]["additionalContext"])
        self.assertEqual(self.cli("action", "context", "meeting", "summarize")["workflow_guidance"], guide)
        rule = self.cli("override", "show", name)["effective"][-1]
        self.assertEqual(rule["behavior"], summary + "\n" + steps)
        path = self.root / overrides.DEFAULTS_FILE
        base = overrides.defaults(self.root)
        base[name] = {"scope": scope, "behavior": summary}
        path.write_text(json.dumps(base))
        self.assertEqual(self.cli("align")["covered_overrides"], [])
        base[name] = rule
        path.write_text(json.dumps(base))
        self.assertEqual(self.cli("align")["covered_overrides"], [name])
        self.assertEqual(self.cli("override", "show", name)["effective"], [rule])

    def test_removing_one_working_habit_cancels_its_report_and_keeps_other_scopes(self):
        self.cli("override", "set", "meeting-format", "--scope", "Meeting summaries", "--behavior", "Open with decisions.")
        self.cli("override", "set", "exec-meeting-format", "--scope", "Leadership meetings", "--behavior", "Open with risks.")
        self.cli("override", "reporting", "on")
        args = pm.build_parser().parse_args(["override", "report", "exec-meeting-format", "--title", "Summary order",
                                            "--body", "Support choosing the first section.", "--approved"])
        with patch.object(overrides, "gh", side_effect=ValueError("offline")):
            self.assertIn("report_pending", overrides.run(self.root, args))
        self.assertEqual(self.cli("override", "remove", "exec-meeting-format")["effective"], [])
        self.assertIsNone(self.cli("override", "remove", "exec-meeting-format")["removed"])
        state = self.cli("override", "list")
        self.assertEqual(state["pending"], [])
        self.assertIn("meeting-format", state["rules"])
        self.assertNotIn("exec-meeting-format", state["effective"])

    def test_symlink_move_notebook_and_shell(self):
        redirect = self.work / "linked.md"
        redirect.symlink_to(self.root / "AGENTS.md")
        for tool, data in [
                ("Write", {"file_path": str(redirect)}),
                ("NotebookEdit", {"notebook_path": str(self.root / "book.ipynb")}),
                ("apply_patch", {"input": "*** Update File: studio/example.md\n*** Move to: NEW.md"}),
                ("Bash", {"command": "python script.py"}),
                ("exec_command", {"cmd": "python script.py"})]:
            decision = hook.edit_guard(self.root, self.root, {"tool_name": tool, "tool_input": data})
            self.assertEqual(decision["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertFalse(hook.edit_guard(self.root, self.root, {"tool_name": "Write",
                                         "tool_input": {"file_path": str(self.work / "README.md")}}))

    def test_private_reporting_and_retries(self):
        parse = pm.build_parser().parse_args
        def run(*args):
            return overrides.run(self.root, parse(["override", *args]))
        run("set", "secret-initiative", "--scope", "Private project", "--behavior", "Private strategy")
        send = ("report", "secret-initiative", "--title", "Public request", "--body", "Public detail", "--approved")
        with self.assertRaisesRegex(ValueError, "Enable"):
            run(*send)
        run("reporting", "on")
        with self.assertRaisesRegex(ValueError, "Approve"):
            run(*send[:-1])
        issue = {"state": "open", "title": "Another title", "number": 3,
                 "body": "", "html_url": "https://github.com/nathandmello/pm-hub/issues/3"}
        receipt = issue["html_url"] + "#issuecomment-45"
        calls = []
        comments = []
        def github(*args):
            calls.append(args)
            if args[1] == "repositories/1463535158":
                return json.dumps({"id": 1463535158, "full_name": "nathandmello/pm-hub", "owner": "nathandmello"})
            if "issues?" in args[-1]:
                return json.dumps(issue)
            if "comments?" in args[-1]:
                return "\n".join(map(json.dumps, comments))
            if "-f" in args:
                payload = next(arg[5:] for arg in args if arg.startswith("body="))
                comments.append({"body": payload, "html_url": receipt})
                return receipt
            self.fail(args)
        with patch.object(overrides, "gh", github):
            self.assertEqual(run(*send, "--issue", "3"), {"url": receipt})
            count = len(calls)
            self.assertEqual(run(*send, "--issue", "3"), {"url": receipt})
            self.assertEqual(len(calls), count)
            # Simulate a dropped response before the receipt reached local disk.
            path = self.work / overrides.FILE
            state = json.loads(path.read_text())
            state["reports"].clear()
            path.write_text(json.dumps(state))
            self.assertEqual(run(*send, "--issue", "3"), {"url": receipt})
        self.assertEqual(len(comments), 1)
        self.assertNotIn("Private", repr(calls))
        self.assertNotIn("secret-initiative", repr(calls))

    def test_known_request_can_create_and_failure_preserves_work(self):
        parse = pm.build_parser().parse_args
        overrides.run(self.root, parse(["override", "reporting", "on"]))
        args = parse(["override", "set", "weekly-review-order", "--scope", "Weekly reviews",
                      "--behavior", "Put pending decisions first."])
        with patch.object(overrides, "gh", side_effect=ValueError("offline")):
            self.assertIn("report_pending", overrides.run(self.root, args))
        receipt = "https://github.com/nathandmello/pm-hub/issues/5"
        identity = json.dumps({"id": 1463535158, "full_name": "nathandmello/pm-hub", "owner": "nathandmello"})
        with patch.object(overrides, "gh", side_effect=[identity, "", receipt]) as api:
            self.assertEqual(overrides.run(self.root, parse(["override", "sync"]))["urls"], [receipt])
            self.assertIn("title=Configurable weekly review order", api.call_args.args)
        self.assertIn("Put pending decisions first.", hook.reply_preferences(self.root)["hookSpecificOutput"]["additionalContext"])

    def test_nested_client_start_migrates_before_building_each_launch_policy(self):
        if sys.platform != "darwin" and not sys.platform.startswith("linux"):
            self.skipTest("Protected launches target Linux and macOS")
        self.cli("override", "set", "close-order", "--scope", "Quarter close", "--behavior", "Review accruals first.")
        # Run the real launcher and align subprocess. Capture its final OS command;
        # the process-level sandbox assertion belongs to test_protected_child_process.
        inspect_launch = """
import json, os, sys
from pathlib import Path
from unittest.mock import patch
root, client = Path(sys.argv[1]), sys.argv[2]
sys.path.insert(0, str(root / "tools"))
import agent_session
with patch("shutil.which", side_effect=lambda tool: "/bin/" + tool), patch("os.execvpe") as handoff:
    agent_session.launch(root, client)
    tool, argv, env = handoff.call_args.args
    print(json.dumps([tool, argv, env["PM_HUB_PROTECTED_ROOT"], os.getcwd()]))
"""
        for legacy in ("workspace", "private"):
            for client in ("codex", "claude"):
                with self.subTest(legacy=legacy, client=client):
                    old = self.root / legacy
                    (self.work / overrides.FILE).rename(self.work / ".hub-overrides.json")
                    self.work.rename(old)
                    nested = old / "workspace" / "initiatives"
                    nested.mkdir(parents=True, exist_ok=True)
                    launched = subprocess.run([sys.executable, "-c", inspect_launch, str(self.root), client],
                                              cwd=nested, capture_output=True, text=True)
                    self.assertEqual(launched.returncode, 0, launched.stderr)
                    program, argv, bound, session_cwd = json.loads(launched.stdout.splitlines()[-1])
                    self.assertEqual((bound, session_cwd), (str(self.root), str(self.root)))
                    self.assertFalse(old.exists())
                    self.assertTrue((self.work / overrides.FILE).is_file())
                    if program == "bwrap":
                        approvals = str(self.work / ".oryx-approvals")
                        i = argv.index(approvals)
                        self.assertEqual(argv[i - 1:i + 2], ["--ro-bind", approvals, approvals])
                        ro = argv.index("--ro-bind")
                        self.assertEqual(argv[ro + 1:ro + 6], [str(self.root), str(self.root), "--bind", str(self.work), str(self.work)])
                    else:
                        self.assertEqual(program, "sandbox-exec")
                        self.assertIn(f'(deny file-write* (subpath {json.dumps(str(self.work / ".oryx-approvals"))}))', argv[2])
                        self.assertIn(f"(require-not (subpath {json.dumps(str(self.work))}))", argv[2])
                    if client == "codex":
                        self.assertIn(f'{json.dumps(str(self.work))}="write"', argv[-1])
                    current = self.work / nested.relative_to(old)
                    event = {"hook_event_name": "UserPromptSubmit", "cwd": str(current), "prompt": "Prepare quarter close."}
                    for pinned in (None, bound):
                        reply = self.registered_hook(client, current, event, pinned)
                        self.assertEqual(reply.returncode, 0, reply.stderr)
                        self.assertIn("Review accruals first.", json.loads(reply.stdout)["hookSpecificOutput"]["additionalContext"])
                    stale = self.registered_hook(client, current, dict(event, cwd=str(nested)), bound)
                    self.assertNotEqual(stale.returncode, 0)
                    self.assertIn("directory moved or is unavailable", stale.stderr)

    def test_both_hook_registrations_honor_the_launched_hub_and_reject_ambiguous_locations(self):
        self.cli("override", "set", "agenda", "--scope", "Planning", "--behavior", "Check support commitments.")
        # A PM keeps a sample Hub project under Studio. Its marker filenames
        # make discovery ambiguous unless the launcher has identified the outer Hub.
        sample = self.work / "workspace" / "samples" / "hub"
        for filename in ("playbook/release.json", "tools/hook.py"):
            (sample / filename).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(self.root / filename, sample / filename)
        event = {"hook_event_name": "UserPromptSubmit", "cwd": str(sample), "prompt": "Prepare for planning."}
        for client in ("codex", "claude"):
            with self.subTest(client=client):
                selected = self.registered_hook(client, sample, event, self.root)
                self.assertEqual(selected.returncode, 0, selected.stderr)
                self.assertIn("Check support commitments.", selected.stdout)
                ambiguous = self.registered_hook(client, sample, event)
                self.assertEqual(ambiguous.returncode, 2)
                self.assertIn("Cannot identify a single oryx checkout", ambiguous.stderr)
                external = self.registered_hook(client, self.root.parent, event, self.root)
                self.assertEqual(external.returncode, 2)
                self.assertIn("Cannot identify a single oryx checkout", external.stderr)
                external_event = self.registered_hook(client, sample, dict(event, cwd=str(self.root.parent)), self.root)
                self.assertNotEqual(external_event.returncode, 0)
                self.assertIn("inside this oryx checkout", external_event.stderr)

    def test_uninstalled_or_invalid_studio_cannot_supply_agent_instructions(self):
        self.cli("override", "set", "agenda", "--scope", "Planning", "--behavior", "Check support commitments.")
        event = {"hook_event_name": "UserPromptSubmit", "cwd": str(self.root), "prompt": "Prepare for planning."}

        def check_readers(*, installed=False, error=None):
            readers = [self.registered_hook(client, self.root, event) for client in ("codex", "claude")]
            readers.append(subprocess.run([sys.executable, str(self.root / "tools/pm.py"), "action", "context",
                                           "meeting", "summarize"], cwd=self.root, capture_output=True, text=True))
            if installed or error:
                readers.append(subprocess.run([sys.executable, str(self.root / "tools/pm.py"), "override", "list"],
                                              cwd=self.root, capture_output=True, text=True))
            for result in readers:
                if error:
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(error, result.stdout + result.stderr)
                else:
                    self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual("Check support commitments." in result.stdout, installed)

        check_readers(installed=True)
        self.work.rename(self.root / "fixture-data")
        check_readers()
        self.work.symlink_to(self.root / "fixture-data", target_is_directory=True)
        check_readers(error="expected its own local Git repository")
        self.work.unlink()
        self.work.mkdir()
        (self.work / overrides.FILE).parent.mkdir(parents=True)
        shutil.copyfile(self.root / "fixture-data" / overrides.FILE, self.work / overrides.FILE)
        check_readers(error="expected its own local Git repository")
        subprocess.run(["git", "init", "--quiet", str(self.work)], check=True)
        check_readers(error="init-workspace")
        (self.root / "private").mkdir()
        check_readers(error="Multiple PM repository roots")

    def test_protected_child_process(self):
        if sys.platform.startswith("linux"):
            if not shutil.which("bwrap") or subprocess.run(
                    ["bwrap", "--ro-bind", "/", "/", "true"], capture_output=True).returncode:
                self.skipTest("Bubblewrap namespaces unavailable")
        elif sys.platform != "darwin":
            self.skipTest("Protected PM sessions require Linux or macOS")
        # Check the OS boundary independently of environment markers or agent hooks.
        approvals = self.work / ".oryx-approvals"
        approvals.mkdir(exist_ok=True)
        receipt = approvals / "existing.json"
        receipt.write_text("PM reviewed this batch.")
        script = """from pathlib import Path
import errno
import os
os.environ.pop("PM_HUB_PROTECTED_ROOT", None)
draft = Path("studio/workspace/initiatives/draft.md")
draft.parent.mkdir(parents=True, exist_ok=True)
draft.write_text("Agent draft")
Path("studio/probe").touch()
for path in ("core-probe", "studio/.oryx-approvals/new.json", "studio/.oryx-approvals/existing.json"):
    try:
        Path(path).write_text("unreviewed edit")
    except OSError as exc:
        assert exc.errno in {errno.EACCES, errno.EPERM, errno.EROFS}
    else:
        raise AssertionError(f"{path} was writable")
try:
    Path("studio/.oryx-approvals").rename("studio/replaced-approvals")
except OSError as exc:
    assert exc.errno in {errno.EACCES, errno.EPERM, errno.EBUSY, errno.EROFS}
else:
    raise AssertionError("PM approval history could be replaced")
"""
        probe_command = [sys.executable, "-c", script]
        for client in ("codex", "claude"):
            with self.subTest(client=client):
                shim = self.root.parent / client
                shim.write_text("#!/bin/sh\nexec " + shlex.join(probe_command) + "\n")
                shim.chmod(0o755)
                result = subprocess.run([sys.executable, "tools/pm.py", "agent", client], cwd=self.root,
                                        env=dict(os.environ, PATH=str(shim.parent) + os.pathsep + os.environ["PATH"]),
                                        capture_output=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue((self.work / "probe").exists())
                (self.work / "probe").unlink()
                self.assertFalse((self.root / "core-probe").exists())
                self.assertEqual(receipt.read_text(), "PM reviewed this batch.")
                self.assertEqual((self.work / "workspace/initiatives/draft.md").read_text(), "Agent draft")
        # The PM's own process still has its original permissions.
        (self.root / "core-probe").touch()
