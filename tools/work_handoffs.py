"""Private, reviewed work checkpoints that either client can find by the PM's task name."""

from hashlib import sha256
import json
from pathlib import Path
import re
import sqlite3
import sys
from uuid import uuid4

import conversation
import layout
import pm_profile
import records
import storage
import task_context
import turn_intent
import upgrades
import workspace


FILE = "workspace/handoffs/index.json"
HASH = re.compile(r"[0-9a-f]{64}")
GRANT = re.compile(r"ref-[0-9a-f]{32}")
JOURNAL = re.compile(r"jrn-[0-9a-f]{32}")
SCOPE = re.compile(r"[a-z0-9]+(?:[-/][a-z0-9]+)*")
FIELDS = ("name", "scope", "objective", "open_question", "next_step")
EXTRA = {"parent", "evidence", "journal", "journal_required", "journal_reference_scope", "owner"}


def fingerprint(value):
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def line(value, limit=240):
    if (not isinstance(value, str) or not value.strip() or value != value.strip() or len(value) > limit
            or not value.isprintable() or "\n" in value):
        raise ValueError("Use short, reviewed task wording on one line")
    return value


def match(pattern, value):
    return isinstance(value, str) and pattern.fullmatch(value) is not None


def fields(value, required, optional=()):
    if not isinstance(value, dict) or not set(required) <= value.keys() <= set(required) | set(optional):
        raise ValueError("Supply exactly the requested checkpoint fields")


def work_input(value):
    fields(value, FIELDS, EXTRA)
    for key in FIELDS:
        line(value[key], 100 if key in {"name", "scope"} else 320)
    if not match(SCOPE, value["scope"]):
        raise ValueError("Use the approved work scope, such as product/billing")
    if "journal_required" in value and (type(value["journal_required"]) is not bool or not value.get("journal")):
        raise ValueError("Bind journal-dependent wording to an approved journal reference")
    if "journal_reference_scope" in value and (not match(SCOPE, value["journal_reference_scope"]) or not value.get("journal")):
        raise ValueError("Choose the journal reference's reviewed work scope")
    for key, pattern in (("evidence", GRANT), ("journal", JOURNAL)):
        refs = value.get(key, [])
        if (not isinstance(refs, list) or len(refs) > 12 or not all(match(pattern, ref) for ref in refs)
                or len(refs) != len(set(refs))):
            raise ValueError("Use separately authorized references for this work")
    for key in ("parent", "owner"):
        if key not in value:
            continue
        ref = value[key]
        if isinstance(ref, dict) and "id" in ref and key == "parent":
            fields(ref, ("id", "revision"))
            layout.slug(ref["id"])
        else:
            fields(ref, ("record", "revision"))
            if not isinstance(ref["record"], str) or not layout.valid_work(ref["record"]):
                raise ValueError("Choose an owning work record")
        if not match(HASH, ref["revision"]):
            raise ValueError("Use the reviewed revision")


def read(private):
    path = pm_profile.safe_path(private, FILE)
    raw = path.read_bytes() if path.is_file() else None
    state = storage.json_input(raw) if raw is not None else {"work": {}, "grants": {}}
    fields(state, ("work", "grants"))
    if not isinstance(state["work"], dict) or not isinstance(state["grants"], dict):
        raise ValueError("Invalid private handoff index")
    for key, row in state["work"].items():
        layout.slug(key)
        fields(row, ("task", "status", "revision", "base_revision"), ("returned_from",))
        work_input(row["task"])
        if (row["status"] not in {"open", "returned", "finished"} or not match(HASH, row["revision"])
                or (row["base_revision"] is not None and not match(HASH, row["base_revision"]))
                or row["revision"] != fingerprint([key, row["task"], row["base_revision"], row["status"], row.get("returned_from")])):
            raise ValueError("Invalid private handoff revision")
    for key, grant in state["grants"].items():
        fields(grant, ("scope", "record", "revision", "source_id"))
        if (not match(GRANT, key) or not match(SCOPE, grant["scope"]) or not match(HASH, grant["revision"])
                or not match(re.compile(r"S[1-9]\d*"), grant["source_id"]) or not isinstance(grant["record"], str)):
            raise ValueError("Invalid private handoff reference")
    return raw, state


