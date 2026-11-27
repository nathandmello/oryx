"""Review and recover a single canonical task or launch checklist file with its neighbors intact."""
import json
import os
from pathlib import Path
import stat
from tempfile import TemporaryDirectory
from uuid import uuid4

from . import handoff, store


def domain():
    handoff.legacy()  # Import legacy modules from this Core installation only.
    import initiative_work
    return initiative_work


def destination(ws, request):
    w = domain()
    if request["operation"] == "customization":
        if set(request) != {"operation", "request", "base", "after"}:
            raise ValueError("Invalid customization proposal")
        from oryx.capabilities import customizations
        import studio_layout
        return studio_layout.location(ws.root, customizations.FILE)
    if set(request) != {"operation", "command", "action", "product", "initiative", "edits", "base", "after"}:
        raise ValueError("Invalid initiative work proposal")
    command, action = request["command"], request["action"]
    if (command, action) not in {("task", "apply"), ("launch-checklist", "apply"), ("launch-checklist", "init")}:
        raise ValueError("Choose a supported initiative edit")
    if not isinstance(request["edits"], dict) or set(request["edits"]) - {"expected", "changes", "starter_revision"}:
        raise ValueError("Invalid initiative edit fields")
    name = w.TASKS if command == "task" else w.CHECKLIST
    relative = w.layout.initiative_work_path(request["product"], request["initiative"], name)
    target = ws.root / relative
    if target.resolve() != target:
        raise ValueError("Use an unredirected initiative file")
    return target


def proposal(ws, request):
    w = domain()
    target = destination(ws, request)
    if target.exists():
        info = target.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_nlink != 1 or info.st_mode & 0o7022 or os.listxattr(target):
            raise ValueError("Use a PM-owned regular initiative file without extra links, attributes or shared writes")
    if os.environ.get("PM_HUB_SHARED_GROUP"):
        raise ValueError("Reviewed initiative updates require an individually owned Workspace")
    core = w.storage.core_for(ws.root)
    if request["operation"] == "customization":
        from oryx.capabilities import customizations
        return customizations.apply(core, request["request"], preview_bytes=True)
    return w.execute(core, request["command"], request["action"], request["product"],
                     request["initiative"], preview_bytes=True, **request["edits"])


def digest(value):
    return None if value is None else store.sha(value.encode("utf-8"))


def stage_work(root, command, operation, product, initiative, edits):
    req = dict(operation="initiative-work", command=command, action=operation, product=product, initiative=initiative,
               edits=edits, base=None, after=None)
    return stage(root, req)


def stage_customization(root, request):
    return stage(root, {"operation": "customization", "request": request, "base": None, "after": None})


def stage(root, req):
    ws = store.Workspace()
    w = domain()
    if w.storage.private_root(root) != ws.root:
        raise ValueError("Selected Workspace differs from the requested destination")
    ws.setup_state()
    with w.storage.writer_lock(ws.root):
        result, old, new = proposal(ws, req)
        if new is None:
            return {**result, "state": "unchanged"}
        req.update(base=digest(old), after=digest(new))
        staged = ws.stage_request(req)
        return {**result, **staged, "next_action": f"oryx review decide {staged['id']}"}


def snapshot_file(path):
    if not os.path.lexists(path):
        return None, None
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > store.MAX_METADATA
                or info.st_uid != os.geteuid()):
            raise ValueError("Use a bounded PM-owned regular initiative file")
        data = stream.read(store.MAX_METADATA + 1)
        current = os.fstat(fd)
        if (len(data) != info.st_size or current.st_ctime_ns != info.st_ctime_ns
                or not os.path.samestat(current, path.lstat())):
            raise ValueError("The initiative file changed during verification")
        return [info.st_dev, info.st_ino], store.sha(data)


def record(folder, filename):
    store.checked_directory(folder, private=True)
    fd = os.open(folder, os.O_DIRECTORY | os.O_RDONLY | os.O_NOFOLLOW)
    try:
        return json.loads(store.read_fd(fd, filename, store.MAX_METADATA), object_pairs_hook=store.unique)
    finally:
        os.close(fd)


