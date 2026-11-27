"""Persist machine-only workflow progress bound to reviewed personal work and its grants."""

from hashlib import sha256
import json
import os
import re

import pm_profile
import storage
import work_handoffs
import workspace
from oryx.workspace.location import workspace_id
from .method import entry, fingerprint, measured, prepare, with_inputs
from .readback import observe, permit_completion

HASH = re.compile(r"[0-9a-f]{64}")
INDEX = ".oryx/state/workflows/"
SCHEMA = 1


def checked_workspace(root, write):
    if write:
        from oryx.review.store import pm_only
        pm_only()
    selected = storage.selected_workspace(root)
    if selected is None or selected != workspace.repo(root, "workspace"):
        raise ValueError("Select the personal Workspace before opening workflow progress")
    return selected, workspace_id(selected)


def require_hash(value):
    if not isinstance(value, str) or not HASH.fullmatch(value):
        raise ValueError("Supply the full reviewed revision or checkpoint identifier")
    return value


def handoff(private, key, scope, revision):
    if not work_handoffs.match(work_handoffs.SCOPE, scope):
        raise ValueError("Supply the exact reviewed work scope")
    _, state = work_handoffs.read(private)
    row = state["work"].get(key)
    if not row or row["status"] != "open" or row["task"]["scope"] != scope or row["revision"] != revision:
        raise ValueError("Review the current handoff in its original scope before continuing")
    # This checks owner/parent revisions, evidence grants, source revisions and any required journal grant.
    details = work_handoffs.details(private, state, key, row, admitting=True)
    return details, row.get("base_revision")


def application(root):
    descriptor = workspace.release(root)
    marker = root / "oryx-release-manifest.json"
    if marker.exists():
        if marker.resolve() != marker or not marker.is_file() or marker.stat().st_size > 1024 * 1024:
            raise ValueError("Cannot identify the installed release")
        release_id = sha256(marker.read_bytes()).hexdigest()
    else:
        release_id = fingerprint(descriptor)
    return {"version": descriptor["system_version"], "format": descriptor["workspace_format"], "release_id": release_id}


def identity(state):
    return fingerprint([state[k] for k in ("workspace", "command", "scope", "handoff", "origin", "version")])


def get(private, key):
    target = pm_profile.safe_path(private, INDEX + require_hash(key) + ".json")
    raw = target.read_bytes() if target.is_file() else None
    if raw is None:
        return target, None, None
    if len(raw) > 64 * 1024:
        raise ValueError("The saved workflow checkpoint exceeds its supported size")
    doc = storage.json_input(raw)
    if (not isinstance(doc, dict) or doc.keys() != {"state", "revision"} or not isinstance(doc["state"], dict)
            or doc["state"].keys() != {"schema", "workspace", "scope", "command", "handoff", "version",
                                       "step", "origin", "handoff_revision", "readback_revision", "application", "accepted", "last_expect"}
            or type(doc["state"]["schema"]) is not int or doc["state"]["schema"] != SCHEMA
            or fingerprint(doc["state"]) != doc["revision"] or identity(doc["state"]) != key):
        raise ValueError("Unrecognized or inconsistent workflow checkpoint; preserve it for review")
    state = doc["state"]
    if not isinstance(state["application"], dict) or state["application"].keys() != {"version", "format", "release_id"}:
        raise ValueError("Unrecognized workflow application revision")
    require_hash(state["application"]["release_id"])
    for field in ("version", "origin", "handoff_revision", "readback_revision"):
        require_hash(state[field])
    for field in ("workspace", "scope", "command", "handoff", "step"):
        if not isinstance(state[field], str) or not state[field] or len(state[field]) > 256:
            raise ValueError("Unrecognized workflow checkpoint field")
    if (not work_handoffs.match(work_handoffs.SCOPE, state["scope"])
            or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", state["handoff"])
            or not isinstance(state["accepted"], list) or len(state["accepted"]) > 100):
        raise ValueError("Unrecognized workflow checkpoint scope or history")
    if state["accepted"]:
        require_hash(state["last_expect"])
    elif state["last_expect"] is not None or state["origin"] != state["handoff_revision"]:
        raise ValueError("Inconsistent initial workflow checkpoint")
    previous = None
    for item in state["accepted"]:
        if (not isinstance(item, dict) or item.keys() != {"from", "to", "handoff_revision"}
                or not isinstance(item["from"], str) or not isinstance(item["to"], str)
                or previous is not None and previous != item["from"]):
            raise ValueError("Inconsistent workflow transition history")
        require_hash(item["handoff_revision"])
        previous = item["to"]
    if previous is not None and (previous != state["step"]
                                 or state["accepted"][-1]["handoff_revision"] != state["handoff_revision"]):
        raise ValueError("Workflow checkpoint differs from its transition history")
    return target, raw, doc


def publish(private, target, raw, state, method, details, observed):
    doc = {"state": state, "revision": fingerprint(state)}
    response = view(private, doc, method, details, observed)
    storage.require_visible(private, target.relative_to(private))
    storage.replace_text(target, raw, json.dumps(doc, sort_keys=True, indent=2) + "\n", mode=0o600)
    return response