def write(private, raw, state):
    storage.require_visible(private, FILE)
    storage.replace_text(pm_profile.safe_path(private, FILE), raw, json.dumps(state, indent=2) + "\n", mode=0o600)


def citation(private, grant):
    name = grant["record"]
    if not isinstance(name, str):
        raise ValueError("Choose a reviewed context record")
    relative = Path(name)
    if (relative.as_posix() != name or relative.parts[:1] != ("context",) or relative.suffix != ".md"
            or any(p.startswith(".") or p in {"sources", "secrets"} for p in relative.parts)
            or name in upgrades.source_paths(private)):
        raise ValueError("Choose a reviewed citation in a private context record")
    path = pm_profile.safe_path(private, name)
    storage.require_visible(private, name)
    data = path.read_bytes()
    if sha256(data).hexdigest() != grant["revision"]:
        raise ValueError("The citation has changed. Review the source again")
    text = data.decode()
    kind = records.MARKER.match(text)
    if not kind or kind[1] not in records.CONTEXT_KINDS or records.context_location(kind[1], relative):
        raise ValueError("Choose a reviewed context record")
    rows, errors = records.table(text, "Sources", records.SOURCE_COLUMNS)
    matching = [row for row in rows if row[0] == grant["source_id"]]
    if (errors or len(matching) != 1 or not match(re.compile(r"S[1-9]\d*"), grant["source_id"])
            or not records.specific(matching[0][1]) or records.uses_customization_source(name, matching[0][1])):
        raise ValueError("Choose a current citation in the owning record")
    return {"record": name, "revision": grant["revision"], "source_id": grant["source_id"]}


def grant_reference(private, payload):
    fields(payload, ("scope", "record", "revision", "source_id", "approved"))
    if payload["approved"] is not True or not match(SCOPE, payload["scope"]):
        raise ValueError("Obtain the PM's approval to retain this exact reference for this work scope")
    grant = {key: value for key, value in payload.items() if key != "approved"}
    with storage.writer_lock(private):
        raw, state = read(private)
        citation(private, grant)
        for key, old in state["grants"].items():
            if old == grant:
                return {"grant": key}
        key = "ref-" + uuid4().hex
        state["grants"][key] = grant
        write(private, raw, state)
        return {"grant": key}


def revoke(private, key):
    if not match(GRANT, key):
        raise ValueError("Choose a handoff reference grant")
    with storage.writer_lock(private):
        raw, state = read(private)
        if key in state["grants"]:
            del state["grants"][key]
            write(private, raw, state)
    return {"status": "revoked"}


def native(private, record):
    path = conversation.record_path(private, record)
    storage.require_visible(private, record)
    data = path.read_bytes()
    text = data.decode()
    checkpoint = conversation.details(text)
    work = checkpoint["work_state"]
    if work["State"] == "complete":
        raise ValueError("This work is complete")
    relative = Path(record)
    kind = layout.governed_kind(record)
    scope = (f"product/{relative.parts[2]}/initiative/{relative.parts[3]}" if kind in layout.INITIATIVE_BRIEFS
             else f"product/{relative.parts[2]}" if kind == "prioritization" else "work/" + checkpoint["id"])
    return {"record": record, "revision": sha256(data).hexdigest(), "name": task_context.title(relative, text),
            "scope": scope, "journal_scope": "work/record/" + checkpoint["id"], "status": work["State"], "next_step": work["Next action"],
            "checkpoint": work["Last checkpoint"], "waiting_on": work["Waiting on"], "mode": work["Mode"]}


def resolve_link(private, state, link, scope, trail):
    if "record" in link:
        resolved = native(private, link["record"])
        if resolved["revision"] != link["revision"] or resolved["scope"] != scope:
            raise ValueError("Review the current work record and its scope before resuming")
        return resolved
    key = link["id"]
    row = state["work"].get(key)
    if (not row or row["status"] != "open" or key in trail or len(trail) > 16
            or row["revision"] != link["revision"] or row["task"]["scope"] != scope):
        raise ValueError("Review the current parent checkpoint and its scope before returning")
    parent = details(private, state, key, row, trail)
    return {field: parent[field] for field in
            ("id", "revision", "scope", "journal_scope", "name", "next_step", "open_question", "mode") if field in parent}