def restored_bindings(ws):
    if not os.path.lexists(ws.state / "restored.json"):
        return None
    row = record(ws.state, "restored.json")
    if (not isinstance(row, dict) or set(row) != {"workspace", "inventory", "transactions"}
            or row["workspace"] != ws.identity or not isinstance(row["inventory"], str)
            or not store.HEX.fullmatch(row["inventory"]) or not isinstance(row["transactions"], dict)):
        raise ValueError("Invalid restored transaction bindings")
    for identifier, inode in row["transactions"].items():
        if (not store.HEX.fullmatch(identifier) or not isinstance(inode, list) or len(inode) != 2
                or any(type(value) is not int or value < 0 for value in inode)):
            raise ValueError("Invalid restored transaction inode")
    return row


def digest_pair(folder, target, request):
    official, old = snapshot_file(target)
    staged, new = snapshot_file(folder / "content")
    if request["after"] is None or request["base"] == request["after"]:
        raise ValueError("An initiative transaction requires distinct before and after bytes")
    if (old, new) == (request["after"], request["base"]):
        return official, "recovering"
    if (old, new) == (request["base"], request["after"]):
        return staged, "prepared"
    raise ValueError("Initiative changed during recovery. Both versions have been retained for inspection")


def recover_copy(ws, archive, expected):
    """Rebind all pending transactions on an independently verified exact restored copy."""
    from oryx.recovery import snapshot
    store.pm_only()
    archive = snapshot.local(archive)
    if archive.is_relative_to(ws.root):
        raise ValueError("Choose the separately retained local backup")
    with TemporaryDirectory(prefix=".oryx-proof-") as verification:
        snapshot.restore(archive, Path(verification) / "verified", expected)
    with ws.lock(), domain().storage.writer_lock(ws.root):
        previous = restored_bindings(ws)
        transactions = ws.state / "transactions"
        store.checked_directory(transactions, private=True)
        bindings = {}
        for folder in sorted(transactions.iterdir()):
            if not store.HEX.fullmatch(folder.name):
                raise ValueError("Unknown entry in initiative transactions")
            store.checked_directory(folder, private=True)
            request = ws.proposal(folder.name)
            if (folder / "done.json").exists():
                state(ws, folder.name, request)
                continue
            inode, _ = digest_pair(folder, destination(ws, request), request)
            validate_intent(ws, folder, request)
            bindings[folder.name] = inode
        result = {"workspace": ws.identity, "inventory": expected, "transactions": bindings}
        if previous and previous["inventory"] == expected and all(
                previous["transactions"].get(key) == value for key, value in bindings.items()):
            return {"state": "rebound", "pending": sorted(bindings), "inventory": expected}
        manifest, stamps = snapshot.inventory(ws.root)
        snapshot.verified(manifest, expected)
        if bindings:
            confirmed, latest = snapshot.inventory(ws.root)
            if latest != stamps or confirmed != manifest:
                raise ValueError("The restored copy changed during verification")
            temporary = ws.state / (".restore-" + uuid4().hex)
            try:
                store.publish_file(temporary, store.encoded(result), mode=0o400)
                os.replace(temporary, ws.state / "restored.json")
                store.sync_dir(ws.state)
            finally:
                temporary.unlink(missing_ok=True)
        return {"state": "rebound", "pending": sorted(bindings), "inventory": expected}


def validate_intent(ws, folder, request):
    intent = record(folder, "intent.json")
    receipt = intent.get("receipt") if isinstance(intent, dict) else None
    if (not isinstance(receipt, dict) or set(receipt) != {"id", "workspace", "actor", "review", "paths"}
            or set(intent) != {"inode", "receipt", "base", "after"} or intent["base"] != request["base"]
            or intent["after"] != request["after"] or receipt["id"] != folder.name
            or receipt["workspace"] != ws.identity or receipt["actor"] not in {"pm-local-review", "pm-local-editor"}
            or not isinstance(receipt["review"],str) or not store.HEX.fullmatch(receipt["review"])
            or not isinstance(intent["inode"],list) or len(intent["inode"]) != 2
            or any(type(v) is not int or v < 0 for v in intent["inode"])
            or receipt["paths"] != [destination(ws, request).relative_to(ws.root).as_posix()]):
        raise ValueError("Initiative recovery record differs from the reviewed operation")
    return intent


