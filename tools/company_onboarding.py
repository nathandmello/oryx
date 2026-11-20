"""Review one company-context finding under a PM-approved source plan."""

import hashlib
import json
import re
from urllib.parse import urlsplit

import context_capture as capture
import layout
import records
import storage

FILE = "workspace/onboarding/company.json"
OPERATIONS = ("status", "plan", "approve", "propose", "accept", "defer", "gap", "resolve", "finish")
GAP_FIELDS = ("question", "why", "next_action", "resume_when")
NEXT = {
    "welcome": "Offer to help set up company context. Listen first.",
    "existing": "Use the existing company brief and check for relevant open questions.",
    "paused": "Respect the pause. Resume when the PM requests it or an agreed cue occurs.",
    "plan": "Show the proposed source plan and wait for the PM to approve it.",
    "gather": "Use only the agreed sources. Bring one material finding back for review.",
    "review": "Review the pending finding with the PM before saving it.",
}


def read(private):
    path = private / FILE
    if path.resolve() != path:
        raise ValueError("Use a regular company onboarding file in Studio")
    if not path.exists():
        return None, {"format": 1, "revision": 0, "plan": None, "approved": False, "pending": None, "gaps": []}
    raw = path.read_bytes()
    state = storage.json_input(raw)
    capture.fields(state, ("format", "revision", "plan", "approved", "pending", "gaps"))
    if (type(state["format"]) is not int or state["format"] != 1 or type(state["revision"]) is not int
            or state["revision"] < 1 or type(state["approved"]) is not bool or not isinstance(state["gaps"], list)):
        raise ValueError("Invalid company onboarding checkpoint")
    for gap in state["gaps"]:
        validate_gap(gap)
    if state["plan"] is not None:
        validate_plan(state["plan"])
    if state["approved"] and state["plan"] is None:
        raise ValueError("Missing company onboarding plan")
    item = state["pending"]
    if item is not None:
        capture.fields(item, ("source_scope", "source", "entry", "destination", "section", "previous", "verification"),
                       ("risk_preview",))
        if not state["approved"]:
            raise ValueError("Pending company finding needs an approved plan")
    return raw, state


def has_company_context(private):
    target = private / layout.COMPANY
    if target.resolve() != target or not target.is_file():
        return False
    text = target.read_text(encoding="utf-8")
    if not text.startswith("<!-- pm: company-context -->"):
        return bool(text.strip())  # Offer to resume or inspect an existing untyped brief.
    for heading, _, start, end in records.section_blocks(text):
        if heading in records.CONTEXT_METADATA:
            continue
        _, content = records.split_context_lead(text[start:end])
        for line in content.splitlines():
            if line.strip() and not line.startswith("|") and not records.PLACEHOLDER.search(line):
                return True
    rows, _ = records.table(text, "Sources", records.SOURCE_COLUMNS)
    return any(re.fullmatch(r"S[1-9]\d*", row[0]) for row in rows)


def view(private, state):
    if state["pending"] is not None:
        phase = "review"
    elif state["plan"] is not None:
        phase = "gather" if state["approved"] else "plan"
    elif has_company_context(private):
        phase = "existing"
    else:
        phase = "paused" if state["revision"] else "welcome"
    pending = state["pending"]
    if pending:
        pending = {k: v for k, v in pending.items() if k != "previous"}
    return {"revision": state["revision"], "phase": phase, "next_action": NEXT[phase],
            "overview": layout.COMPANY if (private / layout.COMPANY).is_file() else None,
            "plan": state["plan"], "pending": pending, "gaps": state["gaps"]}


def status(private):
    return view(private, read(private)[1])


def active(private):
    return read(private)[1]["plan"] is not None


def check_capture(private, destination, plan):
    """Keep ordinary writes from skipping an active company review."""
    if not destination.startswith("context/company/") or not active(private):
        return
    entries = [row for row in plan["entries"] if row["destination"] == destination]
    responses = any(row["record"] == destination for row in plan.get("responses", []))
    if entries and not responses and all("decision" in row for row in entries):
        return  # The owning workflow separately verifies each PM decision confirmation.
    raise ValueError("Review and accept this company finding with company-onboarding")


