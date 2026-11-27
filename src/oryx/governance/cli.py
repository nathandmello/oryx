"""Scoped reads and structured reports from the authenticated customer peer."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import UUID, uuid4

from .client import request
from .common import LIMIT, SHA, canonical, decode, digest, identifier, shape
from .files import directory, read, save


def private_root(explicit):
    from oryx.workspace.location import selected_path
    core = Path(__file__).resolve().parents[3]
    private = selected_path(core, explicit=explicit)
    if private is None or not private.is_dir():
        raise ValueError("Select an existing personal Workspace")
    try:
        root = subprocess.run(["git", "-C", str(private), "rev-parse", "--show-toplevel"],
                              capture_output=True, text=True, timeout=10)
    except subprocess.SubprocessError as exc:
        raise ValueError("Cannot verify the selected Workspace Git root") from exc
    if root.returncode or Path(root.stdout.strip()).resolve() != private:
        raise ValueError("Git root does not match the selected Workspace")
    return private


def local_scope(private, body):
    shape(body, ("type",), ("parent",))
    if body["type"] not in {"company","function","team","user"}:
        raise ValueError("Invalid local scope type")
    root = directory(private, ".oryx/state/scopes", True)
    parent = body.get("parent")
    parents = {"company":{None},"function":{"company"},"team":{"company","function"},"user":{"company","function","team"}}
    parent_type = read(root / (str(UUID(parent))+".json"))["type"] if parent else None
    if parent_type not in parents[body["type"]]:
        raise ValueError("Invalid local scope hierarchy")
    rid=str(uuid4())
    scope={"id":rid,"type":body["type"],"parent":parent,"membership":"local-only"}
    save(root / (rid+".json"), scope)
    return scope


def checked_paths(private):
    """Recognize only well-formed optional sharing state, for the Workspace integrity checker."""
    from oryx.sharing.transfer import check
    names=set()
    root=Path(private)
    sections=(".oryx/staging/sharing",".oryx/state/transfers",".oryx/state/scopes",".oryx/state/github-transfers")
    for relative in sections:
        folder=directory(root,relative)
        if not folder.exists():
            continue
        for path in folder.iterdir():
            value=read(path)
            if relative.endswith("/github-transfers"):
                from .github import transfer_binding
                transfer_binding(value)
                if path.name!=digest(value["id"].encode())+".json":
                    raise ValueError("Mismatched GitHub transfer recovery address")
            elif relative.endswith("/transfers"):
                check(value,path.name)
            elif relative.endswith("/scopes"):
                shape(value, ("id","type","parent","membership"))
                if path.name != str(UUID(value["id"]))+".json" or value["membership"]!="local-only":
                    raise ValueError("Invalid local scope")
            else:
                shape(value, ("organization","actor","intent","commitment"))
                if path.name!=value["commitment"]+".json" or digest(canonical(value["intent"]))!=value["commitment"]:
                    raise ValueError("Invalid reviewed sharing draft")
            names.add(path.relative_to(root).as_posix())
    return names


def arguments(argv, names):
    parser=argparse.ArgumentParser()
    parser.add_argument("operation",choices=names)
    parser.add_argument("--workspace",type=Path)
    return parser.parse_args(argv)


def read_body():
    raw=sys.stdin.buffer.readline(LIMIT+1) if not sys.stdin.isatty() else b"{}"
    if not raw.strip():
        return {}
    # Read a full bounded JSON document, including ordinary indented input.
    raw+=sys.stdin.buffer.read(LIMIT+1-len(raw)) if not sys.stdin.isatty() and len(raw)<=LIMIT else b""
    result=decode(raw)
    if not isinstance(result,dict):
        raise ValueError("Supply one JSON object on standard input")
    return result


def main(argv=None):
    args=arguments(argv, ("local","scope","sync","read","owner","resolve","report","reviews","github-status","github-reviews","github-policy","github-verify","github-merge","github-transfer","github-reconcile","github-record"))
    try:
        body=read_body()
        if args.operation=="local":
            result=local_scope(private_root(args.workspace),body)
        elif args.operation.startswith("github-"):
            from .github import run
            needs_private=args.operation=="github-transfer" or (args.operation=="github-reconcile" and "id" in body)
            result=run(args.operation,body,private_root(args.workspace) if needs_private else None)
        else:
            result=request(args.operation,body)
        print(json.dumps(result,ensure_ascii=True))
        return 0
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.SubprocessError) as exc:
        print(str(exc),file=sys.stderr)
        return 1