def state(ws, identifier, request):
    folder = ws.state / "transactions" / identifier
    if not os.path.lexists(folder):
        return folder, None, None
    intent = validate_intent(ws, folder, request)
    if (folder / "done.json").exists():
        if record(folder, "done.json") != intent["receipt"]:
            raise ValueError("Initiative receipt failed its integrity check")
        return folder, intent, "applied"
    inode, status = digest_pair(folder, destination(ws, request), request)
    if inode == intent["inode"]:
        return folder, intent, status
    previous = restored_bindings(ws)
    if previous and previous["transactions"].get(identifier) == inode:
        return folder, intent, status
    raise ValueError("Local file identity changed. An untouched restored copy requires review recover-copy with its backup and retained digest")



def inspect(ws, identifier, request):
    _, intent, status = state(ws, identifier, request)
    if status in {"applied", "recovering"}:
        return {"state": status, "receipt": intent["receipt"]}
    if (ws.state / "discarded" / identifier).exists():
        return {"id": identifier, "state": "discarded"}
    target = destination(ws, request)
    _, old, new = proposal(ws, request)
    if new is None or digest(old) != request["base"] or digest(new) != request["after"]:
        raise ValueError("The initiative or its supporting evidence changed. Stage the current result again")
    return {"id": identifier, "state": "pending", "workspace": ws.identity,
            "current_behavior": "The Workspace uses the saved revision shown below.",
            "reason": "The PM requested the change to the displayed document.",
            "effect": "Saving publishes the exact replacement at the named location.",
            "changes": [{"path": target.relative_to(ws.root).as_posix(), "base": request["base"],
                         "before": old, "text": new, "after_sha256": request["after"]}]}


def finish(ws, identifier, request):
    folder, intent, status = state(ws, identifier, request)
    if status == "recovering":
        store.sync_dir(destination(ws, request).parent)
        store.sync_dir(folder)
        store.publish_file(folder / "done.json", store.encoded(intent["receipt"]), mode=0o400)
    elif status != "applied":
        raise ValueError("Initiative update remains pending")
    return {"state": "applied", "receipt": intent["receipt"]}


def commit(ws, identifier, reviewed, request, actor):
    w = domain()
    with w.storage.writer_lock(ws.root):
        target = destination(ws, request)
        folder, intent, status = state(ws, identifier, request)
        if status in {"recovering", "applied"}:
            return finish(ws, identifier, request)
        shown = inspect(ws, identifier, request)
        if store.encoded(shown) != reviewed or ws.proposal(identifier) != request:
            raise ValueError("The exact initiative review changed")
        # Prevent a second change to the same canonical file until a pending receipt is finalized.
        for other in folder.parent.iterdir():
            if other != folder and store.HEX.fullmatch(other.name) and not (other / "done.json").exists():
                other_request = ws.proposal(other.name)
                if destination(ws, other_request) == target:
                    raise ValueError(f"Finish the pending initiative review {other.name} first")
        if intent is None:
            generation = ws.generation()
            mode = stat.S_IMODE(target.stat().st_mode) if target.exists() else 0o600
            store.publish_file(generation / "content", shown["changes"][0]["text"].encode(), mode=mode)
            inode, _ = snapshot_file(generation / "content")
            receipt = {"id": identifier, "workspace": ws.identity, "actor": actor, "review": store.sha(reviewed),
                       "paths": [target.relative_to(ws.root).as_posix()]}
            intent = {"inode": inode, "receipt": receipt, "base": request["base"], "after": request["after"]}
            store.publish_file(generation / "intent.json", store.encoded(intent), mode=0o400)
            store.rename_dir(generation, folder, exchange=False)
        if intent["receipt"]["review"] != store.sha(reviewed):
            raise ValueError("Resume the original approved initiative review")
        if store.encoded(inspect(ws, identifier, request)) != reviewed or ws.proposal(identifier) != request:
            raise ValueError("The initiative changed before save")
        target.parent.mkdir(parents=True, exist_ok=True)
        store.checked_directory(target.parent)
        store.rename_dir(folder / "content", target, exchange=request["base"] is not None)
        return finish(ws, identifier, request)
