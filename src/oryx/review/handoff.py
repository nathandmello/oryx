"""Publish a validated legacy handoff and its exact-review receipt in one directory operation."""

import json
import os
from pathlib import Path
import stat
import sys

from . import store


def legacy():
    tools = str(Path(__file__).resolve().parents[3] / "tools")
    if tools not in sys.path:
        sys.path.insert(0, tools)
    import work_handoffs
    return work_handoffs


def receipt_state(ws):
    folder = ws.root / "workspace/handoffs"
    if not os.path.lexists(folder):
        return folder, {}
    store.checked_directory(folder)
    names = set(os.listdir(folder))
    if names - {"index.json", store.HEAD}:
        raise ValueError("Handoff directory contains additional work. Preserve it before using group publication")
    fd = os.open(folder, os.O_DIRECTORY | os.O_RDONLY | os.O_NOFOLLOW)
    try:
        if "index.json" in names:
            store.read_fd(fd, "index.json", store.MAX_METADATA)
        if store.HEAD not in names:
            return folder, {}
        metadata = json.loads(store.read_fd(fd, store.HEAD, store.MAX_METADATA), object_pairs_hook=store.unique)
    finally:
        os.close(fd)
    if (not isinstance(metadata, dict) or set(metadata) != {"workspace", "receipts"}
            or metadata["workspace"] != ws.identity or not isinstance(metadata["receipts"], dict)):
        raise ValueError("Unrecognized handoff review metadata")
    return folder, metadata["receipts"]


def effects(ws, request):
    h = legacy()
    if set(request) != {"operation", "review", "base"} or not isinstance(request["review"], dict):
        raise ValueError("Supply an exact handoff review")
    review = request["review"]
    h.fields(review, ("id", "base_revision", "task", "revision"))
    if not isinstance(review["task"], dict):
        raise ValueError("Expected a reviewed handoff task")
    raw, state = h.read(ws.root)
    if (store.sha(raw) if raw is not None else None) != request["base"]:
        raise ValueError("Handoff index changed. Preview the current record again")
    expected = h.preview(ws.root, {**review["task"], "id": review["id"], "base_revision": review["base_revision"]}, state)
    if expected != review:
        raise ValueError("The reviewed handoff changed")
    state["work"][review["id"]] = {"task": review["task"], "revision": review["revision"],
                                    "status": "open", "base_revision": review["base_revision"]}
    after = (json.dumps(state, indent=2) + "\n").encode()
    if len(after) > store.MAX_METADATA:
        raise ValueError("Handoff index exceeds the supported review size")
    return raw, after


def stage_save(private, payload):
    h = legacy()
    ws = store.Workspace()
    if ws.root != private:
        raise ValueError("Selected Workspace differs from the proposed handoff")
    h.fields(payload, ("review", "approved"))
    if type(payload["approved"]) is not bool:
        raise ValueError("Invalid legacy handoff approval field")
    ws.setup_state()
    with h.storage.writer_lock(private):
        receipt_state(ws)
        raw, _ = h.read(private)
        request = {"operation": "handoff-save", "review": payload["review"],
                   "base": store.sha(raw) if raw is not None else None}
        effects(ws, request)
        return ws.stage_request(request)


def inspect(ws, identifier, request):
    _, receipts = receipt_state(ws)
    if identifier in receipts:
        return {"state": "applied", "receipt": receipts[identifier]}
    if (ws.state / "discarded" / identifier).is_file():
        return {"id": identifier, "state": "discarded"}
    old, new = effects(ws, request)
    return {"id": identifier, "state": "pending", "workspace": ws.identity,
            "current_behavior": "The current handoff remains available to the next session.",
            "reason": "The PM requested this checkpoint for later work.",
            "effect": "Saving replaces the displayed handoff index and makes the reviewed task available to resume.",
            "changes": [{"path": legacy().FILE, "base": request["base"],
                         "before": None if old is None else old.decode(), "text": new.decode(),
                         "after_sha256": store.sha(new)}]}


def commit(ws, identifier, reviewed, request, actor):
    h = legacy()
    with h.storage.writer_lock(ws.root):
        h.storage.require_visible(ws.root, h.FILE)
        folder, receipts = receipt_state(ws)
        if store.encoded(inspect(ws, identifier, request)) != reviewed or ws.proposal(identifier) != request:
            raise ValueError("Handoff review is stale")
        _, updated = effects(ws, request)
        receipt = {"id": identifier, "workspace": ws.identity, "actor": actor, "review": store.sha(reviewed),
                   "paths": [h.FILE], "record": request["review"]["id"], "revision": request["review"]["revision"]}
        generation = ws.generation()
        store.publish_file(generation / "index.json", updated, mode=0o600)
        store.publish_file(generation / store.HEAD, store.encoded({"workspace": ws.identity,
                           "receipts": {**receipts, identifier: receipt}}), mode=0o400)
        if folder.exists():
            info = folder.stat()
            if info.st_uid != os.geteuid() or info.st_mode & 0o022:
                raise ValueError("Use a PM-owned handoff directory")
            generation.chmod(stat.S_IMODE(info.st_mode))
        store.sync_dir(generation)
        if store.encoded(inspect(ws, identifier, request)) != reviewed or ws.proposal(identifier) != request:
            raise ValueError("Handoff changed before save")
        store.rename_dir(generation, folder, exchange=folder.exists())
        return {"state": "applied", "receipt": receipt}