def view(private, doc, method, details, observed):
    import overrides
    s = doc["state"]
    # Refresh the live effective customizations on each delivery. Reviewed text remains in its owning handoff.
    return measured({"application": s["application"], "id": identity(s), "revision": doc["revision"], "workspace_id": s["workspace"],
            "scope": s["scope"], "handoff_id": s["handoff"], "handoff_revision": s["handoff_revision"],
            "accepted": s["accepted"], "open_question": details["open_question"], "objective": details["objective"],
            "reviewed_next_action": details["next_step"], "evidence": details.get("evidence", []),
            "workflow": method, "workflow_guidance": overrides.guidance(private),
            "readback": observed, "readback_revision": fingerprint(observed),
            "readback_changed": fingerprint(observed) != s["readback_revision"]})


def start(root, command, key, scope, revision):
    private, wid = checked_workspace(root, True)
    with storage.writer_lock(private):
        info, _ = handoff(private, key, scope, require_hash(revision))
        method = entry(root, command, private)
        method.pop("owning_capture", None)  # The durable response includes the live capture in readback.
        observed = observe(root, private, command, scope)
        state = {"schema": SCHEMA, "workspace": wid, "scope": scope, "command": command, "handoff": key,
                 "version": method["version"], "application": application(root), "origin": revision, "step": method["step"], "handoff_revision": revision,
                 "accepted": [], "last_expect": None, "readback_revision": fingerprint(observed)}
        target, raw, doc = get(private, identity(state))
        if doc is None:
            return publish(private, target, raw, state, method, info, observed)
        elif doc["state"]["handoff_revision"] != revision:
            raise ValueError("A workflow already exists for this handoff; review its saved revision")
        else:
            method = prepare(root, command, doc["state"]["step"])
        return view(private, doc, method, info, observed)


def open_current(root, private, wid, key, scope):
    target, raw, doc = get(private, key)
    if doc is None or doc["state"]["scope"] != scope or doc["state"]["workspace"] != wid:
        raise ValueError("No workflow checkpoint is available in the selected Workspace and scope")
    state = doc["state"]
    method = prepare(root, state["command"], state["step"])
    if method["version"] != state["version"]:
        raise ValueError("The workflow method changed. Review the new method and start a new checkpoint")
    return target, raw, doc, method


def show(root, key, scope, *, inputs=None):
    private, wid = checked_workspace(root, False)
    with storage.writer_lock(private):
        _, _, doc, method = open_current(root, private, wid, key, scope)
        state = doc["state"]
        info, _ = handoff(private, state["handoff"], scope, state["handoff_revision"])
        observed = observe(root, private, state["command"], scope)
        result = view(private, doc, method, info, observed)
        return with_inputs(root, result, inputs) if inputs is not None else result


def advance(root, key, scope, expect, to, revision, readback=None):
    private, wid = checked_workspace(root, True)
    require_hash(expect)
    with storage.writer_lock(private):
        target, raw, doc, method = open_current(root, private, wid, key, scope)
        state = doc["state"]
        info, previous = handoff(private, state["handoff"], scope, require_hash(revision))
        observed = observe(root, private, state["command"], scope)
        if state["last_expect"] == expect and state["step"] == to and state["handoff_revision"] == revision:
            return view(private, doc, method, info, observed)
        if expect != doc["revision"] or to not in method["allowed_next"]:
            raise ValueError("Review the current workflow revision and one of its allowed next steps")
        if revision != state["handoff_revision"] and previous != state["handoff_revision"]:
            raise ValueError("The reviewed handoff advanced more than one revision; reconcile the checkpoint")
        if fingerprint(observed) != (state["readback_revision"] if readback is None else require_hash(readback)):
            raise ValueError("The owning operation changed. Reopen the workflow and confirm its readback revision")
        permit_completion(state["command"], to, observed)
        decision = {"from": state["step"], "to": to, "handoff_revision": revision}
        updated = {**state, "application": application(root), "step": to, "handoff_revision": revision, "last_expect": expect,
                   "accepted": [*state["accepted"], decision], "readback_revision": fingerprint(observed)}
        next_method = prepare(root, state["command"], to)
        return publish(private, target, raw, updated, next_method, info, observed)


def checked_paths(private):
    """Validate the identity, schema and digest of each durable progress record."""
    directory = private / INDEX
    if not directory.exists() and not directory.is_symlink():
        return set()
    if directory.resolve() != directory or not directory.is_dir():
        raise ValueError("Expected the local workflow state directory")
    wid = workspace_id(private)
    checked = set()
    for path in directory.iterdir():
        key = path.stem
        if path.suffix != ".json" or not HASH.fullmatch(key):
            raise ValueError("Unexpected file in workflow state")
        _, _, doc = get(private, key)
        if doc is None or doc["state"]["workspace"] != wid:
            raise ValueError("Workflow state belongs to another Workspace")
        checked.add(path.relative_to(private).as_posix())
    return checked


def for_handoff(private, item):
    """Discover matching workflows only after the owning handoff has passed its scope and grant checks."""
    directory = private / INDEX
    if not directory.exists():
        return []
    if not directory.is_dir() or directory.resolve() != directory:
        raise ValueError("Expected the local workflow state directory")
    result = []
    root = storage.core_for(private)
    wid = workspace_id(private)
    for path in sorted(directory.glob("*.json")):
        _, _, doc = get(private, path.stem)
        if doc is None:
            continue
        state = doc["state"]
        if (state["workspace"] != wid or state["handoff"] != item["id"] or state["scope"] != item["scope"]
                or state["handoff_revision"] != item["revision"] or state["step"] == "finish"):
            continue
        method = prepare(root, state["command"], state["step"])
        if state["version"] != method["version"]:
            continue
        result.append({"id": path.stem, "revision": doc["revision"], "command": method["command"],
                       "step": method["step"], "allowed_next": method["allowed_next"]})
    return result