def details(private, state, key, row, trail=(), *, admitting=False):
    task = row["task"]
    scope = task["scope"]
    result = {"id": key, "revision": row["revision"], "status": row["status"], "journal_scope": "work/handoff/" + key, **task}
    allowed_origins = {result["journal_scope"]}
    for name in ("parent", "owner"):
        if name in task:
            result[name] = resolve_link(private, state, task[name], scope, (*trail, key))
            allowed_origins.add(result[name]["journal_scope"])
    if "owner" in result:
        result["mode"] = result["owner"]["mode"]
    evidence = []
    for handle in task.get("evidence", []):
        grant = state["grants"].get(handle)
        if not grant or grant["scope"] != scope:
            raise ValueError("The handoff's evidence grant is unavailable")
        evidence.append({"grant": handle, **citation(private, grant)})
    if evidence:
        result["evidence"] = evidence
    origin = task.get("journal_reference_scope", scope)
    if origin != scope and origin not in allowed_origins:
        raise ValueError("A journal reference must belong to this task or its verified parent or owner")
    for event in task.get("journal", []):
        import session_journal
        try:
            allowed = session_journal.resolve_reference(private, event, purpose="handoff", scope=origin)
        except (OSError, ValueError, sqlite3.Error):
            allowed = None
        if not allowed:
            if admitting or task.get("journal_required"):
                raise ValueError("The scoped journal reference is unavailable")
            result.pop("journal", None)
            result.pop("journal_reference_scope", None)
            result["journal_status"] = "The optional conversation reference is unavailable."
            break
    if result.get("journal") and origin not in allowed_origins:
        result["journal_status"] = "Review a task-specific journal reference to recover later exchanges."
    return result


def preview(private, payload, state=None):
    fields(payload, FIELDS, EXTRA | {"id", "base_revision"})
    task = {key: value for key, value in payload.items() if key not in {"id", "base_revision"}}
    work_input(task)
    key = layout.slug(payload.get("id", "work-" + fingerprint([task["name"], task["scope"], task["objective"]])[:20]))
    if len(key) > 80:
        raise ValueError("Use a task ID of at most 80 characters")
    state = read(private)[1] if state is None else state
    existing = state["work"].get(key)
    base = existing["revision"] if existing else None
    revision = fingerprint([key, task, payload.get("base_revision"), "open", None])
    if existing and (existing["status"] != "open" or task["scope"] != existing["task"]["scope"]):
        raise ValueError("Choose the original task and scope")
    if base != payload.get("base_revision") and revision != base:
        raise ValueError("Review the current checkpoint before changing it")
    row = {"task": task, "status": "open", "revision": revision, "base_revision": payload.get("base_revision")}
    details(private, state, key, row, admitting=True)
    return {"id": key, "base_revision": payload.get("base_revision"), "task": task, "revision": revision}


def save(private, payload):
    fields(payload, ("review", "approved"))
    review = payload["review"]
    fields(review, ("id", "base_revision", "task", "revision"))
    if payload["approved"] is not True or not isinstance(review["task"], dict):
        raise ValueError("Obtain PM approval for this exact private checkpoint")
    with storage.writer_lock(private):
        raw, state = read(private)
        expected = preview(private, {**review["task"], "id": review["id"], "base_revision": review["base_revision"]}, state)
        if expected != review:
            raise ValueError("Review the changed private handoff")
        row = {"task": review["task"], "revision": review["revision"], "status": "open", "base_revision": review["base_revision"]}
        if state["work"].get(review["id"]) != row:
            state["work"][review["id"]] = row
            write(private, raw, state)
        return {"id": review["id"], "revision": row["revision"], "status": "open"}


def close(private, key, payload, *, returning):
    fields(payload, ("revision", "scope", "approved"))
    if payload["approved"] is not True:
        raise ValueError("Confirm the selected work and return with the PM")
    with storage.writer_lock(private):
        raw, state = read(private)
        row = state["work"].get(key)
        status = "returned" if returning else "finished"
        if (not row or row["task"]["scope"] != payload["scope"]
                or not (row["status"] == "open" and row["revision"] == payload["revision"]
                        or row["status"] == status and row.get("returned_from") == payload["revision"])):
            raise ValueError("Use the reviewed handoff, scope and revision")
        resolved = details(private, state, key, row)
        if returning and "parent" not in resolved:
            raise ValueError("Choose the reviewed parent before returning")
        if row["status"] == "open":
            row.update(status=status, returned_from=payload["revision"],
                       revision=fingerprint([key, row["task"], row["base_revision"], status, payload["revision"]]))
            write(private, raw, state)
        result = {"status": status, "revision": row["revision"]}
        if returning:
            result["parent"] = resolved["parent"]
        return result


