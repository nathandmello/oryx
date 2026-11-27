"""Review and adopt a preserved, offline, format-2 Workspace beside its original."""
import json
import os
import re
from pathlib import Path
import tempfile
from uuid import UUID, uuid5

from oryx.recovery import snapshot
from . import identity, citations

RECEIPT = identity.STATE / "adoption.json"
HISTORY = identity.STATE / "record-git-history.json"
PORTABLE_RECEIPT = identity.STATE / "portable-restore.json"
NAMESPACE = UUID("366615f3-cb1d-416d-a612-630a80f22d54")
MAX_COMMITS = 2048
MAX_VERSIONS = 50000
MAX_OCCURRENCES = 200000
MAX_HISTORY_BYTES = 512 * 1024 * 1024


def destination_path(source, destination):
    return snapshot.check_destination(source, Path(destination))


def purpose_path(name):
    parts = name.split("/")
    if len(parts) >= 3 and parts[0] == "workspace" and parts[1] in identity.DOMAINS - {"workspace","context","customizations"}:
        return "/".join(parts[1:])
    return name


def preview(source, destination):
    source = snapshot.local(source)
    destination = destination_path(source, destination)
    manifest = snapshot.inspect(source)
    metadata = json.loads(identity.read_regular(source / "settings.json"))
    if metadata.get("workspace_format") != 2 or metadata.get("system_version") != "0.16.0":
        raise ValueError("This adoption is qualified for a 0.16.0 format-2 Workspace")
    if os.path.lexists(source / ".oryx"):
        raise ValueError("The source already has .oryx state; reconcile its identity before adoption")
    names = {}
    rows = []
    for item in manifest["entries"]:
        name = item["path"]
        if name == "." or name.startswith(".git/") or name == ".git":
            continue
        if name.casefold() in names:
            raise ValueError(f"Case-folding collision between {name} and {names[name.casefold()]}")
        names[name.casefold()] = name
        if item["kind"] == "directory":
            continue
        indexed = item["kind"] == "file" and identity.eligible(name)
        rows.append({"path": name, "kind": item["kind"], "mode": item["mode"],
                     "revision": item.get("sha256"), "disposition": "identity and history" if indexed else "preserve opaque",
                     "domain_path": purpose_path(name) if indexed else name})
    if len({r["domain_path"].casefold() for r in rows}) != len(rows):
        raise ValueError("Two existing files claim the same purpose-based path")
    digest = snapshot.digest(manifest)
    return {"schema": 1, "source": str(source), "destination": str(destination), "inventory": digest,
            "workspace_id": str(uuid5(NAMESPACE, str(source) + "\0" + digest)),
            "records": rows, "operation": "separate format-2 adoption",
            "git": "Preserve original refs, objects, index, working files, ignored files and local preimage"}


