"""Compare registered client hooks and reviewed stakeholder actions in two fresh Studios."""

import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import test_conversation


CORE = Path(__file__).resolve().parents[1]
FUNCTIONS = {
    "src/oryx/adapters/host_hooks.py": ["main", "prompt_context", "assess_chat"],
    "src/oryx/cli/command.py": ["main"],
    "src/oryx/subscribers/ingestion.py": ["for_task"],
    "src/oryx/capabilities/source_evidence.py": ["material"],
    "src/oryx/capabilities/evidence_spans.py": ["inspect"],
    "src/oryx/subscribers/stakeholder_signals.py": ["evaluate", "validate_change"],
    "src/oryx/capabilities/stakeholder_profiles.py": ["preview", "accept"],
    "src/oryx/capabilities/task_context.py": ["turn_context"],
    "src/oryx/capabilities/profile_retrieval.py": ["for_task"],
}
SHARED_SKILL = Path(".agents/skills/stakeholder-profiles/SKILL.md")
# Install this observer only on the test subprocess path. It records executed entry points,
# including those loaded by a registered shell handler, without replacing their implementations.
OBSERVER = '''import atexit, json, os, sys
from pathlib import Path
targets = json.loads(os.environ["ORYX_TEST_WATCH"])
observed = set()
def observe(frame, event, arg):
    if event == "call":
        filename, name = frame.f_code.co_filename, frame.f_code.co_name
        if filename in targets and name in targets[filename]:
            observed.add((filename, name))
def save():
    sys.setprofile(None)
    with open(os.environ["ORYX_TEST_TRACE"], "a") as out:
        out.write(json.dumps(sorted(observed)) + "\\n")
sys.setprofile(observe)
atexit.register(save)
'''


def sha(data):
    return hashlib.sha256(data).hexdigest()


def exercise(client, directory):
    fixture = test_conversation.ConversationTests()
    fixture.setUp()
    try:
        root, studio = fixture.root, fixture.work
        registered = json.loads((root / (".claude/settings.json" if client == "claude" else ".codex/hooks.json")).read_bytes())
        hook = registered["hooks"]["UserPromptSubmit"][0]["hooks"][0]
        command = [hook["command"], *hook["args"]] if client == "claude" else hook["command"]
        source_hashes = {path: sha((root / path).read_bytes()) for path in [*FUNCTIONS, str(SHARED_SKILL)]}
        fixture.assertEqual((root / SHARED_SKILL).read_bytes(), (root / ".claude/skills/stakeholder-profiles/SKILL.md").read_bytes())
        watch = {str(root / path): names for path, names in FUNCTIONS.items()}
        trace = directory / "calls.jsonl"
        env = {"PYTHONPATH": str(directory), "XDG_STATE_HOME": str(directory / "state"),
               "ORYX_TEST_WATCH": json.dumps(watch), "ORYX_TEST_TRACE": str(trace)}
        (directory / "sitecustomize.py").write_text(OBSERVER)
        def turn(text, tid):
            event = {"hook_event_name": "UserPromptSubmit", "cwd": str(root), "session_id": "same-work",
                     "turn_id": tid, "prompt": text}
            process = subprocess.run(command, shell=isinstance(command, str), input=json.dumps(event),
                                     cwd=root, capture_output=True, text=True, check=True)
            return json.loads(process.stdout)["hookSpecificOutput"]["additionalContext"]
        with patch.dict(os.environ, env):
            turn("Help me prepare for the Billing review.", "start")
            line = "[03:20] Jo Diaz: I do not want slides unless the customer asks."
            ref = "context/notes/billing-review.txt"
            source_file = studio / ref
            source_file.parent.mkdir(parents=True, exist_ok=True)
            source_file.write_text(line + "\n")
            checked = fixture.cli("ingestion", "assess", payload={
                "source": {"reference": ref, "scope": ref, "source_id": "billing-review",
                           "kind": "transcript", "subject": "product/billing", "authorized": True,
                           "purposes": ["stakeholder-profile"], "retention": "review"}, "moment": "pause"})
            offer = checked["selection"]
            fixture.assertEqual(offer["person"], "Jo Diaz")
            change = {k: offer[k] for k in ("topic", "kind", "wording", "source", "excerpt", "scope",
                                             "subject", "observed_on", "attribution", "evidence")}
            change.update(id="jo-diaz", role="Service lead", name=offer["person"])
            person = studio / "context/stakeholders/profiles/jo-diaz.json"
            fixture.assertFalse(person.exists())
            review = fixture.cli("stakeholder-profile", "preview", payload=change)
            effects = {"preview_writes": int(person.exists())}
            fixture.cli("stakeholder-profile", "accept", payload={"review": review, "approved_wording": "Always use slides."},
                        error="exact reviewed wording")
            effects["rejected_approval_writes"] = int(person.exists())
            approval = {"review": review, "approved_wording": change["wording"]}
            fixture.assertTrue(fixture.cli("stakeholder-profile", "accept", payload=approval)["written"])
            before = person.read_bytes()
            replay = fixture.cli("stakeholder-profile", "accept", payload=approval)
            effects["replay_added"] = int(replay["written"] or before != person.read_bytes())
            entries = fixture.cli("stakeholder-profile", "show", "jo-diaz")["entries"]
            effects["accepted_records"] = len(entries)
            # Include the actual person, source, wording, scope and original evidence in the digest.
            entries_for_compare = []
            for entry in entries:
                evidence = entry["evidence"]
                fixture.assertEqual(evidence, offer["evidence"])
                start, end = evidence["start"], evidence["end"]
                passage = source_file.read_bytes()[start:end].decode()
                fixture.assertEqual(passage, entry["excerpt"])
                # The grant and span tokens authenticate one Studio's read. Compare the
                # authoritative bytes, offsets and attribution they resolve to across Studios.
                semantic = {key: entry[key] for key in ("topic", "kind", "wording", "source", "excerpt",
                                                       "scope", "subject", "observed_on", "attribution")}
                semantic["passage"] = [start, end, passage]
                entries_for_compare.append(semantic)
            effects["record_sha256"] = sha(json.dumps([change["id"], entries_for_compare], sort_keys=True).encode())
            recall = turn("Draft a Billing update for Jo Diaz.", "recall")
            effects["named_recall"] = change["wording"] in recall
            refusal = turn("Make it shorter without using a stakeholder profile.", "refusal")
            effects["refusal_excluded"] = change["wording"] not in refusal
        observed = {str(Path(path).relative_to(root)) + ":" + name
                    for line_ in trace.read_text().splitlines() for path, name in json.loads(line_)}
        return {"paths": sorted(observed), "effects": effects}, source_hashes
    finally:
        fixture.doCleanups()


