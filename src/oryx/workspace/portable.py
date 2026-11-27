"""Export explicitly reviewed text revisions for one audience into an inert portable Workspace."""
import json
import os
from pathlib import Path
import re
import stat
import sys
import subprocess
import tempfile
import zipfile

from oryx.recovery import snapshot
from . import identity, citations, location

FORMAT = "oryx-reviewed-portable-v1"
MANIFEST = "manifest.json"
REVIEW = "review.json"
RECEIPT = identity.STATE / "portable-restore.json"
MAX_TOTAL = 256 * 1024 * 1024
MAX_FILES = 8192
DRAFT = re.compile(r"\.oryx/staging/review/([0-9a-f]{64})\.json")
CHECKPOINT = re.compile(r"\.oryx/state/workflows/([0-9a-f]{64})\.json")
BLOCKED = {"secrets", "credentials", "accounts", "profiles", "sources", "transcripts", "journals", "hooks",
           "node_modules", "recordings", "tokens", "authorizations", "sessions", "consents", "receipts", "policies"}
SENSITIVE = re.compile(rb"-----BEGIN [^\n]*PRIVATE KEY-----|(?:gh[pousr]_|github_pat_|sk-(?:proj-)?|xox[baprs]-)[A-Za-z0-9_-]{12,}|\bAKIA[A-Z0-9]{16}\b|"
                       rb"https?://[^\s/:@]+:[^\s/@]+@|(?:api[_-]?key|password|access[_-]?token|client[_-]?secret|refresh[_-]?token)\s*[\x22']?\s*[:=]\s*[\x22']?[^\s<{}\x22']{4,}",
                       re.I)


def eligible(name):
    parts = Path(identity.relative(name)).parts
    if SENSITIVE.search(name.encode("utf-8")):
        return False
    if DRAFT.fullmatch(name) or CHECKPOINT.fullmatch(name):
        return True
    if name in {".oryx/customizations/rules.json", ".oryx/customizations/settings.json",
                ".oryx/state/handoffs/index.json", ".oryx/state/onboarding/review.json"}:
        return True
    if name == ".gitignore":
        return True
    if len(parts) == 2 and parts[0] == ".oryx-approvals":
        return bool(re.fullmatch(r"[a-z0-9-]+\.json", parts[1]))
    if name == "settings.json":
        return False
    if any(p.startswith(".") or p.casefold() in BLOCKED or Path(p).stem.casefold() in BLOCKED or any(
            word in p.casefold() for word in ("transcript","credential","cookie","password","private-key","private_key")) for p in parts):
        return False
    if parts[0] == "notes":
        from oryx.review.store import NOTE
        return bool(NOTE.fullmatch(name))
    if parts[0] == "customizations":
        return name in {"customizations/settings.json", "customizations/rules.json"}
    return (len(parts) == 1 or parts[0] in identity.DOMAINS or parts[0] == "notes") and Path(name).suffix.lower() in {".md",".txt",".json",".csv"}


def approved_bytes(name, content):
    if len(content) > identity.LIMIT or b"\0" in content or SENSITIVE.search(content):
        raise ValueError(f"Held nonportable or credential-like data in {name}")
    content.decode("utf-8")
    if name in {"customizations/rules.json", ".oryx/customizations/rules.json"}:
        import overrides
        obj = json.loads(content)
        if (obj.get("reporting") is not False or obj.get("pending") or obj.get("reports")
                or set(obj) - {"rules","retired","reporting","reports","pending"}):
            raise ValueError("Reporting grants, queues and prior external deliveries stay with the original Workspace")
        overrides.validate_rules(obj["rules"])
    if name in {"workspace/handoffs/index.json", ".oryx/state/handoffs/index.json"}:
        obj = json.loads(content)
        if obj.keys() != {"work","grants"} or obj["grants"] or any(k in content for k in (
                b'"journal"', b'"journal_reference_scope"', b'"journal_required"', b'"native"')):
            raise ValueError("Transcript grants or host bindings need separate handoff review")
    return identity.checksum(content)


