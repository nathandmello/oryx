"""Inspect, adopt, and recover records through the personal Workspace CLI."""

import argparse
import json
from pathlib import Path
import subprocess
import sys
import zipfile

from oryx.recovery import snapshot
from . import adoption, citations, identity, portable


def hash_option(parser):
    parser.add_argument("--expect", required=True, help="Digest of the reviewed input")


def parser():
    command = argparse.ArgumentParser(prog="oryx workspace", description=__doc__)
    operations = command.add_subparsers(dest="operation", required=True)
    for name in ("adoption-preview", "adopt"):
        action = operations.add_parser(name)
        action.add_argument("source", type=Path)
        action.add_argument("destination", type=Path)
        if name == "adopt":
            action.add_argument("--backup", required=True, type=Path)
            hash_option(action)
    operations.add_parser("record-list")
    for name in ("record-resolve", "record-citation"):
        action = operations.add_parser(name)
        action.add_argument("record", help="Durable record ID or known relative path")
        action.add_argument("--revision")
        if name == "record-citation":
            action.add_argument("href")
    hash_option(operations.add_parser("record-refresh"))
    move = operations.add_parser("record-move")
    move.add_argument("record")
    move.add_argument("destination")
    hash_option(move)
    for name in ("portable-preview", "portable-export"):
        action = operations.add_parser(name)
        action.add_argument("destination", type=Path)
        if name == "portable-export":
            hash_option(action)
    restore = operations.add_parser("portable-restore")
    restore.add_argument("archive", type=Path)
    restore.add_argument("destination", type=Path)
    hash_option(restore)
    return command


def run(core, args):
    import storage
    import workspace

    action = args.operation
    if action == "adoption-preview":
        plan = adoption.preview(args.source, args.destination)
        return {"digest": snapshot.digest(plan), "plan": plan}
    if action == "adopt":
        return adoption.adopt(args.source, args.destination, args.backup, args.expect)
    if action == "portable-restore":
        return portable.restore(args.archive, args.destination, args.expect)

    if storage.selected_workspace(core) is None:
        raise ValueError("Select a personal Workspace with ORYX_WORKSPACE")
    private = workspace.repo(core, "workspace")
    if action == "record-list":
        plan = identity.preview(private)
        return {"digest": snapshot.digest(plan), "plan": plan}
    if action == "record-refresh":
        return identity.refresh(private, args.expect)
    if action == "record-resolve":
        return identity.resolve(private, args.record, args.revision)
    if action == "record-citation":
        return citations.lookup(private, args.record, args.href, args.revision)
    if action == "record-move":
        return identity.move(private, args.record, args.destination, args.expect)
    raw = sys.stdin.read(256 * 1024 + 1)
    if len(raw) > 256 * 1024:
        raise ValueError("Portable selection exceeds the input limit")
    policy = storage.json_input(raw)
    if action == "portable-preview":
        plan, _ = portable.review(private, args.destination, policy)
        return {"digest": portable.review_digest(plan), "plan": plan}
    return portable.export(private, args.destination, policy, args.expect)


def main(core, argv=None):
    args = parser().parse_args(argv)
    try:
        snapshot.require_pm_terminal()
        result = run(core, args)
    except (OSError, ValueError, TypeError, KeyError, RuntimeError, subprocess.SubprocessError, zipfile.BadZipFile) as exc:
        print(f"Workspace operation held: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0
