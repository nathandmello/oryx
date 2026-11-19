"""Manage initiative tasks and launch checkpoints in the private repository."""

from datetime import date
from graphlib import CycleError, TopologicalSorter
from hashlib import sha256
import json
from pathlib import Path
import re

import initiative_store
import layout
import records
import storage
import upgrades
import workspace


TASKS = "tasks.json"
CHECKLIST = "launch-checklist.json"
TEMPLATE = "templates/launch-checklist.json"
TASK_STATUS = ("todo", "in-progress", "blocked", "done", "cancelled")
CHECK_STATUS = ("pending", "blocked", "verified", "waived")
PHASES = ("upstream", "launch", "downstream")
PRIORITIES = ("high", "normal", "low")
TASK_DEFAULTS = {
    "owner": None, "due_on": None, "source": None, "blocked_reason": None,
    "status": "todo", "priority": "normal", "depends_on": [], "resolution": None,
}
CHECK_DEFAULTS = {
    "owner": None, "due_on": None, "source": None, "blocked_reason": None,
    "status": "pending", "tasks": [], "verification": None, "waiver": None,
}
REQUIRED = {
    TASKS: {"title", "completion_criteria"},
    CHECKLIST: {"title", "phase", "criterion"},
}
DEFAULTS = {TASKS: TASK_DEFAULTS, CHECKLIST: CHECK_DEFAULTS}


def text(value, field):
    if (not isinstance(value, str) or value.strip() != value or value.splitlines() != [value]
            or not records.specific(value) or not any(char.isalnum() for char in value)
            or any(ord(char) < 32 or ord(char) == 127 for char in value)):
        raise ValueError(f"{field} needs concrete text on one line")
    value.encode("utf-8")


def day(value, field, *, past=False):
    try:
        parsed = date.fromisoformat(value)
        if parsed.isoformat() == value and (not past or parsed <= date.today()):
            return
    except (TypeError, ValueError):
        pass
    qualifier = " through today" if past else ""
    raise ValueError(f"{field} needs a YYYY-MM-DD date{qualifier}")


def fields(value, required, optional=()):
    if not isinstance(value, dict) or not required <= value.keys() <= required | set(optional):
        raise ValueError(f"Required fields: {', '.join(sorted(required)) or 'none'}. "
                         f"Optional fields: {', '.join(sorted(optional)) or 'none'}.")


def links(value, field):
    if not isinstance(value, list):
        raise ValueError(f"{field} needs a list of task IDs")
    for identifier in value:
        layout.slug(identifier)
    if len(set(value)) != len(value):
        raise ValueError(f"{field} repeats a task ID")


def attestation(value, key):
    fields(value, {key, "by", "on"})
    text(value[key], key)
    text(value["by"], "by")
    day(value["on"], "on", past=True)


def validate_row(filename, row):
    fields(row, REQUIRED[filename] | DEFAULTS[filename].keys())
    for name in REQUIRED[filename]:
        text(row[name], name)
    for name in ("owner", "source", "blocked_reason"):
        if row[name] is not None:
            text(row[name], name)
    if row["due_on"] is not None:
        day(row["due_on"], "due_on")
    statuses = TASK_STATUS if filename == TASKS else CHECK_STATUS
    status = row["status"]
    if status not in statuses:
        raise ValueError(f"status must be one of {', '.join(statuses)}")
    if (status == "blocked") != (row["blocked_reason"] is not None):
        raise ValueError("Record a blocked reason exactly when status is blocked")
    if filename == TASKS:
        if row["priority"] not in PRIORITIES:
            raise ValueError("priority must be high, normal, or low")
        links(row["depends_on"], "depends_on")
        if status in ("done", "cancelled"):
            text(row["resolution"], "resolution")
            if status == "done":
                text(row["owner"], "owner")
        elif row["resolution"] is not None:
            raise ValueError("Set resolution only for a done or cancelled task")
    else:
        if row["phase"] not in PHASES:
            raise ValueError("phase must be upstream, launch, or downstream")
        links(row["tasks"], "tasks")
        if status == "verified":
            text(row["owner"], "owner")
            attestation(row["verification"], "evidence")
        elif row["verification"] is not None:
            raise ValueError("Set verification only for a verified checkpoint")
        if status == "waived":
            attestation(row["waiver"], "reason")
        elif row["waiver"] is not None:
            raise ValueError("Set waiver only for a waived checkpoint")


def read_rows(filename, rows):
    if not isinstance(rows, dict):
        raise ValueError("Use an object keyed by stable record ID")
    for identifier, row in rows.items():
        try:
            layout.slug(identifier)
            validate_row(filename, row)
        except ValueError as exc:
            raise ValueError(f"{identifier}: {exc}") from None
    return rows


def template(root):
    path = root / TEMPLATE
    if path.resolve() != path or not path.is_file():
        raise ValueError("The launch checklist starter is missing or unsafe")
    defaults = storage.json_input(path.read_text(encoding="utf-8"))
    if not isinstance(defaults, dict) or not defaults:
        raise ValueError("Give the launch checklist starter checkpoints")
    rows = {}
    for identifier, row in defaults.items():
        fields(row, REQUIRED[CHECKLIST])
        rows[identifier] = {**CHECK_DEFAULTS, **row}
    read_rows(CHECKLIST, rows)
    if {row["phase"] for row in rows.values()} != set(PHASES):
        raise ValueError("Cover upstream, launch, and downstream checks in the starter")
    return rows


