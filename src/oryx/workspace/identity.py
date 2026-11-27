"""Maintain record identities and verified historical bytes independently of a Workspace's location."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tempfile
from uuid import UUID, uuid5

from oryx.recovery import snapshot
from .location import workspace_id

STATE = Path(".oryx/state")
INDEX = STATE / "records.json"
BLOBS = STATE / "record-blobs"
MOVE = STATE / "record-move.json"
REFRESH = STATE / "record-refresh.json"
ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
SHA = re.compile(r"[a-f0-9]{64}")
NATIVE_ID = re.compile(rb"(?m)^\| ID \| ([a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}) \|\r?$")
DOMAINS = {"context", "workspace", "initiatives", "roadmaps", "goals", "experiments", "strategies", "problems",
           "backlogs", "forecasts", "handoffs", "customizations", "notes"}
LIMIT = 16 * 1024 * 1024


def relative(value):
    if not isinstance(value, str) or not value or len(value) > 1024:
        raise ValueError("Supply a bounded Workspace-relative path")
    path = PurePosixPath(value)
    if (path.is_absolute() or path.as_posix() != value or ".." in path.parts or not path.parts
            or "\\" in value or any(ord(c) < 32 for c in value)):
        raise ValueError("Use a canonical Workspace-relative path")
    return value


def eligible(name):
    parts = PurePosixPath(relative(name)).parts
    if parts[0] == "notes":
        from oryx.review.store import NOTE
        return bool(NOTE.fullmatch(name))
    return name == "README.md" or (parts[0] in DOMAINS and not any(p.startswith(".") or p.lower() in {"secrets", "sources", "profiles"}
                                                    for p in parts)
            and Path(name).suffix.lower() in {".md", ".json"})


def local_file(root, name):
    path = root / relative(name)
    if path.resolve() != path:
        raise ValueError("Redirected Workspace paths require separate review")
    return path


def read_regular(path):
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_NOATIME
    fd = os.open(path, flags)
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > LIMIT:
            raise ValueError("Use a bounded regular file owned by this Workspace")
        data = stream.read(LIMIT + 1)
        if len(data) > LIMIT or snapshot.stamp(before) != snapshot.stamp(os.fstat(stream.fileno())):
            raise ValueError("The file changed during the read")
        return data


def checksum(data):
    return hashlib.sha256(data).hexdigest()


def safe_directory(path):
    if path.resolve() != path:
        raise ValueError("Redirected Workspace state directory")
    if not path.parent.exists():
        safe_directory(path.parent)
    path.mkdir(mode=0o700, exist_ok=True)


def write_json(path, value):
    safe_directory(path.parent)
    if path.resolve() != path:
        raise ValueError("Redirected Workspace state file")
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        tmp = Path(stream.name)
        try:
            stream.write(snapshot.canonical(value) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
            os.replace(tmp, path)
            snapshot.sync_directory(path.parent)
        finally:
            tmp.unlink(missing_ok=True)


def put_blob(root, revision, data):
    if SHA.fullmatch(revision) is None or checksum(data) != revision:
        raise ValueError("Invalid record revision")
    path = local_file(root, str(BLOBS / revision))
    if path.exists():
        if checksum(read_regular(path)) != revision:
            raise ValueError("The saved historical revision changed")
        return
    safe_directory(path.parent)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        tmp = Path(stream.name)
        try:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
            os.link(tmp, path)
        finally:
            tmp.unlink(missing_ok=True)
    snapshot.sync_directory(path.parent)


def load(root):
    owner = workspace_id(root)
    file = local_file(root, str(INDEX))
    if not file.exists():
        return {"schema": 1, "workspace_id": owner, "records": {}}
    data = json.loads(read_regular(file))
    if not isinstance(data, dict) or set(data) != {"schema", "workspace_id", "records"} or data["schema"] != 1 or data["workspace_id"] != owner:
        raise ValueError("Invalid Workspace record index")
    registry = data["records"]
    if not isinstance(registry, dict):
        raise ValueError("Invalid Workspace records")
    paths = set()
    for rid, r in registry.items():
        if not ID.fullmatch(rid) or not isinstance(r, dict) or set(r) != {"path", "aliases", "revision", "history"}:
            raise ValueError("Invalid record identity or fields")
        aliases = r["aliases"]
        if (not isinstance(aliases, list) or not aliases or len(set(aliases)) != len(aliases) or paths.intersection(aliases)
                or any(not eligible(n) for n in aliases) or r["path"] not in aliases):
            raise ValueError("Conflicting record paths")
        paths.update(aliases)
        history = r["history"]
        if (not isinstance(history, list) or not history or r["revision"] not in history
                or any(not isinstance(h, str) or not SHA.fullmatch(h) for h in history)):
            raise ValueError("Invalid record revision history")
    return data


def legacy_id(data):
    if not data.startswith(b"<!-- pm:"):
        return None
    found = NATIVE_ID.findall(data)
    if len(found) > 1:
        raise ValueError("Several candidate IDs appear in the same record")
    return found[0].decode() if found else None


def inventory_names(root):
    if (root / "README.md").is_file():
        yield "README.md"
    for domain in sorted(DOMAINS):
        folder = root / domain
        if not folder.is_dir():
            continue
        if folder.is_symlink():
            raise ValueError("A registered record domain must be a regular directory")
        for basedir, dirs, files in os.walk(folder):
            dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d.lower() not in {"secrets","sources","profiles"})
            for name in sorted(files):
                full = (Path(basedir) / name).relative_to(root).as_posix()
                if eligible(full):
                    yield full


def prepared(root):
    original = load(root)
    before = snapshot.digest(original)
    by_path = {path: rid for rid, r in original["records"].items() for path in r["aliases"]}
    current = set()
    owners = set()
    additions = {}
    for name in inventory_names(root):
        data = read_regular(local_file(root, name))
        revision = checksum(data)
        rid = legacy_id(data) or by_path.get(name) or "rec-" + str(uuid5(UUID(original["workspace_id"]), name))
        if rid in owners or (name in by_path and by_path[name] != rid):
            raise ValueError("Conflicting or changed native record identity; preserve both inputs")
        owners.add(rid)
        record = original["records"].get(rid)
        if record is None:
            record = {"path": name, "aliases": [name], "history": [], "revision": revision}
            original["records"][rid] = record
        if record["path"] != name:
            raise ValueError("A record changed paths outside its reviewed move")
        transfer = transfer_status(root, rid)
        if transfer and transfer["status"] in {"pending","transferred"} and record["revision"] != revision:
            raise ValueError("A transferred or pending record has private edits requiring reconciliation")
        if revision not in record["history"]:
            record["history"].append(revision)
            additions[revision] = name
        record["revision"] = revision
        current.add(name)
    if any(r["path"] not in current for r in original["records"].values()):
        raise ValueError("An indexed record is missing; reconcile its move or deletion")
    return before, original, additions


def preview(root):
    before, result, _ = prepared(root)
    return {"before": before, "after": snapshot.digest(result), "records": result["records"]}


def refresh_receipt(root):
    path = local_file(root, str(REFRESH))
    if not path.exists():
        return None
    value = json.loads(read_regular(path))
    if (not isinstance(value,dict) or value.keys() != {"schema","workspace_id","plan","index"}
            or value["schema"] != 1 or value["workspace_id"] != workspace_id(root)
            or any(not isinstance(value[k],str) or not SHA.fullmatch(value[k]) for k in ("plan","index"))):
        raise ValueError("Invalid reviewed record refresh")
    return value


def refresh(root, expected):
    from storage import writer_lock
    from . import citations
    with writer_lock(root):
        if local_file(root, str(MOVE)).exists():
            raise ValueError("Complete the pending reviewed record move first")
        before, result, additions = prepared(root)
        after = snapshot.digest(result)
        receipt = {"schema":1, "workspace_id":result["workspace_id"], "plan":expected, "index":after}
        plan = {"before":before,"after":after,"records":result["records"]}
        if not (before == after and receipt == refresh_receipt(root)):
            snapshot.verified(plan, expected)
            for revision, name in additions.items():
                put_blob(root, revision, read_regular(local_file(root, name)))
            write_json(local_file(root, str(REFRESH)), receipt)
            citations.reconcile(root, result)
            write_json(local_file(root, str(INDEX)), result)
        else:
            citations.validate(root, result)
    return {"records": len(result["records"]), "revision": after}


def transfer_status(root, rid):
    from oryx.sharing.transfer import status
    data = status(root, rid)
    if data is not None and (data["workspace_id"] != workspace_id(root) or data["id"] != rid):
        raise ValueError("Transfer receipt belongs to a different Workspace or record")
    return data


def resolve(workspace, record, revision=None, *, follow_transfer=True):
    root = Path(workspace)
    registry = load(root)
    found = [(rid, r) for rid, r in registry["records"].items() if record == rid or record in r["aliases"]]
    if len(found) != 1:
        raise ValueError("Unknown or ambiguous record identity or citation")
    rid, row = found[0]
    transfer = transfer_status(root, rid)
    if follow_transfer and transfer and transfer.get("status") == "transferred":
        if not all(isinstance(transfer.get(k),str) and transfer[k] for k in ("organization","scope","official_commit")):
            raise ValueError("The transferred record lacks a verified destination")
        return {"workspace_id": registry["workspace_id"], "id": rid, "source_path": None, "path": None,
                "revision": None, "historical": False, "transfer_status": "transferred",
                "authoritative_destination": {k: transfer[k] for k in ("organization","scope","official_commit")}}
    selected = revision or row["revision"]
    if selected not in row["history"]:
        raise ValueError("Unknown revision for this record")
    physical = str(BLOBS / selected) if revision is not None else row["path"]
    if checksum(read_regular(local_file(root, physical))) != selected:
        raise ValueError("Record bytes changed; inspect and refresh the index before use")
    return {"workspace_id": registry["workspace_id"], "id": rid, "revision": selected, "path": row["path"],
            "source_path": physical, "historical": revision is not None, "transfer_status": transfer and transfer.get("status")}


def move(root, rid, destination, expected):
    from storage import writer_lock
    from oryx.recovery.snapshot import publish_new
    name = relative(destination)
    if not eligible(name):
        raise ValueError("Select an eligible record domain")
    with writer_lock(root):
        registry = load(root)
        row = registry["records"].get(rid)
        if row is None or row["revision"] != expected or (transfer_status(root, rid) or {}).get("status") in {"pending","transferred"}:
            raise ValueError("Record revision or ownership changed")
        source_name = row["path"]
        journal = local_file(root, str(MOVE))
        receipt = json.loads(read_regular(journal)) if journal.exists() else None
        if not receipt and source_name == name:
            return resolve(root, rid)
        if receipt:
            if (receipt.get("id"), receipt.get("to"), receipt.get("revision")) != (rid, name, expected):
                raise ValueError("A different reviewed record move is pending")
            source_name = receipt["from"]
        else:
            # Existing governed files have path-bound readers and approval hashes.
            # New independent domain documents can move without invalidating those readers.
            from . import layout
            if any(layout.governed_kind(n) or layout.initiative_work_identity(n) for n in (source_name, name)):
                raise ValueError("This product workflow binds its domain path. Retain the original home")
            if source_name.split("/")[0] in {"workspace","context","customizations","notes","README.md"} or name.split("/")[0] in {"workspace","context","customizations","notes","README.md"}:
                raise ValueError("A legacy caller binds this path; retain the original while migrating that caller")
            if any(name in other["aliases"] for other in registry["records"].values()):
                raise ValueError("The destination collides with an existing citation")
        source = local_file(root, source_name)
        target = local_file(root, name)
        if not receipt:
            if target.exists() or checksum(read_regular(source)) != expected:
                raise ValueError("The source or destination changed")
            write_json(journal, {"id": rid, "from": source_name, "to": name, "revision": expected})
        if source.exists():
            if target.exists() or checksum(read_regular(source)) != expected:
                raise ValueError("A concurrent edit requires reconciliation")
            safe_directory(target.parent)
            publish_new(source, target)
            snapshot.sync_directory(source.parent)
        if checksum(read_regular(target)) != expected:
            raise ValueError("The moved revision changed")
        if name not in row["aliases"]:
            row["aliases"].append(name)
        row["path"] = name
        write_json(local_file(root, str(INDEX)), registry)
        journal.unlink()
        snapshot.sync_directory(journal.parent)
        return resolve(root, rid)