def approved_selection(policy):
    if (not isinstance(policy,dict) or set(policy) != {"audience","files","lineage"}
            or policy["lineage"] != "new-private-history" or not isinstance(policy["audience"],str)
            or SENSITIVE.search(policy["audience"].encode()) or any(ord(c) < 32 for c in policy["audience"])
            or not policy["audience"].strip() or len(policy["audience"]) > 200 or not isinstance(policy["files"],dict)
            or not 0 < len(policy["files"]) <= MAX_FILES):
        raise ValueError("Review the audience, new-private-history lineage and each eligible file")
    for name, revisions in policy["files"].items():
        if not eligible(name) or not isinstance(revisions, list) or not all(isinstance(r,str) and identity.SHA.fullmatch(r) for r in revisions):
            raise ValueError(f"Unsupported permission or record class for portable export: {name}")
    if len({name.casefold() for name in policy["files"]}) != len(policy["files"]):
        raise ValueError("Portable file paths collide")
    return policy


def git_files(root):
    def mapping(raw, index):
        out = {}
        for item in raw.split(b"\0"):
            if not item:
                continue
            meta, path = item.split(b"\t",1)
            mode, tag, last = meta.split()
            if index and last != b"0":
                raise ValueError("Resolve unmerged index entries before export")
            if not index and tag != b"blob":
                raise ValueError("Non-file Git entries need a separate export")
            out[path.decode()] = (mode, (tag if index else last).decode())
        return out
    refs = snapshot.git_output(root, "for-each-ref", "--format=%(objectname)")
    index = mapping(snapshot.git_output(root, "ls-files", "--stage", "-z"), True)
    if not refs.strip():
        # A fresh repository with no commits may have a populated index.
        test = (root / ".git/HEAD").read_text().strip()
        if not test.startswith("ref: "):
            raise ValueError("Detached Git history needs an explicit export")
        return {}, index, None
    head = snapshot.git_output(root, "rev-parse", "--verify", "HEAD").decode().strip()
    return mapping(snapshot.git_output(root, "ls-tree", "-rz", head), False), index, head


def protected_notes(root, *args):
    core = Path(__file__).resolve().parents[3]
    env = {"PATH": os.defpath, "LC_ALL": "C", "ORYX_WORKSPACE": str(root), "PYTHONDONTWRITEBYTECODE": "1"}
    result = subprocess.run([sys.executable, "-B", str(core / "bin/oryx"), "review", *args], stdin=subprocess.DEVNULL,
                            env=env, capture_output=True, timeout=60)
    if result.returncode:
        raise ValueError("Protected notes need an intact generation selected by the PM")
    return json.loads(result.stdout)


def validate_durable(root, names):
    from oryx.workflows import checkpoints
    import work_handoffs
    for name in names:
        if proposal := DRAFT.fullmatch(name):
            if protected_notes(root, "show", proposal[1])["state"] != "pending":
                raise ValueError("Previously decided or stale protected drafts cannot be replayed")
        if checkpoint := CHECKPOINT.fullmatch(name):
            _, _, doc = checkpoints.get(root, checkpoint[1])
            if doc is None or doc["state"]["workspace"] != identity.workspace_id(root):
                raise ValueError("Workflow checkpoint belongs to another Workspace")
            s = doc["state"]
            _, handoffs = work_handoffs.read(root)
            h = handoffs["work"].get(s["handoff"])
            if (not h or h["status"] != "open" or h["revision"] != s["handoff_revision"]
                    or h["task"]["scope"] != s["scope"] or h["task"].get("evidence")):
                raise ValueError("The workflow requires its verified, source-independent open handoff")