def words(text):
    return re.findall(r"[^\W_]+", text.casefold())


def resume(private, query="", scope=None):
    query = " ".join(words(query))
    def matches(name, key, item_scope):
        label = " ".join(words(name))
        return ((not scope or scope == item_scope) and
                (not query or query == " ".join(words(key)) or set(query.split()) <= set(label.split())))
    with storage.writer_lock(private):
        _, state = read(private)
        found = []
        # Never reveal names or evidence from a checkpoint that has lost its grants.
        owners = {row["task"]["owner"]["record"] for row in state["work"].values()
                  if row["status"] == "open" and "owner" in row["task"]}
        for key, row in state["work"].items():
            task = row["task"]
            if row["status"] != "open" or not matches(task["name"], key, task["scope"]):
                continue
            try:
                found.append(details(private, state, key, row))
            except (OSError, ValueError, RuntimeError):
                continue
        for relative, path in task_context.private_files(private, {"workspace"}):
            name = relative.as_posix()
            if name in owners or not layout.valid_work(relative):
                continue
            try:
                # Look up the task title before reading work state or computing its revision.
                with path.open(encoding="utf-8") as stream:
                    title = next((line[2:].strip() for line in stream if line.startswith("# ")), relative.stem)
                if query and query != " ".join(words(relative.stem)) and not set(query.split()) <= set(words(title)):
                    continue
                item = native(private, name)
            except (OSError, ValueError, RuntimeError):
                continue
            # Unnamed startup drafts are unsuitable for a generic open-work list.
            if (not query and not records.specific(item["next_step"]) or not matches(item["name"], relative.stem, item["scope"])):
                continue
            found.append(item)
        exact = [item for item in found if query in {" ".join(words(item["name"])), " ".join(words(item.get("id", "")))} and query]
        found = exact or found
        if len(found) == 1:
            item = found[0]
            if item.get("journal") and not item.get("journal_status"):
                import session_journal
                item["since_checkpoint"] = session_journal.later_exchanges(
                    private, item["journal"][-1], scope=item.get("journal_reference_scope", item["scope"]))
            return {"status": "resume", "work": item}
        if found:
            return choices(found)
        return {"status": "no-current-match"}


def choices(items):
    choices_ = []
    for item in items:
        summary = {key: item[key] for key in ("name", "id", "scope", "record") if key in item}
        if (item.get("objective") and sum(peer["scope"] == item["scope"] and peer["name"] == item["name"]
                                          for peer in items) > 1):
            summary["objective"] = item["objective"]
        choices_.append(summary)
    return {"status": "clarify", "choices": choices_}


def return_candidates(private):
    """A request to return to original work still needs a current, unambiguous parent."""
    with storage.writer_lock(private):
        _, state = read(private)
        children = []
        for key, row in state["work"].items():
            if row["status"] != "open" or "parent" not in row["task"]:
                continue
            try:
                children.append(details(private, state, key, row))
            except (OSError, ValueError, RuntimeError):
                continue
        if len(children) == 1:
            child = children[0]
            return {"status": "confirm-return", "child": {k: child[k] for k in ("id", "revision", "name", "scope")},
                    "parent": child["parent"]}
        return choices(children) if children else None


REQUEST_LEAD = r"^(?:(?:please|let['’]s|(?:can|could|would) (?:we|you))\s+)*"
PROMPT = re.compile(
    REQUEST_LEAD +
    r"(?:resume|continue(?: working on)?|pick (?:back )?up(?: where we left off (?:on|with))?|"
    r"where did we (?:leave off|stop) (?:on|with)|return to|get back to|go back to|take me back to)"
    r"(?:\s+(?:(?:the|our|my|that)\s+)?(.+?))?[.!?]*$", re.I)


