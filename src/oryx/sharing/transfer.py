"""Fence local ownership while a remote decision is pending; keep every source byte."""
from pathlib import Path
import re
from uuid import UUID

from oryx.governance.common import SHA, canonical, digest, identifier, record_id, shape
from oryx.workspace.identity import read_regular, relative, resolve
from oryx.governance.files import directory, read, save

FIELDS = ("id", "workspace_id", "source_path", "source_revision", "organization", "scope", "proposal", "status", "official_commit")


def check(value, name):
    shape(value, FIELDS)
    if digest(record_id(value["id"]).encode()) + ".json" != name or not SHA.fullmatch(value["proposal"]) or not SHA.fullmatch(value["source_revision"]):
        raise ValueError("Invalid transfer identity, proposal or revision")
    if str(UUID(value["workspace_id"]))!=value["workspace_id"]:
        raise ValueError("Invalid transfer Workspace identity")
    identifier(value["organization"])
    identifier(value["scope"])
    relative(value["source_path"])
    if value["official_commit"] is not None and not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})",value["official_commit"]):
        raise ValueError("Invalid transfer destination commit")
    if value["status"] not in {"pending","transferred","closed"} or ((value["official_commit"] is None) != (value["status"] != "transferred")):
        raise ValueError("Invalid transfer state")
    return value


def location(private, rid, create=False):
    return directory(private, ".oryx/state/transfers", create) / (digest(record_id(rid).encode()) + ".json")


def status(private, rid):
    path = location(private, rid)
    if path.is_symlink():
        raise ValueError("Redirected transfer marker")
    return check(read(path), path.name) if path.exists() else None


def source(private, rid):
    row = resolve(private, rid, follow_transfer=False)
    if row.get("transfer_status") in {"pending","transferred"}:
        raise ValueError("Resolve the authoritative transfer destination before using private bytes")
    path = Path(private) / row["source_path"]
    if path.resolve() != path or path.stat().st_nlink != 1:
        raise ValueError("Transfer requires a regular current record")
    before=path.stat()
    data=read_regular(path)
    after=path.stat()
    if (before.st_ino,before.st_mtime_ns)!=(after.st_ino,after.st_mtime_ns) or digest(data)!=row["revision"]:
        raise ValueError("Private record changed; review the current bytes")
    from oryx.workspace.portable import pending_timestamps, source_mtime
    stamp = source_mtime(pending_timestamps(private), row["path"], row["id"], row["revision"], after.st_mtime_ns)
    return row, data, after.st_mtime if stamp is not None else None


def begin(private, intent, organization, actor):
    from storage import writer_lock
    with writer_lock(private):
        return _begin_locked(private,intent,organization,actor)


def _begin_locked(private,intent,organization,actor):
    key = digest(canonical([organization, actor, digest(canonical(intent))]))
    previous=status(private,intent["id"])
    if previous and previous["status"] != "closed":
        if previous["proposal"] != key:
            raise ValueError("Resolve the existing ownership transfer first")
        return previous
    src, data, _ = source(private, intent["id"])
    if intent["source"] != {"workspace_id":src["workspace_id"], "id":src["id"], "revision":src["revision"]} or data.decode() != intent["content"]:
        raise ValueError("Private source or its identity changed; review the current transfer")
    path=location(private,src["id"],True)
    current={"id":src["id"],"workspace_id":src["workspace_id"],"source_path":src["path"],"source_revision":src["revision"],
             "organization":organization,"scope":intent["scope"],"proposal":key,"status":"pending","official_commit":None}
    save(path,current,expected=previous)
    return current


def reconcile(private, rid, request):
    previous=status(private,rid)
    if not previous:
        raise ValueError("No pending local ownership transfer")
    peer=request("scope", {"scope":previous["scope"]})
    if peer["organization"]!=previous["organization"] or peer["scope"]!=previous["scope"]:
        raise ValueError("Cannot verify the registered destination for this transfer")
    remote=request("reconcile", {"proposal":previous["proposal"]})
    if remote["scope"] != previous["scope"] or remote["id"] != previous["proposal"]:
        raise ValueError("Cannot verify destination transfer receipt")
    if remote["status"] == "merged":
        official=request("read",{"scope":previous["scope"],"kind":"record","id":rid,"revision":remote["candidate"]})
        owner=request("owner",{"id":rid})
        if (official["record"]["id"]!=rid or official["scope"]!=previous["scope"] or official["commit"]!=remote["candidate"]
                or owner["scope"]!=previous["scope"] or digest(official["record"]["content"].encode())!=previous["source_revision"]):
            raise ValueError("Merged record does not match the originally reviewed private bytes")
        updated={**previous,"status":"transferred","official_commit":remote["candidate"]}
    elif remote["status"] == "closed":
        updated={**previous,"status":"closed","official_commit":None}
    else:
        return previous
    save(location(private,rid),updated,expected=previous)
    return updated