def approved_pairs(files, blobs, *, purpose):
    """Only transfer an already-applied batch receipt paired with its exact register."""
    from oryx.capabilities import initiative_store
    legacy_handoff = "workspace/handoffs/index.json"
    handoff = ".oryx/state/handoffs/index.json" if purpose else legacy_handoff
    for former, current in ((legacy_handoff, ".oryx/state/handoffs/index.json"),
                            ("workspace/onboarding/review.json", ".oryx/state/onboarding/review.json"),
                            ("customizations/settings.json", ".oryx/customizations/settings.json"),
                            ("customizations/rules.json", ".oryx/customizations/rules.json")):
        if (former if purpose else current) in files:
            raise ValueError("Selected private records must use the source Workspace layout")
    for name, row in files.items():
        draft = DRAFT.fullmatch(name)
        checkpoint = CHECKPOINT.fullmatch(name)
        if draft or checkpoint:
            if row["head"] or row["index"] or row["history"] or not row["working"]:
                raise ValueError("Select only the current private draft or workflow checkpoint")
            content = blobs[row["working"]]
            doc = json.loads(content)
            if draft:
                if identity.checksum(content) != draft[1] or doc["request"].keys() != {"current_behavior","reason","effect","changes"}:
                    raise ValueError("Only pending protected note drafts qualify for portable staging")
                for change in doc["request"]["changes"]:
                    base = change["base"]
                    if base != files.get(change["path"], {}).get("working"):
                        raise ValueError("Select the exact protected note required by its pending draft")
            elif handoff not in files:
                raise ValueError("Select the owning handoff before its workflow checkpoint")
        if not name.startswith(".oryx-approvals/"):
            continue
        product = Path(name).stem
        register_path = f"backlogs/{product}/initiatives.json"
        match = files.get(register_path if purpose else "workspace/" + register_path)
        if not match:
            raise ValueError("Review the initiative approval and its bound register together")
        for layer in ("working", "head", "index"):
            if row[layer]:
                if not match[layer]:
                    raise ValueError("An incomplete initiative receipt could authorize replay")
                receipt = json.loads(blobs[row[layer]])
                envelope = json.loads(blobs[match[layer]])
                if receipt.get("product") != product or initiative_store.fingerprint(envelope) != receipt.get("after"):
                    raise ValueError("Pending or mismatched initiative approvals must remain local")
                initiative_store.validate_receipt_comparison(product, receipt)
                comparison = receipt.get("comparison")
                if comparison and files.get(comparison["path"], {}).get(layer) != identity.checksum(comparison["text"].encode()):
                    raise ValueError("Select the exact reviewed roadmap together with its approval")
                initiative_store.check_committed_batch(envelope, receipt)


def exported_bindings(root, selected, registry):
    from . import adoption
    edges = citations.load(root)
    legacy = adoption.origin_proofs(root)
    known = {row["id"]: {r for r in [row["working"], row["head"], row["index"], *row["history"]] if r}
             for row in selected.values() if row["id"] and row["working"]}
    bindings = {}
    for rid, revisions in known.items():
        originals = registry[rid]
        # Every exported alias is shown in the private preview. Exclude restricted paths.
        aliases = [a for a in originals["aliases"] if eligible(a)]
        out = {}
        for revision, links in edges.get(rid, {}).items():
            if revision not in revisions:
                continue
            out[revision] = {}
            for href, edge in links.items():
                if edge["status"] == "record" and edge["revision"] not in known.get(edge["id"], set()):
                    edge = {"status": "historical-target-unverified"}
                out[revision][href] = edge
        retained = []
        if legacy.get(rid):
            name = originals["path"]
            raw = identity.read_regular(identity.local_file(root, name))
            retained = sorted({p[2] for p in citations.legacy_proofs(rid,name,raw).values()} & set(legacy[rid]))
        bindings[rid] = {"aliases": aliases, "citations": out, "legacy_core":retained}
    return bindings


def pending_timestamps(root):
    if identity.local_file(root, str(RECEIPT)).exists():
        return check_receipt(root).get("missing_times", {})
    return {}


def source_mtime(missing, name, rid, revision, observed):
    # Bind the uncertainty to the exact restored version, including after a record move.
    at_path = missing.get(name)
    if at_path is not None and (at_path["revision"], at_path["restore_mtime_ns"]) == (revision, observed):
        return None
    if rid and name not in missing:
        for item in missing.values():
            if (item["id"], item["revision"], item["restore_mtime_ns"]) == (rid, revision, observed):
                return None
    return observed