def validate_plan(plan):
    capture.fields(plan, ("purpose", "sources"))
    capture.line(plan["purpose"], "Plan purpose")
    sources = plan["sources"]
    if not isinstance(sources, list) or not sources:
        raise ValueError("Name the file, interview, site or connected collection to read")
    for source in sources:
        capture.line(source, "Source scope")
    if len(sources) != len(set(sources)):
        raise ValueError("List each approved source scope once")


def validate_gap(gap):
    capture.fields(gap, GAP_FIELDS, ("basis",))
    if "basis" in gap:
        capture.fields(gap["basis"], ("reference", "date", "location", "quote"))
        for field, value in gap["basis"].items():
            capture.line(value, field)
    for field in GAP_FIELDS:
        capture.line(gap[field], field)


def source_target(reference):
    link = re.fullmatch(r"\[[^\]\n]+\]\((<[^>\n]+>|[^\s)]+)\)", reference)
    return link[1].strip("<>") if link else reference


def within_scope(scope, reference):
    """Bind the actual reference to an exact source or an approved HTTPS subtree."""
    actual = source_target(reference)
    allowed = source_target(scope)
    if actual == allowed:
        return True
    base, candidate = urlsplit(allowed), urlsplit(actual)
    if (base.scheme != "https" or not base.netloc or base.username is not None or base.query or base.fragment
            or not base.path.endswith("/") or candidate.scheme != base.scheme
            or candidate.netloc != base.netloc or not candidate.path.startswith(base.path)):
        return False
    return (not {".", ".."}.intersection(candidate.path.split("/"))
            and not re.search(r"\\|%(?:2e|2f|5c|25)", candidate.path, re.I))