CURRENT_TASK = re.compile(
    REQUEST_LEAD + r"(?:continue|resume|keep going|carry on|go on|pick (?:back )?up where we left off)"
    r"(?:\s+(?:working on |with )?(?:this|that|it|the current (?:task|handoff)))?[.!? ]*$", re.I)
SHORT_FOLLOWUP = re.compile(
    r"(?:(?:can|could|would) you (?:please )?)?(?:yes|no|agreed|what(?:'s| is| comes) next|what should we do next|"
    r"(?:please )?(?:shorten|revise|tighten|update|rewrite) (?:it|that|this)|"
    r"(?:please )?make (?:it|that|this) (?:shorter|clearer|more concise))[.!? ]*", re.I)
# Remove only the referential introduction. The remaining subject must be grounded in the checkpoint.
FOLLOWUP_LEAD = re.compile(
    r"^(?:(?:please|now|then)\s+)*(?:keep (?:the )?(?:(?:existing|same|current) )?|"
    r"(?:what|how) about (?:the )?|(?:can|could) we (?:keep|review) (?:the )?)", re.I)


def active_key(client, session):
    if client in ("codex", "claude") and isinstance(session, str) and session:
        return "active-handoff\0" + client + "\0" + session
    return None


def same_task(private, work, prompt):
    """Retain the exact work pointer only for a related follow-up in a compatible scope."""
    mode, prompt = conversation.mode_request(prompt)
    if (not prompt and not mode) or turn_intent.leaves_handoff(prompt) or task_context.SWITCH.match(prompt):
        return False
    if not CURRENT_TASK.fullmatch(prompt) and PROMPT.fullmatch(prompt):
        return False  # A named resume that could not be resolved leaves the old task.
    named = task_context.WORK_RECORD.search(prompt)
    if named and named[1] != work.get("record", work.get("owner", {}).get("record")):
        return False
    if not prompt or CURRENT_TASK.fullmatch(prompt) or SHORT_FOLLOWUP.fullmatch(prompt) or conversation.acknowledgement(prompt):
        return True
    # Every substantive part must refer to this work before joining the entire exchange to its journal.
    wording = " ".join(work.get(k, "") for k in ("name", "objective", "open_question", "next_step", "checkpoint"))
    subjects = task_context.words(wording)
    clauses = [part.strip() for part in re.split(r"[.!?;\n]+|,?\s+and (?:also |then )?", prompt, flags=re.I) if part.strip()]
    for clause in clauses:
        if task_context.mentions(clause, work["name"]):
            continue
        terms = task_context.words(FOLLOWUP_LEAD.sub("", clause))
        if not terms or not terms <= subjects:
            return False
    if not clauses:
        return False
    # A substantive follow-up can name a conflicting subject. Resolve the PM's words independently of the terminal directory.
    context = task_context.resolve(private, prompt)
    if context["status"] == "ambiguous":
        return False
    subject = context.get("scope", {})
    if subject:
        levels = [f"product/{subject['product']}"] if subject.get("product") else []
        levels += [f"{key}/{subject[key]}" for key in ("area", "initiative") if subject.get(key)]
        resolved = "/".join(levels) or ("company" if subject.get("company") else "stakeholders")
        if work["scope"] != resolved and not work["scope"].startswith(resolved + "/"):
            return False
    return True


def current_checkpoint(private, selected):
    if "record" in selected:
        work = native(private, selected["record"])
    else:
        _, index = read(private)
        row = index["work"][selected["id"]]
        if row["status"] != "open":
            raise ValueError("The selected handoff has closed")
        work = details(private, index, selected["id"], row)
    if selected["revision"] != work["revision"]:
        raise ValueError("Review the changed checkpoint")
    return work


def context_scope(private, work):
    """Translate a reviewed handoff scope when it names a task-context subject."""
    subject = work["scope"]
    if subject in {"company", "stakeholders"}:
        return {subject: True}
    product = re.fullmatch(r"product/([a-z0-9-]+)(?:/(area|initiative)/([a-z0-9-]+))?", subject)
    if product and (private / layout.product(product[1])).is_file():
        return {"product": product[1], "area": product[3] if product[2] == "area" else None,
                "initiative": product[3] if product[2] == "initiative" else None}
    return {}  # An independent checkpoint can exist without any registered context subject.