def valid_time(value):
    # Python's representable UTC years. The destination filesystem must also preserve the exact value.
    return type(value) is int and -62135596800 * 10**9 <= value < 253402300800 * 10**9


def restore_timestamps(root, files):
    missing = {}
    for name, row in files.items():
        if row["working"] is None:
            continue
        path = identity.local_file(root, name)
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ValueError("A portable record changed during timestamp recovery")
            when = row.get("mtime_ns")
            if when is None:
                missing[name] = {"id": row["id"], "revision": row["working"], "restore_mtime_ns": info.st_mtime_ns}
            else:
                os.utime(fd, ns=(info.st_atime_ns, when))
                os.fsync(fd)
                if os.fstat(fd).st_mtime_ns != when:
                    raise ValueError("The destination filesystem cannot preserve the source modification time")
        finally:
            os.close(fd)
    return missing


def review(root, destination, policy, *, payload=False):
    root = snapshot.local(root)
    policy = approved_selection(policy)
    destination = snapshot.check_destination(root, destination)
    sid = identity.workspace_id(root)
    current = snapshot.inspect(root)
    snapshot.check_repository(root)
    head, index, old_head = git_files(root)
    entries = {r["path"]:r for r in current["entries"] if r["kind"] != "directory"}
    registry = identity.load(root)["records"]
    missing_times = pending_timestamps(root)
    notes = [name for name in policy["files"] if name.startswith("notes/")]
    note_digests = {r["path"]: r["revision"] for r in protected_notes(root, "read", *notes)["records"]} if notes else {}
    governed = []
    if notes:
        metadata = json.loads(identity.read_regular(identity.local_file(root, "notes/.oryx-review.json")))
        governed = sorted(n for n in metadata.get("governing", []) if "notes/"+n in notes)
    by_name = {row["path"]:(rid,row) for rid,row in registry.items()}
    blobs = {}
    total = 0
    selected = {}
    def remember(name, data):
        nonlocal total
        rev = approved_bytes(name, data)
        if rev not in blobs:
            total += len(data)
            if total > MAX_TOTAL:
                raise ValueError("Portable data exceeds the supported archive size")
            blobs[rev] = data
        return rev
    for name, history in sorted(policy["files"].items()):
        row = {"working":None,"index":None,"head":None,"history":[]}
        if name in by_name and (identity.transfer_status(root, by_name[name][0]) or {}).get("status") in {"pending", "transferred"}:
            raise ValueError("Resolve shared ownership before portable export")
        if name in entries:
            r = entries[name]
            if r["kind"] != "file" or r["mode"] & 0o111:
                raise ValueError(f"Executable or linked work needs separate eligibility review: {name}")
            row["working"] = remember(name, identity.read_regular(identity.local_file(root, name)))
        for layer, source in (("head", head), ("index", index)):
            if name in source:
                mode, oid = source[name]
                if mode != b"100644" or int(snapshot.git_output(root, "cat-file", "-s", oid)) > identity.LIMIT:
                    raise ValueError("An unreviewable committed or staged version must stay local")
                row[layer] = remember(name, snapshot.git_output(root, "cat-file", "blob", oid))
        for sha in sorted(set(history)):
            if name not in by_name or sha not in by_name[name][1]["history"]:
                raise ValueError("A selected historical version is outside its identified record")
            blob = identity.read_regular(identity.local_file(root, str(identity.BLOBS / sha)))
            if remember(name, blob) != sha:
                raise ValueError("Historical file changed")
            row["history"].append(sha)
        if not any(row.values()):
            raise ValueError("Selected file is absent from every layer")
        if name in note_digests and row["working"] != note_digests[name]:
            raise ValueError("A protected note changed after its reviewed generation")
        if identity.eligible(name) and row["working"] and (name not in by_name or by_name[name][1]["revision"] != row["working"]):
            raise ValueError("Review and refresh record identities before exporting changed records")
        row["id"] = by_name.get(name,(None,None))[0]
        if row["working"]:
            row["mtime_ns"] = source_mtime(missing_times, name, row["id"], row["working"], entries[name]["mtime_ns"])
        selected[name] = row
    approved_pairs(selected, blobs, purpose=location.purpose_layout(root))
    validate_durable(root, selected)
    grant_file = identity.local_file(root, ".state/ingestion-grants.json")
    if grant_file.exists():
        grants = json.loads(identity.read_regular(grant_file))
        if grants != {"grants": {}, "revoked": {}}:
            raise ValueError("Source-use restrictions need an independently verified export resolution")
    metadata = json.loads(identity.read_regular(identity.local_file(root, "settings.json")))
    # Use only a fixed subset; old remotes, configuration, hook code and credentials never enter the archive.
    allowed = {k:metadata[k] for k in ("owner","delivery_system","system_version","workspace_format")}
    approved_bytes("settings.json", snapshot.canonical(allowed))
    omits = {}
    for name in sorted((entries.keys() | head.keys() | index.keys()) - selected.keys()):
        if name.startswith(".git/"):
            continue
        omits[name] = "not selected" if eligible(name) else "restricted or opaque"
    manifest = {"format":FORMAT,"audience":policy["audience"],"lineage":"new-private-history","workspace_id":sid,
                "source_head":old_head,"governing":governed,"settings":allowed,"files":selected,"bindings":exported_bindings(root, selected, registry)}
    if location.purpose_layout(root):
        manifest["layout"] = "purpose-v1"
    decision = {"destination":str(destination),"source_inventory":snapshot.digest(current),"manifest":manifest,
                "omitted":omits,"exclusions":["raw Git history and refs","host and account state","unspecified historical versions",
                                             "unreviewed file classes, credentials, grants, pending sends and executable config"]}
    if snapshot.digest(snapshot.inspect(root)) != decision["source_inventory"]:
        raise ValueError("Workspace changed during portable review")
    return decision, blobs if payload else {}


