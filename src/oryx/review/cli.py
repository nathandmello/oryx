"""Stage reviewed notes, inspect exact revisions, and commit from a PM-controlled terminal."""

import argparse
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import zipfile
import zlib
from tempfile import TemporaryDirectory

from . import store


def tty_session():
    store.pm_only()
    fd = os.open("/dev/tty", os.O_RDWR | os.O_NOCTTY | os.O_CLOEXEC)
    try:
        if not os.isatty(fd) or os.tcgetpgrp(fd) != os.getpgrp():
            raise ValueError("Review requires the foreground PM terminal")
        return os.fdopen(fd, "r+b", buffering=0)
    except BaseException:
        os.close(fd)
        raise


def confirm_effect(summary, displayed, keyword):
    """Show the exact operation in the PM's foreground terminal and read its decision."""
    with tty_session() as terminal:
        terminal.write(summary.encode("utf-8") + b"\n")
        terminal.write(json.dumps(displayed, ensure_ascii=True, indent=2).encode("ascii") + b"\n")
        terminal.write(f"Type {keyword} to approve this exact operation: ".encode("ascii"))
        decision = terminal.readline(64)
        return decision.endswith(b"\n") and decision.strip() == keyword.encode("ascii")


def interact(ws, identifier, *, actor="pm-local-review"):
    store.pm_only()
    shown = ws.inspect(identifier)
    if shown["state"] == "recovering":
        return ws.decide(identifier, store.encoded(shown), "save", actor=actor)
    if shown["state"] != "pending":
        return shown
    reviewed = store.encoded(shown)
    with tty_session() as terminal:
        terminal.write(b"Review this exact local change. JSON escapes represent exact characters.\n")
        terminal.write(json.dumps(shown, ensure_ascii=True, indent=2).encode() + b"\n")
        terminal.write(b"Type save, discard, or later and press Return: ")
        decision = terminal.readline(32).strip()
    if decision in (b"", b"later"):
        return {"id": identifier, "state": "pending"}
    if decision not in (b"save", b"discard"):
        raise ValueError("Unrecognized PM decision. The proposal remains staged")
    return ws.decide(identifier, reviewed, decision.decode(), actor=actor)


def direct_edit(ws, path):
    store.pm_only()
    if not store.NOTE.fullmatch(path):
        raise ValueError("Choose a managed note")
    with tty_session():
        pass
    head, texts = ws.snapshot()
    name = path.split("/")[1]
    with TemporaryDirectory(dir=ws.state) as folder:
        draft = Path(folder) / name
        draft.write_bytes(texts.get(name, "").encode("utf-8"))
        command = shlex.split(os.environ.get("VISUAL") or os.environ.get("EDITOR") or "vi")
        if not command:
            raise ValueError("Configure an interactive editor")
        subprocess.run([*command, str(draft)], check=True)
        if draft.is_symlink() or draft.stat().st_size > store.MAX_NOTE:
            raise ValueError("Edited note is invalid or too large")
        edited = draft.read_bytes().decode("utf-8")
    result = ws.stage({"current_behavior": "The saved note remains at the displayed revision.",
                       "reason": "The PM edited this text in the local editor.",
                       "effect": "Saving publishes the exact wording shown.",
                       "changes": [{"path": path, "base": head["files"].get(name), "text": edited}]})
    return interact(ws, result["id"], actor="pm-local-editor")


def main(argv=None):
    parser = argparse.ArgumentParser(prog="oryx review", description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    commands.add_parser("init", help="Initialize protected local Markdown notes and review state")
    recovery = commands.add_parser("recover-copy", help="Rebind pending initiative changes on an untouched local restore")
    recovery.add_argument("--archive", required=True, type=Path)
    recovery.add_argument("--expect", required=True, help="Digest from the separately retained backup inventory")
    commands.add_parser("stage", help="Stage a complete change group from JSON on standard input")
    commands.add_parser("status", help="List durable local proposals by state")
    for name in ("show", "decide"):
        commands.add_parser(name).add_argument("id")
    commands.add_parser("edit", help="Edit a note directly in the PM's local editor").add_argument("path")
    commands.add_parser("read", help="Read a coherent generation of official notes").add_argument("paths", nargs="*")
    args = parser.parse_args(argv)
    try:
        ws = store.Workspace()
        if args.action == "init":
            result = ws.init()
        elif args.action == "recover-copy":
            from . import work
            result = work.recover_copy(ws, args.archive, args.expect)
        elif args.action == "stage":
            data = sys.stdin.buffer.read(store.MAX_METADATA + 1)
            if len(data) > store.MAX_METADATA:
                raise ValueError("Review input exceeds the supported limit")
            result = ws.stage(json.loads(data, object_pairs_hook=store.unique))
        elif args.action == "show":
            result = ws.inspect(args.id)
        elif args.action == "decide":
            result = interact(ws, args.id)
        elif args.action == "edit":
            result = direct_edit(ws, args.path)
        elif args.action == "status":
            result = []
            if ws.staging.exists():
                store.checked_directory(ws.staging)
                for path in sorted(ws.staging.iterdir()):
                    if path.suffix != ".json" or not store.HEX.fullmatch(path.stem):
                        continue
                    try:
                        status = ws.inspect(path.stem)["state"]
                    except (ValueError, OSError):
                        status = "needs-review"
                    result.append({"id": path.stem, "state": status})
        else:
            head, texts = ws.snapshot()
            paths = args.paths or ["notes/" + name for name in sorted(texts)]
            if any(not store.NOTE.fullmatch(path) or path.split("/")[1] not in texts for path in paths):
                raise ValueError("Unknown protected note")
            result = {"workspace": ws.identity, "generation": store.sha(store.encoded(head)),
                      "records": [{"path": path, "revision": head["files"][path.split("/")[1]],
                                   "text": texts[path.split("/")[1]]} for path in paths]}
        print(json.dumps(result, indent=2, ensure_ascii=True))
        return 0
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, zipfile.BadZipFile, zlib.error, subprocess.SubprocessError) as error:
        print(f"Review held: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