def git_versions(root, registry):
    records = registry["records"]
    paths = {name: rid for rid, row in records.items() for name in row["aliases"]}
    versions = {}
    processed = {}
    occurrences = 0
    total = 0
    commits = snapshot.git_output(root, "rev-list", "--all", f"--max-count={MAX_COMMITS + 1}").decode().splitlines()
    if len(commits) > MAX_COMMITS:
        raise ValueError("Git history exceeds this adoption's reviewed size limit")

    def record_version(mode, oid, name, location):
        nonlocal total, occurrences
        if mode not in (b"100644", b"100755") or not identity.eligible(name):
            return
        if oid not in processed:
            size = int(snapshot.git_output(root, "cat-file", "-s", oid))
            if size > identity.LIMIT or total + size > MAX_HISTORY_BYTES or len(processed) >= MAX_VERSIONS:
                raise ValueError("Record history exceeds the supported preservation limits")
            data = snapshot.git_output(root, "cat-file", "blob", oid)
            total += size
            processed[oid] = (identity.checksum(data), identity.legacy_id(data))
        revision, historical_id = processed[oid]
        rid = historical_id or paths.get(name)
        if rid not in records:
            return  # Historical-only records remain in the exact private Git history.
        row = records[rid]
        if name not in row["aliases"]:
            if name in paths and paths[name] != rid:
                raise ValueError("A historical path maps to different record owners")
            row["aliases"].append(name)
            paths[name] = rid
        if revision not in row["history"]:
            identity.put_blob(root, revision, snapshot.git_output(root, "cat-file", "blob", oid))
            row["history"].append(revision)
        occurrences += 1
        if occurrences > MAX_OCCURRENCES:
            raise ValueError("Record history exceeds the supported citation occurrence limit")
        versions.setdefault(rid, {}).setdefault(revision, []).append({"path": name, "git": location})

    for commit in commits:
        for item in snapshot.git_output(root, "ls-tree", "-rz", commit).split(b"\0"):
            if item:
                meta, path = item.split(b"\t", 1)
                mode, kind, oid = meta.split()
                if kind == b"blob":
                    record_version(mode, oid.decode(), path.decode(), commit)
    for item in snapshot.git_output(root, "ls-files", "--stage", "-z").split(b"\0"):
        if item:
            meta, path = item.split(b"\t", 1)
            mode, oid, stage = meta.split()
            if stage != b"0":
                raise ValueError("Unmerged index entries require review")
            record_version(mode, oid.decode(), path.decode(), "index")
    return versions


def validate_receipt(root):
    path = identity.local_file(root, str(RECEIPT))
    if not path.exists():
        return None
    data = json.loads(identity.read_regular(path))
    keys = {"schema","workspace_id","plan","source_inventory","source","destination","backup","status"}
    if (not isinstance(data, dict) or set(data) - {"legacy_core"} != keys or data["schema"] != 1
            or data["workspace_id"] != identity.workspace_id(root) or data["status"] != "adopted-separate-copy"
            or any(not isinstance(data[k],str) or not identity.SHA.fullmatch(data[k]) for k in ("plan","source_inventory"))
            or any(not isinstance(data[k],str) or not Path(data[k]).is_absolute() for k in ("source","destination","backup"))):
        raise ValueError("Invalid adoption receipt")
    check_proofs(data.get("legacy_core", {}))
    return data


def check_proofs(values):
    if not isinstance(values,dict) or any(not identity.ID.fullmatch(rid) or not isinstance(tokens,list)
            or not all(isinstance(t,str) and identity.SHA.fullmatch(t) for t in tokens) for rid,tokens in values.items()):
        raise ValueError("Invalid adopted Core link proofs")
    return values


def origin_proofs(root):
    receipt = validate_receipt(root)
    if receipt is None and (root / PORTABLE_RECEIPT).is_file():
        from . import portable
        receipt = portable.check_receipt(root)
    return (receipt or {}).get("legacy_core", {})


def checked_paths(private):
    root = Path(private)
    if not (root / ".oryx/workspace.json").exists():
        return set()
    included = set()
    if validate_receipt(root):
        included.add(str(RECEIPT))
    registry = identity.load(root)
    if (root / identity.INDEX).exists():
        included.add(str(identity.INDEX))
    digests = {h for r in registry["records"].values() for h in r["history"]}
    for sha in digests:
        path = str(identity.BLOBS / sha)
        if identity.checksum(identity.read_regular(identity.local_file(root, path))) != sha:
            raise ValueError("A historical record blob differs from its declared revision")
        included.add(path)
    git_file = identity.local_file(root, str(HISTORY))
    if git_file.exists():
        history = json.loads(identity.read_regular(git_file))
        if not isinstance(history, dict) or not history.keys() <= registry["records"].keys():
            raise ValueError("Invalid Git record history")
        for rid, revisions in history.items():
            row = registry["records"][rid]
            for rev, aliases in revisions.items():
                if rev not in row["history"] or not isinstance(aliases, list):
                    raise ValueError("Unknown historical record revision")
                for alias in aliases:
                    if (not isinstance(alias, dict) or alias.keys() != {"path","git"} or alias["path"] not in row["aliases"]
                            or not isinstance(alias["git"],str) or not (alias["git"] == "index" or
                            re.fullmatch("[a-f0-9]{40}|[a-f0-9]{64}", alias["git"]))):
                        raise ValueError("Invalid historical citation")
        included.add(str(HISTORY))
    if (root / citations.FILE).exists():
        citations.validate(root, registry)
        included.add(str(citations.FILE))
    if identity.refresh_receipt(root):
        included.add(str(identity.REFRESH))
    if (root / identity.MOVE).exists():
        raise ValueError("A record move is pending; retry the reviewed move")
    if (root / PORTABLE_RECEIPT).exists():
        from . import portable
        portable.check_receipt(root)
        included.add(str(PORTABLE_RECEIPT))
    return included