def private_context(plan):
    return snapshot.digest({key: value for key,value in plan.items() if key != "manifest"})


def review_digest(plan):
    return snapshot.digest([snapshot.digest(plan["manifest"]), private_context(plan)])


def export(root, destination, policy, expected):
    root = snapshot.local(root)
    destination = snapshot.local(destination)
    if destination.exists():
        if not stat.S_ISREG(destination.lstat().st_mode):
            raise ValueError("The existing export destination requires separate review")
        with zipfile.ZipFile(destination) as z:
            if z.getinfo(REVIEW).file_size > 1024:
                raise ValueError("Oversized portable review receipt")
            receipt = json.loads(z.read(REVIEW))
        if (receipt.get("binding") != snapshot.digest([expected, identity.workspace_id(root), str(destination)])
                or snapshot.digest([receipt["manifest"], receipt["context"]]) != expected):
            raise ValueError("A different artifact already occupies the export destination")
        manifest, _ = validate_archive(destination, receipt["manifest"])
        approved_selection(policy)
        if manifest["audience"] != policy["audience"] or {n:sorted(set(v)) for n,v in policy["files"].items()} != {
                n:r["history"] for n,r in manifest["files"].items()}:
            raise ValueError("The export selection differs from the published decision")
        return {"result":"already-exported","manifest_digest":receipt["manifest"],"files":len(manifest["files"]),
                "lineage":manifest["lineage"]}
    destination = snapshot.check_destination(root, destination)
    with snapshot.idle_writer(root):
        decision, blobs = review(root, destination, policy, payload=True)
        if review_digest(decision) != expected:
            raise ValueError("Portable inputs differ from the reviewed selection")
        manifest = decision["manifest"]
        with tempfile.TemporaryDirectory(dir=destination.parent, prefix=".oryx-export-") as temporary:
            archive = Path(temporary) / "portable.zip"
            with archive.open("xb") as stream:
                os.fchmod(stream.fileno(),0o600)
                with zipfile.ZipFile(stream, "w") as z:
                    z.writestr(MANIFEST,snapshot.canonical(manifest))
                    z.writestr(REVIEW, snapshot.canonical({"manifest":snapshot.digest(manifest),
                               "context": private_context(decision), "binding":snapshot.digest([expected, manifest["workspace_id"], str(destination)])}))
                    for sha, data in sorted(blobs.items()):
                        z.writestr("blobs/" + sha,data)
                stream.flush()
                os.fsync(stream.fileno())
            validate_archive(archive,snapshot.digest(manifest))
            if snapshot.digest(snapshot.inspect(root)) != decision["source_inventory"]:
                raise ValueError("Workspace changed after portable review")
            snapshot.publish_new(archive,destination)
    return {"result":"portable-export","manifest_digest":snapshot.digest(manifest),"files":len(manifest["files"]),
            "omitted_count":len(decision["omitted"]), "lineage":manifest["lineage"]}