def fingerprint(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def routed(private, source, entry):
    return capture.route({"sources": [source], "entries": [entry]}, private, capture.inspect_remit(private)[0], single_excerpt=True)


def prepare(private, state, data, *, restoring=False):
    capture.fields(data, ("source_scope", "sources", "entries"))
    if not state["approved"]:
        raise ValueError("Show and approve the source plan before proposing a finding")
    scope = data["source_scope"]
    if scope not in state["plan"]["sources"]:
        raise ValueError("The source is outside the approved plan")
    sources, entries = data["sources"], data["entries"]
    if not isinstance(sources, list) or len(sources) != 1 or not isinstance(entries, list) or len(entries) != 1:
        raise ValueError("Review one attributed finding at a time")
    source = capture.source_rows(sources)[0]
    if not within_scope(scope, source["reference"]):
        raise ValueError("Source reference is outside the approved source scope")
    entry = entries[0]
    if not isinstance(entry, dict) or entry.get("scope") != "company" or entry.get("source") != 1:
        raise ValueError("Supply one sourced company finding for this review")
    if "decision" in entry or entry.get("topic") == "decisions":
        raise ValueError("Wording approval cannot record a product decision. Use its separate decision workflow.")
    # A document can supply several separately reviewed claims. Check this quote
    # against supplied material without retaining the source document in the checkpoint.
    plan = routed(private, sources[0], entry)
    row = plan["entries"][0]
    if not row["destination"] or not row["destination"].startswith("context/company/"):
        raise ValueError("Choose the company overview or a qualifying company supporting record")
    path = capture.record_path(private, row["destination"])
    verification = plan["source_checks"][0]["verification"]
    if not restoring and verification != "reviewed excerpt matched inspected text":
        raise ValueError("Supply inspected source text or a readable local source for the reviewed finding")
    pending = {"entry": entry, "source": source, "source_scope": scope, "destination": row["destination"],
               "section": row["section"], "previous": fingerprint(path), "verification": verification}
    if plan.get("risk_preview"):
        pending["risk_preview"] = plan["risk_preview"]
    return pending, plan


def accept(root, private, state, owner, lint):
    item = state["pending"]
    if item is None:
        raise ValueError("Preview a company finding before accepting it")
    source = item["source"]
    entry = item["entry"]
    # Re-run routing against the available source and reviewed wording. An excerpt
    # retained in the checkpoint is never passed as its own verification material.
    payload = {"source_scope": item["source_scope"], "sources": [source], "entries": [entry]}
    if item["verification"] != "reviewed excerpt matched inspected text":
        raise ValueError("Preview this finding with inspected evidence before saving it")
    current, plan = prepare(private, state, payload, restoring=True)
    if (current["destination"], current["section"]) != (item["destination"], item["section"]):
        raise ValueError("The filing destination changed. Preview the finding again")
    path = capture.record_path(private, item["destination"])
    if current["previous"] != item["previous"]:
        if path.is_file() and capture.contains_capture(path.read_text(encoding="utf-8"), path, entry,
                                                      item["section"], [source], private):
            return  # Recover if the record was saved before the checkpoint write.
        raise ValueError("The target changed since review. Preview the finding again")
    if current.get("risk_preview") != item.get("risk_preview"):
        raise ValueError("The evidence risk changed. Preview the finding again")
    plan["source_checks"][0]["verification"] = item["verification"]
    capture.apply(root, item["destination"], plan, owner, lint)


def change(root, operation, payload, owner, lint):
    private = storage.private_root(root)
    with storage.writer_lock(private):
        original, state = read(private)
        if (not isinstance(payload, dict) or type(payload.get("revision")) is not int
                or payload["revision"] != state["revision"]):
            raise ValueError("The review revision is missing or stale. Read company-onboarding status")
        storage.require_visible(private, FILE)
        data = {key: value for key, value in payload.items() if key != "revision"}
        if operation == "plan":
            validate_plan(data)
            if state["pending"]:
                raise ValueError("Accept or defer the pending finding before changing the source plan")
            state.update(plan=data, approved=False)
        elif operation in {"approve", "finish", "accept"}:
            capture.fields(data, ())
            if operation == "approve":
                if state["plan"] is None or state["approved"]:
                    raise ValueError("Present the proposed plan before approving it")
                state["approved"] = True
            elif operation == "accept":
                accept(root, private, state, owner, lint)
                state["pending"] = None
            else:
                if state["pending"]:
                    raise ValueError("Accept or defer the pending finding before finishing")
                state.update(plan=None, approved=False)
        elif operation == "propose":
            state["pending"], _ = prepare(private, state, data)
        elif operation in {"defer", "gap"}:
            capture.fields(data, GAP_FIELDS)
            validate_gap(data)
            existing = next((gap for gap in state["gaps"] if gap["question"] == data["question"]), {})
            if "basis" in existing:
                data["basis"] = existing["basis"]
            if operation == "defer":
                if state["pending"] is None:
                    raise ValueError("There is no pending finding to defer")
                item = state["pending"]
                data["basis"] = {**{k: item["source"][k] for k in ("reference", "date")},
                                 **{k: item["entry"][k] for k in ("location", "quote")}}
                state["pending"] = None
            state["gaps"] = [gap for gap in state["gaps"] if gap["question"] != data["question"]] + [data]
        elif operation == "resolve":
            capture.fields(data, ("question",))
            gaps = [gap for gap in state["gaps"] if gap["question"] != data["question"]]
            if len(gaps) == len(state["gaps"]):
                raise ValueError("Choose an existing gap to resolve")
            if not state["pending"] or state["pending"]["entry"].get("answers") != data["question"]:
                raise ValueError("Review a sourced answer to the exact open question before resolving it")
            accept(root, private, state, owner, lint)
            state["pending"] = None
            state["gaps"] = gaps
        else:
            raise ValueError("Unknown company onboarding operation")
        state["revision"] += 1
        storage.replace_text(private / FILE, original, json.dumps(state, indent=2, ensure_ascii=False) + "\n")
        return view(private, state)