def adopt(source, destination, backup, expect):
    source = snapshot.local(source)
    destination = snapshot.local(destination)
    backup = snapshot.local(backup)
    if destination.exists():
        receipt = validate_receipt(destination)
        if (receipt and receipt["plan"] == expect and receipt["source"] == str(source)
                and receipt["destination"] == str(destination) and receipt["backup"] == str(backup)):
            checked_paths(destination)
            return receipt
        raise ValueError("The destination already exists; preserve it and review separately")
    plan = preview(source, destination)
    snapshot.verified(plan, expect)
    if source in backup.parents or destination == backup or destination in backup.parents:
        raise ValueError("Choose an independent private backup location")
    digest = plan["inventory"]
    if not backup.exists():
        snapshot.backup(source, backup, digest)
    with tempfile.TemporaryDirectory(dir=destination.parent, prefix=".oryx-adopt-") as folder:
        staging = Path(folder) / "pm"
        snapshot.restore(backup, staging, digest)
        snapshot.check_repository(staging)
        staging.chmod(0o700)  # Access to the separately published copy is personal to the PM.
        identity.write_json(staging / ".oryx/workspace.json", {"id": plan["workspace_id"]})
        registry_before, registry, additions = identity.prepared(staging)
        for revision, name in additions.items():
            identity.put_blob(staging, revision, identity.read_regular(identity.local_file(staging, name)))
        history = git_versions(staging, registry)
        for row in registry["records"].values():
            logical = purpose_path(row["path"])
            if logical not in row["aliases"]:
                row["aliases"].append(logical)
        identity.write_json(staging / identity.INDEX, registry)
        identity.write_json(staging / HISTORY, history)
        receipt = {"schema": 1, "workspace_id": plan["workspace_id"], "plan": expect, "source_inventory": digest,
                   "source": str(source), "destination": str(destination), "backup": str(backup),
                   "status": "adopted-separate-copy"}
        proofs = {}
        for rid,row in registry["records"].items():
            if row["path"].endswith(".md"):
                raw = identity.read_regular(identity.local_file(staging, row["path"]))
                tokens = [v[2] for v in citations.legacy_proofs(rid, row["path"], raw).values()]
                if tokens:
                    proofs[rid] = sorted(set(tokens))
        receipt["legacy_core"] = proofs
        identity.write_json(staging / RECEIPT, receipt)
        citations.reconcile(staging, registry, history)
        checked_paths(staging)
        with snapshot.idle_writer(source):
            current, _ = snapshot.inventory(source)
            snapshot.verified(current, digest)
            snapshot.publish_new(staging, destination)
    return receipt

def legacy_resource(private, workspace_relative_path, raw_href, expression):
    if not raw_href.startswith("../"):
        return None
    name = str(workspace_relative_path)
    registry = identity.load(private)["records"]
    for rid,row in registry.items():
        if row["path"] != name:
            continue
        trusted = origin_proofs(private).get(rid, [])
        if not trusted:
            return None
        raw = identity.read_regular(identity.local_file(private, name))
        native = identity.legacy_id(raw)
        if (native or not rid.startswith("rec-")) and native != rid:
            return None
        proof = citations.legacy_proofs(rid, name, raw).get(expression)
        if proof and proof[0] == raw_href and proof[2] in trusted:
            return proof[1]
    return None