def validate_archive(archive, expected):
    with zipfile.ZipFile(archive) as z:
        names = z.namelist()
        if (len(names) != len(set(names)) or MANIFEST not in names or not 1 < len(names) <= MAX_FILES * 8
                or any(e.compress_type != zipfile.ZIP_STORED or e.flag_bits & 1 or e.file_size > identity.LIMIT for e in z.infolist())
                or sum(e.file_size for e in z.infolist()) > MAX_TOTAL + identity.LIMIT):
            raise ValueError("Invalid portable archive size, format or entries")
        manifest = json.loads(z.read(MANIFEST))
        snapshot.verified(manifest,expected)
        if ((set(manifest) - {"layout"}) != {"format","audience","lineage","workspace_id","source_head","settings","files","bindings","governing"}
                or "layout" in manifest and manifest["layout"] != "purpose-v1"
                or manifest["format"] != FORMAT or manifest["lineage"] != "new-private-history"):
            raise ValueError("Invalid portable manifest")
        from uuid import UUID
        if str(UUID(manifest["workspace_id"])) != manifest["workspace_id"]:
            raise ValueError("Invalid portable Workspace identity")
        approved_selection({"audience":manifest["audience"],"lineage":manifest["lineage"],
                            "files":{p:r["history"] for p,r in manifest["files"].items()}})
        settings = manifest["settings"]
        if (set(settings) != {"owner","delivery_system","system_version","workspace_format"}
                or settings["workspace_format"] != 2 or not isinstance(settings["owner"],str)
                or not isinstance(settings["delivery_system"],str) or not re.fullmatch(r"\d+\.\d+\.\d+",settings["system_version"])):
            raise ValueError("Unsupported portable Workspace settings")
        if manifest["source_head"] is not None and not re.fullmatch(r"[a-f0-9]{40}|[a-f0-9]{64}", manifest["source_head"]):
            raise ValueError("Invalid source Git revision")
        approved_bytes("settings.json", snapshot.canonical(settings))
        if REVIEW not in names or z.getinfo(REVIEW).file_size > 1024:
            raise ValueError("Invalid portable review receipt")
        receipt = json.loads(z.read(REVIEW))
        if (set(receipt) != {"manifest","binding","context"} or receipt["manifest"] != expected
                or any(not identity.SHA.fullmatch(receipt[k]) for k in ("binding","context"))):
            raise ValueError("Portable review receipt differs from the manifest")
        needed = {MANIFEST, REVIEW}
        blobs = {}
        for name,row in manifest["files"].items():
            if set(row) - {"mtime_ns"} != {"working","index","head","history","id"} or row["id"] is not None and not identity.ID.fullmatch(row["id"]):
                raise ValueError("Invalid portable record metadata")
            when = row.get("mtime_ns")
            if when is not None and (row["working"] is None or not valid_time(when)):
                raise ValueError("Invalid portable source modification time")
            for sha in [row["working"],row["index"],row["head"],*row["history"]]:
                if sha is None:
                    continue
                if not isinstance(sha,str) or not identity.SHA.fullmatch(sha):
                    raise ValueError("Invalid portable data digest")
                key = "blobs/"+sha
                needed.add(key)
                data = blobs.setdefault(sha, z.read(key)) if sha not in blobs else blobs[sha]
                if approved_bytes(name,data) != sha:
                    raise ValueError("Portable record bytes differ from reviewed bytes")
        governing = manifest["governing"]
        if not isinstance(governing,list) or governing != sorted(set(governing)) or any(
                "notes/"+name not in manifest["files"] for name in governing):
            raise ValueError("Invalid governing note metadata")
        approved_pairs(manifest["files"], blobs, purpose=manifest.get("layout") == "purpose-v1")
        if needed != set(names):
            raise ValueError("Unexpected portable payload")
        return manifest,blobs