def bind_active(private, client, payload, *, work=None, continuing=False):
    """Keep only the selected checkpoint's identity, revision and optional journal cursor."""
    import session_journal
    key = active_key(client, payload.get("session_id"))
    if (not key or not session_journal.visible_turn(payload)
            or (work is None and not task_context.previous_scope(private, key))):
        return None
    try:
        with storage.writer_lock(private):
            previous = task_context.previous_scope(private, key)
            current = work  # for_prompt holds the workspace lock from lookup through selection.
            if continuing and previous:
                try:
                    candidate = current_checkpoint(private, previous)
                    if same_task(private, candidate, turn_intent.instruction(payload["prompt"])):
                        current = candidate
                except (KeyError, ValueError, OSError, RuntimeError, sqlite3.Error):
                    pass  # A withdrawn or changed checkpoint releases the pointer.
            bound = {}
            if current:
                bound = {k: current[k] for k in ("id", "record", "revision") if k in current}
                # Keep the last cursor for duplicate hooks. A new binding must still prove adjacency and consent.
                if all(previous.get(k) == v for k, v in bound.items()) and previous.get("event"):
                    bound["event"] = previous["event"]
                if work is not None or bound.get("event"):
                    try:
                        event = session_journal.bind_turn_scope(private, client, payload, current["journal_scope"],
                                                                previous=None if work is not None else bound["event"])
                        if event:
                            bound["event"] = event
                    except (ValueError, OSError, sqlite3.Error):
                        pass  # Journal availability has no bearing on independently approved work.
            if current or previous:
                task_context.remember_scope(private, key, bound)
            return current
    except (OSError, ValueError, RuntimeError):
        return None  # Failure of the session cache cannot interrupt the primary task.


def for_prompt(private, prompt, *, client=None, payload=None):
    """Resolve a PM's request and bind that exact selection before releasing the workspace lock."""
    if not isinstance(prompt, str) or len(prompt) > 240 or "\n" in prompt:
        return None
    match_ = PROMPT.fullmatch(prompt.strip())
    query = (match_[1] or "") if match_ else ""
    returning = query.casefold() in {"original task", "original work", "main task", "parent task", "parent", "main discussion"}
    if query.casefold() in {"coaching", "setup", "onboarding", "area setup", "stakeholder profile setup"}:
        return None
    if not match_ and not re.fullmatch(r"(?i)(?:what(?:'s| is) (?:still )?open|where did we leave off)[?.! ]*", prompt.strip()):
        return None
    try:
        with storage.writer_lock(private):
            result = return_candidates(private) if returning else resume(private, query)
            if not result or result["status"] == "no-current-match":
                return None
            if payload is not None:
                bind_active(private, client, payload, work=result.get("work"))
            return result
    except (ValueError, OSError, RuntimeError):
        return {"status": "unavailable"}


def check_workspace(private):
    try:
        read(private)
        return []
    except (OSError, ValueError, RuntimeError):
        return [f"{FILE}: invalid private work checkpoint index"]


def add_commands(commands):
    group = commands.add_parser("handoff", help="Save reviewed work and resume it by name in either client")
    group.set_defaults(hub_action=run)
    ops = group.add_subparsers(dest="operation", required=True)
    for verb in ("preview", "save", "grant"):
        ops.add_parser(verb, help="Read reviewed task data on standard input")
    ops.add_parser("revoke").add_argument("grant")
    for verb in ("finish", "return"):
        ops.add_parser(verb).add_argument("id", type=layout.slug)
    query = ops.add_parser("resume", help="Find open work by its plain-language name")
    query.add_argument("name", nargs="*", default=[])
    query.add_argument("--scope")


def run(root, args, prepare_write):
    action = args.operation
    if action not in {"resume", "preview"}:
        prepare_write(root)
    private = workspace.repo(root, "workspace")
    if action == "resume":
        result = resume(private, " ".join(args.name), args.scope)
    elif action == "revoke":
        result = revoke(private, args.grant)
    else:
        payload = storage.json_input(sys.stdin.read())
        if action in {"return", "finish"}:
            result = close(private, args.id, payload, returning=action == "return")
        else:
            result = {"preview": preview, "save": save, "grant": grant_reference}[action](private, payload)
    print(json.dumps(result, ensure_ascii=False, indent=2))