def resolve_initiative(root, product, initiative, registrations=None):
    """Use the qualified register or a typed, product-owned initiative overview."""
    private = storage.private_root(root)
    name = records.initiative_home(private, product, initiative)
    target = private / name
    parent = layout.product(product)
    if target.is_file() and target.resolve() == target:
        content = target.read_text(encoding="utf-8")
        if records.parent_reference(name, records.visible_section_markup(content)) == parent:
            initiative_store.local_markdown(root, name, "initiative-context")
            initiative_store.local_markdown(root, parent, "product-context")
            return
    if registrations is None:
        _, _, register = initiative_store.read(root, product)
    else:
        register = registrations.get(product)
    if register and register.setup:
        registered_id = f"{register.setup['references']['product_id']}/{initiative}"
        if registered_id in register.items:
            return
    raise ValueError(f"Select an existing initiative for {product}/{initiative} in its register or context overview")


def read(root, product, initiative, filename):
    private = storage.private_root(root)
    relative = layout.initiative_work_path(product, initiative, filename)
    target = private / relative
    if target.resolve() != target or (target.exists() and not target.is_file()):
        raise ValueError(f"{relative}: use a regular private file")
    if not target.exists():
        return target, None, {}
    if relative.as_posix() in upgrades.source_paths(private):
        raise ValueError(f"{relative} is preserved as original evidence")
    storage.require_visible(private, relative)
    original = target.read_bytes().decode("utf-8")
    field = layout.INITIATIVE_WORK[filename]
    value = storage.json_input(original)
    fields(value, {"version", "product", "initiative", field})
    if type(value["version"]) is not int or value["version"] != 1 or (value["product"], value["initiative"]) != (product, initiative):
        raise ValueError(f"{relative}: schema version and initiative must match the record's home")
    return target, original, read_rows(filename, value[field])


def relationships(tasks, checkpoints):
    graph = {identifier: row["depends_on"] for identifier, row in tasks.items()}
    for label, relation in (("task", graph), ("checkpoint", {key: row["tasks"] for key, row in checkpoints.items()})):
        for identifier, linked in relation.items():
            unknown = set(linked) - tasks.keys()
            if unknown:
                raise ValueError(f"{label} {identifier}: unknown task IDs {', '.join(sorted(unknown))}")
    try:
        TopologicalSorter(graph).prepare()
    except CycleError as exc:
        raise ValueError(f"Task dependency cycle: {' -> '.join(exc.args[1])}") from None


def check(root, identities, registrations):
    for product, initiative in sorted(identities):
        home = layout.initiative_work_path(product, initiative, TASKS).parent
        try:
            resolve_initiative(root, product, initiative, registrations)
            _, _, tasks = read(root, product, initiative, TASKS)
            _, _, checkpoints = read(root, product, initiative, CHECKLIST)
            relationships(tasks, checkpoints)
        except (OSError, ValueError) as exc:
            yield f"{home}: {exc}"


def revision(text_body):
    return "absent" if text_body is None else sha256(text_body.encode("utf-8")).hexdigest()


def edit(filename, current, changes):
    if not isinstance(changes, list) or not changes:
        raise ValueError("Supply a nonempty JSON array of edits")
    result, seen = dict(current), set()
    for change in changes:
        fields(change, {"id", "action", "fields"})
        identifier = layout.slug(change["id"])
        action, delta = change["action"], change["fields"]
        if action not in ("add", "update"):
            raise ValueError("Use add or update")
        if identifier in seen:
            raise ValueError(f"{identifier}: supply one edit per ID")
        seen.add(identifier)
        before = result.get(identifier)
        if (action == "add") != (before is None):
            raise ValueError(f"{identifier}: choose add for a new ID or update for an existing ID")
        allowed = REQUIRED[filename] | DEFAULTS[filename].keys()
        mandatory = REQUIRED[filename] if before is None else set()
        fields(delta, mandatory, allowed - mandatory)
        if not delta:
            raise ValueError(f"{identifier}: supply fields to change")
        after = {**(DEFAULTS[filename] if before is None else before), **delta}
        if before is not None:
            refresh_evidence(filename, before, after, delta)
        result[identifier] = after
    return read_rows(filename, result)


def refresh_evidence(filename, before, after, delta):
    status = after["status"]
    proof = {"done": "resolution", "verified": "verification", "waived": "waiver"}.get(
        status if isinstance(status, str) else None
    )
    review_fields = REQUIRED[filename] | {"owner"}
    if filename == CHECKLIST:
        review_fields |= {"tasks"}
    if (proof and status == before["status"] and proof not in delta
            and any(before[key] != after[key] for key in review_fields)):
        raise ValueError(f"Refresh {proof} or reopen the record when its reviewed scope changes")