def capture():
    host = platform.system().lower()
    if host == "darwin":
        host = "macos"
    elif host == "linux" and "microsoft" in platform.release().lower():
        host = "wsl2"
    clients = {}
    hashes = {}
    expected_paths = sorted(path + ":" + function for path, names in FUNCTIONS.items() for function in names)
    with tempfile.TemporaryDirectory() as tmp:
        for client in ("claude", "codex"):
            # Journal storage requires a canonical path even when TMPDIR is a symlink.
            directory = Path(tmp).resolve() / client
            directory.mkdir()
            clients[client], hashes[client] = exercise(client, directory)
    effects = clients["codex"]["effects"]
    expected = {"preview_writes": 0, "rejected_approval_writes": 0, "accepted_records": 1,
                "replay_added": 0, "named_recall": True, "refusal_excluded": True}
    same = (clients["claude"] == clients["codex"] and hashes["claude"] == hashes["codex"] and
            clients["codex"]["paths"] == expected_paths and all(effects[k] == v for k, v in expected.items()))
    candidate = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=CORE, text=True).strip()
    return {"protocol": "oryx-shared-core/1", "host": host, "candidate": candidate,
            "source_hashes": hashes["codex"], "clients": clients, "same_core": same}


class ClientCoreParityTests(unittest.TestCase):
    def test_registered_hooks_and_reviewed_actions_share_code_and_effects(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "physical"
            target.mkdir()
            alias = Path(tmp) / "linked"
            alias.symlink_to(target, target_is_directory=True)
            with patch.object(tempfile, "tempdir", str(alias)):
                result = capture()
        self.assertTrue(result["same_core"], result)


if __name__ == "__main__":
    if sys.argv[1:] == ["--capture"]:
        pending = subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=all"], cwd=CORE)
        if pending:
            sys.exit("Collect release evidence from a clean checkout of the registered commit.")
        result = capture()
        print(json.dumps(result, sort_keys=True, indent=2))
        sys.exit(0 if result["same_core"] else 1)
    unittest.main()
