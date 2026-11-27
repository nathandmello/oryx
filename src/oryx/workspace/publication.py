"""Commit a reviewed group of Workspace files under the shared repository lock.

Published paths stay ordinary files. Oryx observers pin one generation with
view(). A crash leaves one owner-private write-ahead intent. A reader completes
it or refuses a mixed view when a file has been edited independently.
"""
from contextlib import contextmanager
import ctypes
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
from uuid import UUID, uuid4

from . import identity, storage
from .location import workspace_id

PENDING = Path(".git/oryx-group-saves/pending.json")
MAX = 16 * 1024 * 1024
MAX_FILES = 1024


def digest(data):
    return None if data is None else hashlib.sha256(data.encode("utf-8")).hexdigest()


def target(root, name):
    parts = Path(identity.relative(name)).parts
    receipt = len(parts) == 2 and parts[0] == ".oryx-approvals" and parts[1].endswith(".json")
    if not receipt and (parts[0] not in identity.DOMAINS or any(p.startswith(".") for p in parts)):
        raise ValueError("Choose an approved Workspace record location")
    path = root / name
    if path.resolve() != path:
        raise ValueError("Use an unredirected publication destination")
    return path


def read(path):
    if not os.path.lexists(path):
        return None, None
    raw = identity.read_regular(path)
    info = path.lstat()
    if (info.st_uid != os.getuid() or info.st_mode & 0o7022
            or os.listxattr(path, follow_symlinks=False)):
        raise ValueError("Use an individually owned record without shared writes or extended attributes")
    return raw.decode("utf-8"), stat.S_IMODE(info.st_mode)


def change(root, path, original, after, mode=None):
    relative = path.relative_to(root).as_posix()
    current, current_mode = read(target(root, relative))
    # Legacy domain readers sometimes normalized CRLF. Bind the exact reviewed
    # bytes to the transaction while retaining the domain's comparison semantics.
    if current != original and (current is None or current.replace("\r\n", "\n") != original):
        raise ValueError(f"{relative} changed before group save")
    return {"path": relative, "before": digest(current), "after": after,
            "mode": mode if mode is not None else (current_mode if current_mode is not None else 0o600)}


def inspect(root, intent):
    if (not isinstance(intent, dict) or set(intent) - {"approval"} != {"schema", "id", "workspace", "changes"} or intent["schema"] != 1
            or not isinstance(intent["id"], str) or UUID(intent["id"]).hex != intent["id"]
            or intent["workspace"] != workspace_id(root) or not isinstance(intent["changes"], list)
            or not 1 <= len(intent["changes"]) <= MAX_FILES):
        raise ValueError("Invalid publication intent")
    seen = set()
    pending = []
    for row in intent["changes"]:
        if (not isinstance(row, dict) or set(row) != {"path", "before", "after", "mode"}
                or row["before"] is not None and (not isinstance(row["before"], str) or not identity.SHA.fullmatch(row["before"]))
                or row["after"] is not None and not isinstance(row["after"], str)
                or type(row["mode"]) is not int or not 0 <= row["mode"] <= 0o777 or row["mode"] & 0o133):
            raise ValueError("Invalid publication change")
        path = target(root, row["path"])
        if row["path"].casefold() in seen:
            raise ValueError("Duplicate publication destination")
        seen.add(row["path"].casefold())
        current, mode = read(path)
        if current == row["after"] and (current is None or mode == row["mode"]):
            preimage = slot(root, intent, row)
            if os.path.lexists(preimage):
                saved, previous_mode = read(preimage)
                if digest(saved) != row["before"] or previous_mode != row["mode"]:
                    raise ValueError(f"Concurrent edit preserved at {preimage}. Reconcile the publication before continuing")
            continue
        if digest(current) != row["before"] or current is not None and mode != row["mode"]:
            raise ValueError(f"{row['path']} changed during publication. Preserve the edit and reconcile before resuming")
        pending.append((path, current, row))
    return pending


def sync(directory):
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def ensure_parent(path):
    if path.exists():
        if path.resolve() != path or not path.is_dir():
            raise ValueError("Use a regular publication directory")
        return
    ensure_parent(path.parent)
    path.mkdir(mode=0o700)
    sync(path.parent)


def history_root(root):
    directory = root / PENDING.parent
    if directory.resolve() != directory:
        raise ValueError("Use unredirected local publication history")
    if directory.exists():
        info = directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise ValueError("Use owner-private group publication history")
    return directory