def save(target, original, product, initiative, rows):
    filename = target.name
    body = json.dumps({
        "version": 1, "product": product, "initiative": initiative, layout.INITIATIVE_WORK[filename]: rows,
    }, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n"
    storage.replace_text(target, original, body, mode=storage.initiative_mode(target, draft=True))
    return body


def view(filename, target, raw, rows, tasks):
    data = {"path": target.as_posix(), "revision": revision(raw)}
    if filename == TASKS:
        data["tasks"] = [
            dict(row, id=identifier, unfinished_dependencies=[key for key in row["depends_on"] if tasks[key]["status"] != "done"])
            for identifier, row in sorted(rows.items(), key=lambda pair: (
                PRIORITIES.index(pair[1]["priority"]), pair[1]["due_on"] or "9999-12-31", pair[0]
            ))
        ]
    else:
        data["checkpoints"] = [
            dict(row, id=identifier, task_status={key: tasks[key]["status"] for key in row["tasks"]})
            for identifier, row in sorted(rows.items(), key=lambda pair: (
                PHASES.index(pair[1]["phase"]), pair[1]["due_on"] or "9999-12-31", pair[0]
            ))
        ]
        readiness = [row for row in rows.values() if row["phase"] in ("upstream", "launch")]
        if {row["phase"] for row in readiness} != {"upstream", "launch"}:
            data["launch_readiness"] = "upstream or launch checks missing"
        elif any(row["status"] not in ("verified", "waived") for row in readiness):
            data["launch_readiness"] = "pending"
        else:
            data["launch_readiness"] = "ready for launch decision"
    return data


def markdown(result):
    def plain(value):
        return re.sub(r"([\\|*_#<>&\x60\[\]])", r"\\\1", str(value))

    print(f"Record revision: {result['revision']}\n")
    if "launch_readiness" in result:
        print(f"Launch readiness: **{result['launch_readiness']}**\n")
    rows = result.get("tasks", result.get("checkpoints"))
    if not rows:
        print("No records yet.")
    for row in rows:
        print(f"### {plain(row['title'])} ({row['id']})\n")
        for key in ("phase", "status", "owner", "priority", "due_on", "completion_criteria", "criterion",
                    "source", "blocked_reason", "depends_on", "unfinished_dependencies", "task_status",
                    "resolution", "verification", "waiver"):
            value = row.get(key)
            if key == "owner" and value is None:
                value = "Unassigned"
            if value:
                if isinstance(value, list):
                    value = ", ".join(value)
                if isinstance(value, dict):
                    value = " · ".join(f"{name}: {detail}" for name, detail in value.items())
                print(f"- {key.replace('_', ' ').capitalize()}: {plain(value)}")
        print()


def add_commands(commands):
    for name, help_text in (("task", "Manage initiative PM tasks"), ("launch-checklist", "Track launch readiness and follow-through")):
        command = commands.add_parser(name, help=help_text)
        operations = command.add_subparsers(dest="operation", required=True)
        listing = operations.add_parser("list", help="Show the records and revision")
        listing.add_argument("--format", choices=("json", "markdown"), default="json")
        apply = operations.add_parser("apply", help="Apply or preview a JSON array of edits")
        apply.add_argument("--revision", required=True, help="Current list revision or absent for a new list")
        apply.add_argument("--preview", action="store_true", help="Validate and display proposed edits without writing")
        entries = [listing, apply]
        if name == "launch-checklist":
            init = operations.add_parser("init", help="Start from the shared launch checklist")
            init.add_argument("--preview", action="store_true", help="Show starter checkpoints without writing")
            entries.append(init)
        for operation in entries:
            operation.add_argument("product")
            operation.add_argument("initiative")


def render(result, output_format):
    if output_format == "markdown":
        markdown(result)
    else:
        print(json.dumps(result, indent=2, ensure_ascii=False))


def execute(root, command, operation, product, initiative, *, expected=None, changes=None, write=False):
    filename = {"task": TASKS, "launch-checklist": CHECKLIST}[command]
    relative = layout.initiative_work_path(product, initiative, filename)
    resolve_initiative(root, product, initiative)
    target, original, rows = read(root, product, initiative, filename)
    other_file = CHECKLIST if filename == TASKS else TASKS
    _, _, other = read(root, product, initiative, other_file)
    if operation == "apply":
        if expected != revision(original):
            raise ValueError("The list changed. Read its current revision and review your edits")
        rows = edit(filename, rows, changes)
    elif operation == "init":
        if expected is not None and expected != revision(original):
            raise ValueError("The list changed. Read its current revision and review your edits")
        if original is None:
            rows = template(root)
    tasks, checkpoints = (rows, other) if filename == TASKS else (other, rows)
    relationships(tasks, checkpoints)
    if operation == "apply" or (operation == "init" and original is None):
        private = storage.private_root(root)
        if relative.as_posix() in upgrades.source_paths(private):
            raise ValueError(f"{relative} is preserved as original evidence")
        storage.require_visible(private, relative)
        if write:
            original = save(target, original, product, initiative, rows)
    return view(filename, relative, original, rows, tasks)
