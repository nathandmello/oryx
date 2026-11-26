"""Local continuity uses only the PM's admitted native conversation."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from datetime import datetime, timezone
import errno
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import stat
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import agent_session
import journal_native
import session_journal as journal
import snapshots


class JournalTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name).resolve()
        self.root = self.base / "install"
        self.studio = self.root / "studio"
        self.studio.mkdir(parents=True)
        self.env = patch.dict(os.environ, XDG_STATE_HOME=str(self.base / "state"),
                              CLAUDE_CONFIG_DIR=str(self.base / "claude"), CODEX_HOME=str(self.base / "codex"))
        self.env.start()
        self.addCleanup(self.env.stop)
        self.clock = 1795654800.0
        timer = patch.object(journal.time, "time", side_effect=lambda: self.clock)
        timer.start()
        self.addCleanup(timer.stop)
        self.session = "abf38f20-b186-4721-bbfe-178576779572"

    def hook(self, event, client="codex", session=None, scope=None, **fields):
        payload = {"hook_event_name": event, "session_id": session or self.session, "cwd": str(self.root), **fields}
        self.assertIsNone(journal.capture(self.studio, client, payload, scope=scope))
        return payload

    def rows(self, client="codex", session=None):
        return journal.read_session(self.studio, client, session or self.session)["events"]

    def time_string(self):
        return datetime.fromtimestamp(self.clock, timezone.utc).isoformat()

    def append(self, path, row):
        with path.open("a") as stream:
            stream.write(json.dumps({"timestamp": self.time_string(), **row}) + "\n")

    def native_file(self, client):
        if client == "codex":
            path = self.base / "codex/sessions/2026/11/26" / ("rollout-2026-11-26T09-00-00-" + self.session + ".jsonl")
        else:
            path = self.base / "claude/projects/-installation" / (self.session + ".jsonl")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
        if client == "codex":
            self.append(path, {"type": "session_meta", "payload": {"id": self.session, "cwd": str(self.root)}})
        return path

    def test_default_permissions_location_and_snapshot(self):
        for client in journal.CLIENTS:
            self.hook("UserPromptSubmit", client, prompt="Excluded before consent")
        self.assertEqual(journal.status(self.studio)["retention_days"], 90)
        self.assertFalse(journal.off_record(self.studio, "codex", self.session))
        self.assertFalse((self.base / "state").exists())
        journal.configure(self.studio, enabled=True)
        self.hook("UserPromptSubmit", turn_id="t1", prompt="An admitted exchange.")
        path = journal.location(self.studio)
        for parent in (path, path.parent, path.parent.parent):
            self.assertEqual(stat.S_IMODE(parent.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE((path / "journal.sqlite3").stat().st_mode), 0o600)
        # Recovery archives the complete installation, including ignored files and .git.
        (self.root / ".git").mkdir()
        store = self.root / ".git/archive"
        store.mkdir()
        archive = store / "restore.tar.gz"
        snapshots.create(self.root, store, archive)
        with tarfile.open(archive) as saved:
            self.assertFalse(any("journal" in member.name for member in saved))
        other = self.base / "elsewhere/studio"
        other.mkdir(parents=True)
        self.assertNotEqual(journal.location(other), path)
        self.assertFalse(journal.status(other)["enabled"])
        (path / "journal.sqlite3").chmod(0o644)
        with self.assertRaises(ValueError):
            journal.status(self.studio)
        self.assertTrue(journal.off_record(self.studio, "codex", self.session))

    def test_reject_repo_symlink_and_hardlink_redirects(self):
        for state in (self.root, self.studio, self.root / ".git/backup"):
            with self.subTest(state=state), patch.dict(os.environ, XDG_STATE_HOME=str(state)), self.assertRaises(ValueError):
                journal.configure(self.studio, enabled=True)
        other = self.base / "other"
        other.mkdir()
        (other / ".git").mkdir()
        (other / ".git/HEAD").write_text("ref: refs/heads/main\n")
        with patch.dict(os.environ, XDG_STATE_HOME=str(other / "stash")), self.assertRaises(ValueError):
            journal.configure(self.studio, enabled=True)
        (self.base / "state").symlink_to(other, target_is_directory=True)
        with self.assertRaises(ValueError):
            journal.configure(self.studio, enabled=True)
        (self.base / "state").unlink()
        journal.configure(self.studio, enabled=True)
        os.link(journal.location(self.studio) / "journal.sqlite3", self.base / "second")
        with self.assertRaises(ValueError):
            journal.status(self.studio)

    def test_visible_idempotent_events_and_attribution(self):
        journal.configure(self.studio, enabled=True)
        for client in journal.CLIENTS:
            with self.subTest(client=client):
                for event in (dict(origin="tool"),dict(agent_id="delegate"),dict(isSidechain=True),dict(role="assistant")):
                    self.hook("UserPromptSubmit", client, prompt="Untrusted data", **event)
                self.hook("PreToolUse", client, tool_input={"prompt": "tool secret"})
                self.hook("UserPromptSubmit", client, turn_id="one", prompt="Compare the two timelines.", scope="product/alpha")
                self.hook("UserPromptSubmit", client, turn_id="one", prompt="Compare the two timelines.", scope="product/alpha")
                self.hook("Stop", client, turn_id="wrong", last_assistant_message="Other turn")
                self.hook("Stop", client, turn_id="one", agent_id="worker", last_assistant_message="Hidden worker")
                for _ in range(2):
                    self.hook("Stop", client, turn_id="one", last_assistant_message="The pilot comes first.",
                              tool_output="Not a reply", reasoning="Hidden thought")
                self.assertEqual([(r["role"],r["text"]) for r in self.rows(client)],
                                 [("human", "Compare the two timelines."),("assistant", "The pilot comes first.")])
        self.assertNotEqual(self.rows("claude")[0]["id"], self.rows("codex")[0]["id"])
        stored = (journal.location(self.studio) / "journal.sqlite3").read_bytes()
        for text in ("Untrusted data","tool secret","Hidden thought","Other turn","Hidden worker"):
            self.assertNotIn(text.encode(), stored)

    def test_off_record_without_logging_and_revoked_or_deleted_turns_cannot_recover(self):
        journal.set_off_record(self.studio, "codex", self.session, True)
        self.assertFalse(journal.status(self.studio)["enabled"])
        self.assertTrue(journal.off_record(self.studio, "codex", self.session))
        self.assertFalse(journal.off_record(self.studio, "claude", self.session))
        journal.configure(self.studio, enabled=True)
        self.hook("UserPromptSubmit", turn_id="off", prompt="Off record")
        journal.set_off_record(self.studio, "codex", self.session, False)
        self.hook("Stop", turn_id="off", last_assistant_message="Still excluded")
        self.assertEqual(self.rows(), [])
        for operation in ("pause", "disable", "delete", "expire"):
            with self.subTest(operation=operation):
                native = self.native_file("codex")
                self.hook("UserPromptSubmit", turn_id=operation, prompt="Visible " + operation, transcript_path=str(native))
                if operation == "pause":
                    journal.set_off_record(self.studio, "codex", self.session, True)
                    journal.set_off_record(self.studio, "codex", self.session, False)
                elif operation == "disable":
                    journal.configure(self.studio, enabled=False)
                    journal.configure(self.studio, enabled=True)
                elif operation == "delete":
                    journal.delete(self.studio, client="codex", session_id=self.session)
                else:
                    self.clock += 91 * 86400
                self.append(native, {"type":"event_msg","payload":{"type":"task_complete","turn_id":operation,
                                                                  "last_agent_message":"Never backfill " + operation}})
                self.hook("SessionStart")
                self.hook("Stop", turn_id=operation, last_assistant_message="Never backfill " + operation)
                self.assertNotIn("Never backfill", json.dumps(self.rows()))
                native.unlink()
        self.assertEqual(self.rows(), [])

    def test_reconcile_after_kill_before_stop_or_leave_gap_without_native_history(self):
        journal.configure(self.studio, enabled=True)
        for client in journal.CLIENTS:
            with self.subTest(client=client):
                path = self.native_file(client)
                # Existing client history may contain personal material read before consent.
                self.append(path, {"type":"event_msg","payload":{"type":"task_complete","turn_id":"old",
                                                                 "last_agent_message":"Pre-consent history"}})
                self.hook("UserPromptSubmit", client, turn_id="t1", prompt="Who owns the pilot?", transcript_path=str(path))
                self.clock += 1
                if client == "codex":
                    self.append(path, {"type":"response_item","payload":{"type":"function_call_output","output":"Hidden tool"}})
                    self.append(path, {"type":"event_msg","payload":{"type":"agent_message","message":"Incomplete thought"}})
                    self.append(path, {"type":"event_msg","payload":{"type":"task_complete","turn_id":"t1",
                                                                     "last_agent_message":"Jo owns the pilot."}})
                else:
                    meta = {"sessionId":self.session, "cwd":str(self.root)}
                    self.append(path, dict(meta, type="user", uuid="U",message={"role":"user","content":"Who owns the pilot?"}))
                    self.append(path, dict(meta, type="assistant", uuid="A", parentUuid="U",
                                           message={"role":"assistant","stop_reason":"end_turn","content":[
                                               {"type":"thinking","thinking":"Hidden thought"},{"type":"text","text":"Jo owns the pilot."}]}))
                delivered = self.time_string()
                self.clock += 2 * 86400
                self.hook("SessionStart", client)
                path.unlink()  # Both clients can still use the local visible journal after native history expires.
                self.assertEqual([r["text"] for r in self.rows(client)], ["Who owns the pilot?", "Jo owns the pilot."])
                self.assertEqual(self.rows(client)[-1]["time"], delivered)
                self.hook("UserPromptSubmit", client, turn_id="lost", prompt="Which test?", transcript_path=str(path))
                self.hook("SessionStart", client)
                self.assertEqual(self.rows(client)[-1]["status"], "gap")

    def test_native_file_metadata_position_and_turn_boundary(self):
        journal.configure(self.studio, enabled=True)
        path = self.native_file("codex")
        self.hook("UserPromptSubmit", turn_id="t1", prompt="Read the pilot brief.", transcript_path=str(path))
        self.append(path, {"type":"event_msg","payload":{"type":"task_started","turn_id":"other"}})
        self.append(path, {"type":"event_msg","payload":{"type":"task_complete","turn_id":"t1","last_agent_message":"Leaked"}})
        self.assertEqual(self.rows()[-1]["status"], "gap")
        old = path.with_suffix(".old")
        path.rename(old)
        path.write_bytes(old.read_bytes())
        self.assertEqual(self.rows()[-1]["status"], "gap")
        old.unlink()
        path.unlink()
        path.symlink_to(self.root / "hidden.jsonl")
        self.assertIsNone(journal_native.checkpoint(self.studio,"codex",self.session,{"transcript_path":str(path)}, self.clock))
        path.unlink()
        self.append(path, {"type":"session_meta","payload":{"id":self.session,"cwd":str(self.base / "other")}})
        self.assertIsNone(journal_native.checkpoint(self.studio,"codex",self.session,{"transcript_path":str(path)}, self.clock))
        self.assertIsNone(journal_native.checkpoint(self.studio,"claude",self.session,{"transcript_path":str(path)}, self.clock))

    def test_claude_first_prompt_precedes_file_and_client_attachments_bridge_parent_ids(self):
        journal.configure(self.studio, enabled=True)
        path = self.native_file("claude")
        path.unlink()
        self.hook("UserPromptSubmit", "claude", prompt="What next?", transcript_path=str(path))
        self.clock -= 0.070
        common = {"sessionId": self.session, "cwd": str(self.root), "isSidechain": False}
        self.append(path, dict(common, type="mode"))
        self.append(path, dict(common, type="attachment", uuid="before", attachment={"text": "Internal note"}))
        self.append(path, dict(common, type="user", uuid="human", origin={"kind": "human"}, turnOrigin="human",
                               parentUuid="before", message={"role": "user", "content": "What next?"}))
        self.append(path, dict(common, type="attachment", uuid="bridge", parentUuid="human",
                               attachment={"text": "Client-generated context"}))
        self.clock += 1
        self.append(path, dict(common, type="assistant", uuid="answer", parentUuid="bridge",
                               message={"role": "assistant", "stop_reason": "end_turn",
                                        "content": [{"type": "text", "text": "Run a pilot."}]}))
        self.assertEqual([r["text"] for r in self.rows("claude")], ["What next?", "Run a pilot."])
        self.assertNotIn(b"Client-generated context", (journal.location(self.studio)/"journal.sqlite3").read_bytes())

    def test_delayed_idless_stops_and_stale_scope_binding_stay_unattributed(self):
        journal.configure(self.studio, enabled=True)
        old = self.hook("UserPromptSubmit", "claude", prompt="First")
        self.hook("UserPromptSubmit", "claude", prompt="Second")
        self.assertIsNone(journal.bind_turn_scope(self.studio, "claude", old, "work/handoff/a"))
        self.hook("Stop", "claude", last_assistant_message="A late reply to the first request")
        self.assertEqual([r["status"] for r in self.rows("claude")], ["visible", "gap", "visible", "gap"])
        journal.set_off_record(self.studio, "claude", self.session, True)
        journal.set_off_record(self.studio, "claude", self.session, False)
        self.hook("UserPromptSubmit", "claude", prompt="A new request")
        self.hook("Stop", "claude", last_assistant_message="Late off-record answer")
        self.assertNotIn("Late off-record answer", repr(self.rows("claude")))

    def test_concurrent_submissions_are_exactly_once_restricted_input_becomes_gap(self):
        journal.configure(self.studio, enabled=True)
        with ThreadPoolExecutor(6) as pool:
            list(pool.map(lambda _: self.hook("UserPromptSubmit", turn_id="one", prompt="A visible question"), range(12)))
            list(pool.map(lambda _: self.hook("Stop",turn_id="one",last_assistant_message="A visible reply"),range(10)))
        self.assertEqual(len(self.rows()), 2)
        self.hook("UserPromptSubmit", turn_id="two", prompt="password=secret_fixture")
        self.hook("Stop", turn_id="two", last_assistant_message="Potential echo")
        self.assertTrue(all(row["status"] == "gap" for row in self.rows()[-2:]))
        with sqlite3.connect(journal.location(self.studio) / "journal.sqlite3") as db:
            self.assertNotIn("secret_fixture", repr(db.execute("SELECT * FROM turns").fetchall()))
        journal.delete(self.studio)
        raw = (journal.location(self.studio) / "journal.sqlite3").read_bytes()
        self.assertNotIn(b"A visible question", raw)

    def test_handoff_binding_exact_turn_permission_and_epoch(self):
        journal.configure(self.studio, enabled=True)
        scope = "product/pilot"
        prompt = self.hook("UserPromptSubmit", turn_id="t1", prompt="What is next?")
        self.assertIsNone(journal.bind_turn_scope(self.studio,"codex",dict(prompt,prompt="Other"),scope))
        key = journal.bind_turn_scope(self.studio,"codex",prompt,scope)
        self.assertIsNotNone(key)
        self.assertIsNone(journal.bind_turn_scope(self.studio,"codex",prompt,"product/other"))
        self.hook("Stop",turn_id="t1",last_assistant_message="Run the pilot.")
        self.assertIsNone(journal.resolve_reference(self.studio,key,scope="product/other"))
        self.assertIsNone(journal.resolve_reference(self.studio,key,purpose="profile"))
        self.assertNotIn("text", journal.resolve_reference(self.studio,key,scope=scope))
        self.assertNotIn("text", journal.latest_reference(self.studio,"codex",self.session,scope=scope))
        self.hook("UserPromptSubmit",turn_id="t2",prompt="The pilot starts Friday.",scope=scope)
        self.hook("Stop",turn_id="t2",last_assistant_message="Recorded in our conversation.")
        journal.set_off_record(self.studio,"codex",self.session,True)
        self.assertEqual(journal.later_exchanges(self.studio,key,scope=scope),[])
        journal.set_off_record(self.studio,"codex",self.session,False)
        self.hook("UserPromptSubmit",turn_id="t3",prompt="New permission interval.",scope=scope)
        later = journal.later_exchanges(self.studio,key,scope=scope)
        self.assertEqual([r["text"] for r in later],["Run the pilot.","The pilot starts Friday.","Recorded in our conversation."])
        self.hook("UserPromptSubmit",turn_id="t4",prompt="Another task")
        self.hook("Stop",turn_id="t4",last_assistant_message="Done")
        event = self.rows()[-2]["id"]
        with self.assertRaises(ValueError):
            journal.attach(self.studio,"codex",self.session,event,scope,approved=False)
        self.assertEqual(journal.attach(self.studio,"codex",self.session,event,scope,approved=True)["id"],event)
        journal.configure(self.studio,days=1)
        self.clock += 2*86400
        self.assertIsNone(journal.resolve_reference(self.studio,key,scope=scope))
        self.assertIsNone(journal.latest_reference(self.studio,"codex",self.session,scope=scope))

    def test_owner_can_find_expire_and_erase_an_orphan_after_a_move(self):
        journal.configure(self.studio, enabled=True, days=1)
        old_id = journal.status(self.studio)["store_id"]
        old_file = journal.location(self.studio) / "journal.sqlite3"
        self.hook("UserPromptSubmit", turn_id="old", prompt="Private old exchange")
        self.clock += 18 * 3600
        self.hook("UserPromptSubmit", turn_id="new", prompt="Recent orphan exchange")
        self.clock += 12 * 3600
        moved = self.base / "elsewhere/studio"
        moved.parent.mkdir()
        self.studio.rename(moved)
        self.assertFalse(journal.status(moved)["enabled"])
        self.studio.mkdir()
        self.assertFalse(journal.status(self.studio)["enabled"])
        journal.configure(self.studio, enabled=True)
        self.hook("UserPromptSubmit", turn_id="independent", prompt="Other Studio conversation")
        live_file = journal.location(self.studio) / "journal.sqlite3"
        live_id = journal.status(self.studio)["store_id"]
        with patch.object(sqlite3, "connect", side_effect=AssertionError("inventory opened a database")):
            inventory = journal.stores()["stores"]
        self.assertEqual({row["store_id"] for row in inventory}, {old_id, live_id})
        self.assertTrue(all(set(row) == {"store_id", "modified"} for row in inventory))
        before = live_file.read_bytes()
        self.assertEqual(journal.maintain_store(old_id)["status"], "pruned")
        with sqlite3.connect(old_file) as db:
            self.assertEqual(db.execute("SELECT native FROM turns").fetchall(), [("new",)])
        self.assertEqual(journal.maintain_store(old_id, erase=True)["status"], "deleted")
        self.assertFalse(old_file.exists())
        self.assertEqual(journal.maintain_store(old_id, erase=True)["status"], "absent")
        self.assertEqual(live_file.read_bytes(), before)
        self.assertEqual([row["store_id"] for row in journal.stores()["stores"]], [live_id])
        with self.assertRaises(ValueError):
            journal.maintain_store("../other", erase=True)
        with patch.dict(os.environ, PM_HUB_PROTECTED_ROOT=str(self.root)), self.assertRaises(ValueError):
            journal.stores()

    def test_unsupported_filesystem_preserves_ordinary_processing_and_explicit_privacy(self):
        with patch.object(journal, "_birth_time", return_value=None):
            self.assertFalse(journal.status(self.studio)["available"])
            self.assertFalse(journal.off_record(self.studio, "codex", self.session))
            with self.assertRaisesRegex(ValueError, "creation time"):
                journal.configure(self.studio, enabled=True)
            self.hook("UserPromptSubmit", turn_id="plain", prompt="Ordinary input")
            self.assertFalse((self.base / "state").exists())
            journal.set_off_record(self.studio, "codex", self.session, True)
            self.assertTrue(journal.off_record(self.studio, "codex", self.session))
            journal.set_off_record(self.studio, "codex", self.session, False)
            self.assertFalse(journal.off_record(self.studio, "codex", self.session))
            self.assertEqual(self.rows(), [])

    def test_recreated_studio_at_same_path_does_not_inherit_recording(self):
        journal.configure(self.studio, enabled=True)
        first_id = journal.status(self.studio)["store_id"]
        self.hook("UserPromptSubmit", turn_id="first", prompt="Previous checkout")
        self.studio.rmdir()
        self.studio.mkdir()
        self.assertNotEqual(journal.location(self.studio).name, first_id)
        self.assertFalse(journal.status(self.studio)["enabled"])
        self.hook("UserPromptSubmit", turn_id="later", prompt="Fresh checkout")
        self.assertEqual(self.rows(), [])
        self.assertEqual(journal.stores()["stores"][0]["store_id"], first_id)

    def test_owner_lifecycle_commands_work_without_studio(self):
        # Use the actual dispatcher from the core checkout. The isolated state directory belongs to this test.
        journal.configure(self.studio, enabled=True)
        store = journal.status(self.studio)["store_id"]
        self.studio.rename(self.base / "removed")
        cli = [sys.executable, str(Path(__file__).resolve().parents[1] / "tools/pm.py"), "journal"]
        env = dict(os.environ)
        env.pop("PM_HUB_PROTECTED_ROOT", None)
        for argv, field, expected in [(["stores"], "stores", store),
                                      (["prune", "--store", store], "status", "pruned"),
                                      (["delete-store", store], "status", "deleted")]:
            completed = subprocess.run(cli + argv, cwd=self.base, env=env, capture_output=True, text=True)
            self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
            result = json.loads(completed.stdout)[field]
            self.assertEqual(result[0]["store_id"] if field == "stores" else result, expected)
        self.assertEqual(journal.stores(), {"stores": []})

    def test_handoff_suffix_contains_latest_decision_and_preserves_scope_boundary(self):
        journal.configure(self.studio, enabled=True)
        scope = "work/handoff/release"
        self.hook("UserPromptSubmit", turn_id="start", prompt="Start the checkpoint.", scope=scope)
        self.hook("Stop", turn_id="start", last_assistant_message="Initial date is Monday.")
        human, reply = self.rows()
        for index in range(12):
            self.hook("UserPromptSubmit", turn_id=str(index), prompt=f"Review {index}", scope=scope)
            self.hook("Stop", turn_id=str(index), last_assistant_message=f"Decision {index}")
        self.hook("UserPromptSubmit", turn_id="switch", prompt="Other work", scope="work/handoff/support")
        self.hook("UserPromptSubmit", turn_id="return", prompt="New work interval", scope=scope)
        for anchor, omitted in [(reply, 20), (human, 21)]:
            result = journal.later_exchanges(self.studio, anchor["id"], scope=scope, limit=4)
            self.assertEqual([event["text"] for event in result], ["Review 10", "Decision 10", "Review 11", "Decision 11"])
            self.assertEqual(result[0]["omitted_earlier_events"], omitted)
        latest = journal.later_exchanges(self.studio, human["id"], scope=scope, limit=1)
        self.assertEqual(latest[0]["text"], "Decision 11")
        self.assertEqual(latest[0]["omitted_earlier_events"], 24)

    def test_protected_launcher_masks_all_siblings_when_checkout_identity_is_unavailable(self):
        journal.configure(self.studio, enabled=True)
        base = journal.location(self.studio).parent
        with ExitStack() as stack:
            stack.enter_context(patch.object(agent_session.workspace, "repo", return_value=self.studio))
            stack.enter_context(patch.object(journal, "location", side_effect=ValueError("unknown checkout")))
            stack.enter_context(patch("subprocess.run"))
            stack.enter_context(patch("shutil.which", side_effect=lambda tool: "/bin/" + tool))
            stack.enter_context(patch("os.chdir"))
            exec_client = stack.enter_context(patch("os.execvpe"))
            for platform in ("linux", "darwin"):
                with patch.object(agent_session.sys, "platform", platform):
                    agent_session.launch(self.root, "codex")
                    args = exec_client.call_args.args[1]
                    if platform == "linux":
                        i = args.index("--tmpfs")
                        self.assertEqual(args[i:i + 4], ["--tmpfs", str(base), "--remount-ro", str(base)])
                    else:
                        self.assertIn(f"(deny file-read* file-write* (subpath {json.dumps(str(base))}))", args[2])
                    self.assertNotIn(str(base), args[-1])
            exec_client.reset_mock()
            with patch.object(journal, "protected_home", side_effect=ValueError("unsafe namespace")):
                with self.assertRaises(ValueError):
                    agent_session.launch(self.root, "claude")
            exec_client.assert_not_called()

    def test_immutable_state_mount_only_masks_existing_verified_namespaces(self):
        state = Path(os.environ["XDG_STATE_HOME"])
        state.mkdir(mode=0o700)
        base = state / "oryx" / "journals"
        with ExitStack() as stack:
            stack.enter_context(patch.object(agent_session.workspace, "repo", return_value=self.studio))
            stack.enter_context(patch("subprocess.run"))
            stack.enter_context(patch("shutil.which", side_effect=lambda tool: "/bin/" + tool))
            stack.enter_context(patch("os.chdir"))
            stack.enter_context(patch.object(agent_session.sys, "platform", "linux"))
            exec_client = stack.enter_context(patch("os.execvpe"))
            for exists in (False, True):
                if exists:
                    base.parent.mkdir(mode=0o700)
                    base.mkdir(mode=0o700)
                    (base / ("a" * 64)).mkdir(mode=0o700)
                immutable = OSError(errno.EROFS, "Read-only filesystem")
                with patch("os.statvfs") as statvfs, patch.object(Path, "mkdir", side_effect=immutable) as mkdir:
                    statvfs.return_value.f_flag = os.ST_RDONLY
                    agent_session.launch(self.root, "codex")
                    mkdir.assert_not_called()
                    args = exec_client.call_args.args[1]
                    self.assertEqual("--tmpfs" in args, exists)
                    if exists:
                        i = args.index("--tmpfs")
                        self.assertEqual(args[i:i + 4], ["--tmpfs", str(base), "--remount-ro", str(base)])
                    self.assertNotIn(str(base), args[-1])
            base.chmod(0o755)
            with patch("os.statvfs") as statvfs, self.assertRaises(ValueError):
                statvfs.return_value.f_flag = os.ST_RDONLY
                agent_session.launch(self.root, "codex")
            base.chmod(0o700)
            # An EROFS or permission error alone cannot establish absence on a read-only mount.
            with patch.dict(os.environ, XDG_STATE_HOME=str(self.base / "missing")), patch("os.statvfs") as statvfs:
                statvfs.return_value.f_flag = 0
                with patch.object(Path, "mkdir", side_effect=OSError(errno.EROFS, "unverified")), self.assertRaises(OSError):
                    agent_session.launch(self.root, "codex")

    def test_protected_client_policy_scope_and_optional_statusline(self):
        with ExitStack() as stack:
            stack.enter_context(patch.object(agent_session.workspace, "repo", return_value=self.studio))
            stack.enter_context(patch.object(agent_session.sys, "platform", "linux"))
            # Stub launcher alignment only. Filesystem identity still uses the OS's actual creation time.
            run = subprocess.run
            stack.enter_context(patch("subprocess.run", side_effect=lambda command, **kwargs:
                                      None if command[-1] == "align" else run(command, **kwargs)))
            stack.enter_context(patch("shutil.which", side_effect=lambda tool: "/bin/" + tool))
            stack.enter_context(patch("os.chdir"))
            launch = stack.enter_context(patch("os.execvpe"))
            agent_session.launch(self.root,"codex")
            _, argv, env = launch.call_args.args
            self.assertEqual(env["PM_HUB_CLIENT"], "codex")
            own = journal.location(self.studio)
            self.assertIn(f'{json.dumps(str(own))}="write"', argv[-1])
            self.assertNotIn(f'{json.dumps(str(own.parent))}="write"',argv[-1])
            mask = argv.index("--tmpfs")
            self.assertEqual(argv[mask:mask + 7], ["--tmpfs", str(own.parent), "--bind", str(own),
                                                   str(own), "--remount-ro", str(own.parent)])
            self.assertFalse((own/"journal.sqlite3").exists())
            agent_session.launch(self.root,"claude")
            self.assertNotIn("--settings", launch.call_args.args[1])
            agent_session.launch(self.root,"claude",context_statusline=True)
            settings = json.loads(launch.call_args.args[1][-1])
            self.assertIn("claude-statusline",settings["statusLine"]["command"])
            with self.assertRaises(ValueError):
                agent_session.launch(self.root,"codex",context_statusline=True)


if __name__ == "__main__":
    unittest.main()