def slot(root, intent, row):
    # Keep displaced inodes privately with local Git metadata. A PM editor
    # holding an old file descriptor can still finish writing its original.
    folder = history_root(root) / intent["id"]
    if folder.resolve() != folder:
        raise ValueError("Use unredirected local publication history")
    if folder.exists():
        info = folder.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise ValueError("Use an owner-private transaction directory")
    return folder / hashlib.sha256(row["path"].encode()).hexdigest()


def swap(source, destination):
    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform.startswith("linux") and hasattr(libc, "renameat2"):
        status = libc.renameat2(-100, os.fsencode(source), -100, os.fsencode(destination), 2)
    elif sys.platform == "darwin" and hasattr(libc, "renamex_np"):
        status = libc.renamex_np(os.fsencode(source), os.fsencode(destination), 2)
    else:
        raise ValueError("Atomic exchange is unavailable on this system")
    if status:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code))


def replace(root, intent, path, current, row):
    if read(path)[0] != current:
        raise ValueError("A record changed during group publication")
    stage = slot(root, intent, row)
    ensure_parent(stage.parent)
    if row["after"] is None:
        storage.rename_exclusive(path, stage)
    else:
        if not os.path.lexists(stage):
            storage.replace_text(stage, None, row["after"], mode=row["mode"], durable=True)
        if read(stage) != (row["after"], row["mode"]):
            raise ValueError("Publication preimage changed. Retain it for reconciliation")
        ensure_parent(path.parent)
        if current is None:
            storage.rename_exclusive(stage, path)
        else:
            swap(stage, path)
    sync(stage.parent)
    sync(path.parent)


def recover(root):
    """Caller must hold the same Workspace writer lock as publish()."""
    path = history_root(root) / PENDING.name
    if not os.path.lexists(path):
        return
    if os.environ.get("PM_HUB_PROTECTED_ROOT") or os.environ.get("ORYX_PROPOSAL_HOST"):
        raise ValueError("The PM must resume the saved publication before this Workspace can be read")
    if path != path.resolve() or path.stat().st_mode & 0o077:
        raise ValueError("Use the owner-private publication intent")
    raw, _ = read(path)
    intent = storage.json_input(raw)
    pending = inspect(root, intent)
    history = slot(root, intent, intent["changes"][0]).parent
    ensure_parent(history)
    receipt = json.dumps({"workspace": intent["workspace"], "approval": intent.get("approval"), "changes": [
        {"path": row["path"], "before": row["before"], "after": digest(row["after"])} for row in intent["changes"]]},
        ensure_ascii=False, sort_keys=True) + "\n"
    metadata = history / "records.json"
    if not os.path.lexists(metadata):
        storage.replace_text(metadata, None, receipt, mode=0o600, durable=True)
    elif read(metadata)[0] != receipt:
        raise ValueError("Prior group history differs from the approved publication")
    from . import group_snapshot
    prepared = group_snapshot.prepare(root, intent, receipt.encode("utf-8"))
    for dest, current, row in pending:
        replace(root, intent, dest, current, row)
    if inspect(root, intent):
        raise ValueError("Group publication needs reconciliation")
    group_snapshot.publish(prepared)
    path.unlink()
    sync(path.parent)


@contextmanager
def view(core):
    """Pin a logical Oryx read. Legacy checkouts keep their existing behavior."""
    root = storage.selected_workspace(core)
    if root is None or not root.exists():
        yield
        return
    with storage.writer_lock(root):
        yield


def publish(root, changes, *, approval=None):
    if os.environ.get("PM_HUB_PROTECTED_ROOT") or os.environ.get("ORYX_PROPOSAL_HOST"):
        raise ValueError("Publish the reviewed group from the PM terminal")
    if os.environ.get(storage.SHARED_GROUP):
        raise ValueError("Group publication requires an individually owned Workspace")
    with storage.writer_lock(root):
        intent = {"schema": 1, "id": uuid4().hex, "workspace": workspace_id(root), "changes": list(changes)}
        if approval is not None:
            intent["approval"] = approval
        inspect(root, intent)
        raw = json.dumps(intent, ensure_ascii=False, separators=(",", ":")) + "\n"
        if len(raw.encode()) > MAX:
            raise ValueError("Group publication exceeds its supported size")
        path = history_root(root) / PENDING.name
        ensure_parent(path.parent)
        storage.replace_text(path, None, raw, mode=0o600, durable=True)
        recover(root)