def git(root, args, data=None):
    env = {"PATH":os.defpath,"LC_ALL":"C","GIT_CONFIG_GLOBAL":os.devnull,"GIT_CONFIG_NOSYSTEM":"1",
           "GIT_TERMINAL_PROMPT":"0","GIT_AUTHOR_NAME":"Oryx restore","GIT_AUTHOR_EMAIL":"restore@localhost",
           "GIT_COMMITTER_NAME":"Oryx restore","GIT_COMMITTER_EMAIL":"restore@localhost"}
    result = subprocess.run(["git","-C",str(root),"-c","core.hooksPath=/dev/null",*args],input=data,
                            env=env,capture_output=True,timeout=60,check=True)
    return result.stdout.strip()


def restore(archive, destination, expected):
    archive = snapshot.local(archive)
    destination = snapshot.local(destination)
    if not stat.S_ISREG(archive.lstat().st_mode):
        raise ValueError("Use a regular portable archive")
    manifest, blobs = validate_archive(archive,expected)
    if destination.exists():
        receipt = check_receipt(destination)
        if receipt["manifest"] != expected:
            raise ValueError("The existing destination belongs to a different recovery")
        return {"result": "already-restored", "manifest_digest": expected, "workspace_id": receipt["workspace_id"],
                "lineage": receipt["lineage"], "head": receipt["new_head"]}
    destination = snapshot.check_destination(archive, destination)
    with tempfile.TemporaryDirectory(dir=destination.parent,prefix=".oryx-portable-") as temp:
        root = Path(temp)/"workspace"
        root.mkdir(mode=0o700)
        git(root, ["init","--quiet","--template=","--initial-branch=main"])
        files = manifest["files"]
        def install_index(layer):
            git(root,["read-tree","--empty"])
            lines = []
            for name, row in files.items():
                sha = row[layer]
                if sha:
                    oid = git(root,["hash-object","-w","--stdin"],blobs[sha])
                    lines.append(b"100644 "+oid+b"\t"+name.encode()+b"\0")
            if lines:
                git(root,["update-index","-z","--index-info"],b"".join(lines))
        # Git may return the virtual empty-tree ID without creating its object.
        git(root, ["hash-object","-w","-t","tree","--stdin"], b"")
        install_index("head")
        tree = git(root,["write-tree"]).decode()
        commit = git(root,["commit-tree",tree,"-m","Restore reviewed portable Workspace baseline"]).decode()
        git(root,["update-ref","refs/heads/main",commit])
        install_index("index")
        for name,row in files.items():
            if row["working"] and not name.startswith("notes/"):
                path=identity.local_file(root,name)
                identity.safe_directory(path.parent)
                with path.open("xb") as f:
                    os.fchmod(f.fileno(),0o600)
                    f.write(blobs[row["working"]]); f.flush(); os.fsync(f.fileno())
        settings={**manifest["settings"],"remotes":{"system":None,"workspace":None}}
        identity.write_json(root/"settings.json",settings)
        identity.write_json(root/".oryx/workspace.json", {"id": manifest["workspace_id"],
                            **({"layout": manifest["layout"]} if "layout" in manifest else {})})
        # Start with a new customer-owned notes generation. No imported approval becomes actionable.
        notes = {name.removeprefix("notes/"): row["working"] for name, row in files.items() if name.startswith("notes/")}
        if notes or any(DRAFT.fullmatch(n) for n in files):
            from oryx.review import store
            if not all(notes.values()):
                raise ValueError("A removed protected note needs a separate review")
            protected_notes(root, "init")
            folder = root / "notes"
            (folder / store.HEAD).unlink()
            head = {"schema": 1, "workspace": manifest["workspace_id"], "files": notes,
                    "receipts": {}, "governing": manifest["governing"]}
            store.Workspace.write_generation(folder, head, {name:blobs[sha].decode("utf-8") for name,sha in notes.items()})
            protected_notes(root, "read")
        from .repository import starter_texts
        core = Path(__file__).resolve().parents[3]
        for relative, text in starter_texts(core, root, purpose=manifest.get("layout") == "purpose-v1", selected=root):
            if relative.as_posix() not in files:
                target = identity.local_file(root, relative.as_posix())
                identity.safe_directory(target.parent)
                with target.open("xb") as output:
                    os.fchmod(output.fileno(), 0o600)
                    output.write(text.encode("utf-8"))
        # Recovery ledgers are initialized locally and never replay source actions.
        import upgrades, layout_upgrade
        upgrades.fresh(root)
        layout_upgrade.mark_fresh(root)
        registry={"schema":1,"workspace_id":manifest["workspace_id"],"records":{}}
        for name,row in files.items():
            if not row["id"] or not row["working"]:
                continue
            if row["id"] in registry["records"]:
                raise ValueError("Two exported records have the same identity")
            versions = sorted({h for h in [row["working"],row["index"],row["head"],*row["history"]] if h})
            registry["records"][row["id"]]={"path":name,"aliases":manifest["bindings"][row["id"]]["aliases"],"revision":row["working"],"history":versions}
            for sha in versions:
                identity.put_blob(root,sha,blobs[sha])
        identity.write_json(root/identity.INDEX,registry)
        if set(manifest["bindings"]) != set(registry["records"]):
            raise ValueError("Unexpected exported identity or citation")
        identity.load(root)
        identity.write_json(root / citations.FILE, {"schema":1,"workspace_id":manifest["workspace_id"],
                            "records": {rid: item["citations"] for rid,item in manifest["bindings"].items()}})
        _, registry, additions = identity.prepared(root)
        for revision,name in additions.items():
            identity.put_blob(root, revision, identity.read_regular(identity.local_file(root, name)))
        identity.write_json(root / identity.INDEX, registry)
        citations.reconcile(root,registry)
        missing_times = restore_timestamps(root, files)
        identity.write_json(root/RECEIPT,{"schema":1,"missing_times":missing_times,"workspace_id":manifest["workspace_id"],"manifest":expected,
                            "lineage":"new-private-history","new_head":commit,"source_head":manifest["source_head"],
                            "legacy_core":{rid:row["legacy_core"] for rid,row in manifest["bindings"].items() if row.get("legacy_core")}})
        from . import adoption
        validate_durable(root, files)
        adoption.checked_paths(root)
        snapshot.check_repository(root)
        from .storage import prepare_repository_lock
        prepare_repository_lock(root)
        snapshot.publish_new(root,destination)
    return {"result":"restored-portable-copy","manifest_digest":expected,"files":len(files),
            "workspace_id":manifest["workspace_id"],"lineage":"new-private-history","head":commit}


def check_receipt(root):
    record=json.loads(identity.read_regular(identity.local_file(root,str(RECEIPT))))
    if (not isinstance(record,dict) or set(record) - {"legacy_core","missing_times"} != {"schema","workspace_id","manifest","source_head","lineage","new_head"}
            or record["schema"] != 1 or record["workspace_id"] != identity.workspace_id(root)
            or record["lineage"] != "new-private-history" or not identity.SHA.fullmatch(record["manifest"])
            or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}",record["new_head"])):
        raise ValueError("Invalid portable recovery receipt")

    from . import adoption
    adoption.check_proofs(record.get("legacy_core", {}))
    missing = record.get("missing_times", {})
    if not isinstance(missing, dict):
        raise ValueError("Invalid portable source timestamp receipt")
    for path, item in missing.items():
        identity.relative(path)
        if (not isinstance(item,dict) or item.keys() != {"id","revision","restore_mtime_ns"}
                or item["id"] is not None and not identity.ID.fullmatch(item["id"])
                or not identity.SHA.fullmatch(item["revision"]) or not valid_time(item["restore_mtime_ns"])):
            raise ValueError("Invalid portable source timestamp receipt")
    return record
