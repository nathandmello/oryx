"""Publish a private, index-free Git view derived from one approved group."""
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile

from . import identity, storage
from .location import workspace_id

ROOT = Path(".git/oryx-group-saves/history.git")
MANIFEST = ".oryx-publication.json"


def git(repo, *args, data=None, missing=False):
    env = {"PATH": os.defpath, "LC_ALL": "C", "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
           "GIT_ALLOW_PROTOCOL": "", "GIT_NO_LAZY_FETCH": "1", "GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0"}
    result = subprocess.run(["git", "--no-replace-objects", "--git-dir=" + str(repo),
                             "-c", "core.hooksPath=/dev/null", "-c", "core.fsync=all", *args],
                            env=env, input=data, capture_output=True, timeout=45)
    if missing and result.returncode == 1:
        return None
    if result.returncode:
        raise ValueError("Cannot verify local approved group history")
    return result.stdout


def repository(root, *, create=False):
    from .publication import ensure_parent, history_root, sync
    parent = history_root(root)
    repo = root / ROOT
    if repo.resolve() != repo:
        raise ValueError("Local group history must use an independent Git directory")
    if create and not repo.exists():
        ensure_parent(parent)
        with tempfile.TemporaryDirectory(dir=parent) as temp:
            staged = Path(temp) / "history.git"
            git(staged, "init", "--quiet", "--bare", "--template=", str(staged))
            staged.chmod(0o700)
            for folder, _, entries in os.walk(staged, topdown=False):
                for name in entries:
                    with (Path(folder) / name).open("rb") as stream:
                        os.fsync(stream.fileno())
                sync(Path(folder))
            storage.rename_exclusive(staged, repo)
            sync(parent)
    if not repo.is_dir():
        raise ValueError("The Workspace has no approved group history")
    info = repo.lstat()
    if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o077:
        raise ValueError("Group history must be owner-private")
    for name in ("config", "HEAD", "refs", "objects"):
        if (repo / name).resolve() != repo / name:
            raise ValueError("Redirected group history")
    if any(os.path.lexists(repo / path) for path in ("commondir", "objects/info/alternates",
                                                     "objects/info/http-alternates", "config.worktree")):
        raise ValueError("Group history cannot depend on another object store")
    return repo


def blob(repo, contents):
    return git(repo, "hash-object", "--no-filters", "-w", "--stdin", data=contents).strip()


def tree(repo, entries):
    encoded = []
    for name, value in entries.items():
        if isinstance(value, dict):
            kind, oid = b"040000 tree", tree(repo, value)
        else:
            kind, oid = b"100644 blob", value
        encoded.append(kind + b" " + oid + b"\t" + name.encode() + b"\0")
    return git(repo, "mktree", "-z", data=b"".join(encoded)).strip()


def reference(revision):
    if not isinstance(revision, str) or not identity.SHA.fullmatch(revision):
        raise ValueError("Supply the exact reviewed group revision")
    return "refs/oryx/publications/" + revision


def lookup(repo, ref):
    value = git(repo, "rev-parse", "--verify", "--quiet", ref, missing=True)
    return None if value is None else value.decode().strip()


def prepare(root, intent, metadata):
    repo = repository(root, create=True)
    approval = intent.get("approval")
    revision = hashlib.sha256(metadata).hexdigest()
    if approval is not None:
        if not isinstance(approval, dict) or set(approval) != {"path", "revision"}:
            raise ValueError("Invalid approved publication binding")
        approved = next((row for row in intent["changes"] if row["path"] == approval["path"]), None)
        if not approved or approved["after"] is None:
            raise ValueError("Group lacks its reviewed PM approval receipt")
        receipt = storage.json_input(approved["after"])
        if (not isinstance(receipt, dict) or not isinstance(receipt.get("approval"), dict)
                or receipt["approval"].get("revision") != approval["revision"]
                or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", str(receipt.get("product", "")))
                or approval["path"] != ".oryx-approvals/" + receipt["product"] + ".json"):
            raise ValueError("Group differs from its reviewed PM approval receipt")
        revision = approval["revision"]
    ref = reference(revision)
    entries = {MANIFEST: blob(repo, metadata)}
    for row in intent["changes"]:
        if row["after"] is None:
            continue
        directory = entries
        *parents, name = Path(row["path"]).parts
        for part in parents:
            directory = directory.setdefault(part, {})
            if not isinstance(directory, dict):
                raise ValueError("Conflicting group paths")
        if name in directory:
            raise ValueError("Conflicting group paths")
        directory[name] = blob(repo, row["after"].encode("utf-8"))
    oid = tree(repo, entries).decode()
    if lookup(repo, ref) not in (None, oid):
        raise ValueError("An immutable group already exists for this reviewed revision")
    return repo, ref, oid


def publish(prepared):
    repo, ref, oid = prepared
    existing = lookup(repo, ref)
    if existing is None:
        git(repo, "update-ref", "--no-deref", ref, oid, "0" * len(oid))
    if lookup(repo, ref) != oid:
        raise ValueError("Could not confirm the pinned group")


def describe(root, revision):
    from oryx.capabilities import source_evidence
    repo = repository(root)
    ref = reference(revision)
    oid = lookup(repo, ref)
    if oid is None or git(repo, "cat-file", "-t", oid).strip() != b"tree":
        raise ValueError("Unknown approved group revision")
    raw = git(repo, "cat-file", "blob", oid + ":" + MANIFEST)
    manifest = storage.json_input(raw)
    if (not isinstance(manifest, dict) or set(manifest) != {"workspace", "approval", "changes"}
            or manifest["workspace"] != workspace_id(root) or not isinstance(manifest["changes"], list)):
        raise ValueError("Group belongs to a different Workspace or schema")
    approved = manifest["approval"]
    if approved is None:
        bound = hashlib.sha256(raw).hexdigest() == revision
    else:
        bound = isinstance(approved, dict) and set(approved) == {"path", "revision"} and approved["revision"] == revision
        if bound:
            receipt_bytes = git(repo, "cat-file", "blob", oid + ":" + approved["path"])
            receipt = storage.json_input(receipt_bytes)
            bound = (receipt["approval"]["revision"] == revision and any(
                row["path"] == approved["path"] and row["after"] == hashlib.sha256(receipt_bytes).hexdigest()
                for row in manifest["changes"]))
    if not bound:
        raise ValueError("The local history ref differs from the approved revision")
    paths = git(repo, "ls-tree", "-r", "-z", "--name-only", oid).decode().split("\x00")[:-1]
    if set(paths) != {MANIFEST, *(r["path"] for r in manifest["changes"] if r["after"] is not None)}:
        raise ValueError("Pinned tree contains unexplained changes")
    denied = source_evidence.denied_references(root)
    if any(source_evidence.withheld(denied, row["path"]) for row in manifest["changes"]):
        raise ValueError("Current access is unavailable for a group member")
    return {"revision": revision, "git_dir": str(repo), "ref": ref, "tree": oid, **manifest}
