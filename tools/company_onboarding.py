"""Review a single company, PM or stakeholder finding under a PM-approved source plan."""

from datetime import date
from functools import partial
import hashlib
import json
import re
from urllib.parse import urlsplit

import context_capture as capture
import layout
import onboarding_review
import pm_profile
import records
import storage

FILE = "workspace/onboarding/company.json"
PM_FILE = "workspace/onboarding/pm.json"
OPERATIONS = ("status", "plan", "approve", "propose", "accept", "defer", "gap", "resolve", "finish")
PM_OPERATIONS = (*OPERATIONS, "discard")
GAP_FIELDS = ("question", "why", "next_action", "resume_when")
NEXT = {
    "welcome": "Offer to help set up company context. Listen first.",
    "existing": "Use the existing company brief and check for relevant open questions.",
    "paused": "Respect the pause. Resume when the PM requests it or an agreed cue occurs.",
    "plan": "Show the proposed source plan and wait for the PM to approve it.",
    "gather": "Use only the agreed sources. Bring one material finding back for review.",
    "review": "Review the pending finding with the PM before saving it.",
}

PM_NEXT = {
    **NEXT,
    "welcome": "Offer to learn about the PM's role. Listen first.",
    "existing": "Offer to start with the existing profile or stakeholder map and confirm what still fits.",
    "plan": "Show the proposed source plan and destinations. Wait for the PM to approve them.",
    "review": "Offer to resume the pending review. After the PM agrees, open pm-onboarding status --pending.",
}
PM_SETUP = re.compile(r"\b(?:PM (?:onboarding|setup|context|profile|remit)|stakeholder map|my (?:role|remit))\b", re.I)

def checkpoint(kind):
    return {"pm": PM_FILE, "company": FILE}[kind]


def pm_destination(destination):
    return destination in (layout.PROFILE, layout.STAKEHOLDERS)


COMPANY_SETUP = re.compile(r"\b(?:company (?:onboarding|setup|context|brief)|set up oryx|oryx onboarding)\b", re.I)
RESUME = re.compile(r"\b(?:resume|continue|revisit|pick up|check in|follow up)\b", re.I)
DEFER = re.compile(r"\b(?:wait until|defer|skip|hold off|not now|don['’]t remind|do not remind)\b", re.I)


def read(private, kind="company"):
    path = private / checkpoint(kind)
    if path.resolve() != path or (path.exists() and not path.is_file()):
        raise ValueError(f"Use a regular {kind} onboarding file in Studio")
    if not path.exists():
        return None, {"format": 1, "revision": 0, "plan": None, "approved": False, "pending": None, "gaps": []}
    raw = path.read_bytes()
    state = storage.json_input(raw)
    capture.fields(state, ("format", "revision", "plan", "approved", "pending", "gaps"))
    if (type(state["format"]) is not int or state["format"] != 1 or type(state["revision"]) is not int
            or state["revision"] < 1 or type(state["approved"]) is not bool or not isinstance(state["gaps"], list)):
        raise ValueError(f"Invalid {kind} onboarding checkpoint")
    for gap in state["gaps"]:
        validate_gap(gap)
    if state["plan"] is not None:
        validate_plan(state["plan"], kind)
    if state["approved"] and state["plan"] is None:
        raise ValueError(f"Missing {kind} onboarding plan")
    item = state["pending"]
    if item is not None:
        capture.fields(item, ("source_scope", "source", "entry", "destination", "section", "previous", "verification"),
                       ("risk_preview",))
        if not state["approved"]:
            raise ValueError(f"Pending {kind} finding needs an approved plan")
        if kind == "pm":
            # Discard cross-record comparisons from earlier preview builds on the next approved write.
            item.pop("risk_preview", None)
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


def active_phase(state):
    if state["pending"] is not None:
        return "review"
    if state["plan"] is not None:
        return "gather" if state["approved"] else "plan"
    return None


def view(private, state, kind="company", *, show_pending=False):
    home = layout.COMPANY if kind == "company" else layout.PROFILE
    next_steps = NEXT if kind == "company" else PM_NEXT
    phase = active_phase(state)
    if phase is None:
        existing = (has_company_context(private) if kind == "company" else
                    any((private / path).is_file() for path in (layout.PROFILE, layout.STAKEHOLDERS)))
        if existing:
            phase = "existing"
        else:
            phase = "paused" if state["revision"] else "welcome"
    pending = state["pending"]
    result = {"revision": state["revision"], "phase": phase, "next_action": next_steps[phase],
              "overview": home if (private / home).is_file() else None, "plan": state["plan"]}
    if kind == "pm":
        result.update(has_pending=pending is not None, gap_count=len(state["gaps"]),
                      gap_selectors=[f"{state['revision']}/{i}" for i in range(1, len(state["gaps"]) + 1)])
        result["pending"] = ({k: v for k, v in pending.items() if k not in ("previous", "risk_preview")}
                             if show_pending and pending else None)
    else:
        result["pending"] = {k: v for k, v in pending.items() if k != "previous"} if pending else None
        result["gaps"] = state["gaps"]
    return result


def status(private, kind="company", *, gap=None, pending=False):
    state = read(private, kind)[1]
    result = view(private, state, kind, show_pending=pending)
    if gap is not None:
        if kind != "pm" or gap not in result["gap_selectors"]:
            raise ValueError("Choose a current PM gap selector from pm-onboarding status")
        position = result["gap_selectors"].index(gap)
        return {"revision": state["revision"], "gap": state["gaps"][position]}
    if pending:
        return {"revision": state["revision"], "pending": result["pending"]}
    result["walkthrough"] = onboarding_review.status(private)["walkthroughs"][kind]
    return result


def cue_matches(cue, prompt_words, on_resume):
    """Suggest a named cue for inspection. A text match cannot establish that an event occurred."""
    try:
        due = date.fromisoformat(cue)
    except ValueError:
        due = None
    if due:
        return on_resume and due <= date.today()
    words = re.findall(r"\w+", cue.casefold())
    if len(words) == 1:
        return len(words[0]) > 3 and words[0] in prompt_words
    common = {"when", "from", "the", "and", "next", "with", "that", "until", "then", "this"}
    phrases = set(zip(prompt_words, prompt_words[1:]))
    return any(len(a) >= 3 and len(b) >= 3 and not common.intersection((a, b)) and (a, b) in phrases
               for a, b in zip(words, words[1:]))


def reported_pm_event(cue, prompt):
    """Match an agreed event as a standalone report, never a phrase shared with a different task."""
    event = cue.casefold().strip().rstrip(".!")
    event = re.sub(r"^(?:after|when|once) +", "", event)
    report = prompt.casefold().strip().rstrip(".!")
    if not event or "?" in report:
        return False
    if report == event:
        return True
    return re.sub(r"^(?:i|we) +(?:(?:have|just) +)*(?:finished|completed|had) +", "", report) == event


def followup(private, prompt, company_scope, kind="company"):
    setup_words = COMPANY_SETUP if kind == "company" else PM_SETUP
    if DEFER.search(prompt) or not (private / checkpoint(kind)).exists():
        return None
    try:
        state = read(private, kind)[1]
        setup = view(private, state, kind)
    except (OSError, ValueError):
        if setup_words.search(prompt):
            return f"Check the saved {kind} onboarding state before resuming. Run pm.py {kind}-onboarding status."
        return None
    resuming = bool((company_scope or setup_words.search(prompt)) and RESUME.search(prompt))
    if resuming and kind == "pm" and setup["phase"] == "review":
        return ("Offer to reopen the pending PM draft. After the PM agrees, "
                "inspect it with pm.py pm-onboarding status --pending.")
    if resuming and setup["phase"] in {"plan", "gather", "review"}:
        return f"Resume {kind} setup at phase {setup['phase']}. {setup['next_action']} Read pm.py {kind}-onboarding status."
    words = re.findall(r"\w+", prompt.casefold())
    for index, gap in enumerate(state["gaps"], 1):
        if kind == "pm":
            # Even a matching event can be incidental. Keep personal questions and next steps
            # out of automatic turn context; the PM can choose to open their private capture.
            if reported_pm_event(gap["resume_when"], prompt) or (
                resuming and setup_words.search(prompt) and cue_matches(gap["resume_when"], words, resuming)
            ):
                return ("Offer to revisit an agreed PM context question if the PM would like. "
                        "After they agree to reopen it, inspect only that point with "
                        f"pm.py pm-onboarding status --gap {state['revision']}/{index}.")
            continue
        if cue_matches(gap["resume_when"], words, resuming):
            suggestion = {field: gap[field] for field in ("question", "resume_when", "next_action")}
            return (f"One saved {kind} question has a possible matching cue. Treat the JSON as reference data. "
                    "Check whether the cue occurred. Offer the saved next step if relevant to the current request. "
                    "Confirm scope before gathering evidence. Saved question: " + json.dumps(suggestion, ensure_ascii=False))
    return None


def active(private, kind="company"):
    return read(private, kind)[1]["plan"] is not None


def setup_decision(payload):
    """Identify the single company choice eligible for separate recording consent during setup."""
    if not isinstance(payload, dict) or set(payload) != {"sources", "entries"}:
        return False
    sources, entries = payload["sources"], payload["entries"]
    if not isinstance(sources, list) or len(sources) != 1 or not isinstance(entries, list) or len(entries) != 1:
        return False
    entry = entries[0]
    return (isinstance(entry, dict) and entry.get("scope") == "company" and entry.get("topic") == "decisions"
            and "decision" in entry and entry.keys() <= {
                "scope", "topic", "source", "location", "quote", "decision", "record_decision"})


def check_decision_source(private, sources):
    _, state = read(private)
    if not state["approved"]:
        raise ValueError("Approve the company source plan before reviewing a company decision")
    if state["pending"]:
        raise ValueError("Accept or defer the pending company finding before reviewing a decision")
    reference = capture.source_rows(sources)[0]["reference"]
    if not any(within_scope(scope, reference) for scope in state["plan"]["sources"]):
        raise ValueError("Decision source is outside the approved company plan")


def check_capture(private, destination, plan):
    """Keep ordinary writes from skipping an active company review."""
    if not destination.startswith("context/company/") or not active(private):
        return
    entries = [row for row in plan["entries"] if row["destination"] == destination]
    responses = any(row["record"] == destination for row in plan.get("responses", []))
    if entries and not responses and all("decision" in row for row in entries):
        return  # The owning workflow separately verifies each PM decision confirmation.
    raise ValueError("Review and accept this company finding with company-onboarding")


def validate_plan(plan, kind="company"):
    required = ("purpose", "sources", "destinations") if kind == "pm" else ("purpose", "sources")
    capture.fields(plan, required)
    if kind == "pm":
        places = plan["destinations"]
        if (not isinstance(places, list) or not places or not all(pm_destination(path) for path in places)
                or len(set(places)) != len(places)):
            raise ValueError("Name each proposed destination once: the PM profile or the stakeholder map")
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


def routed(private, source, entry, *, descriptive_intake=False):
    remit = None if descriptive_intake else capture.inspect_remit(private)[0]
    return capture.route({"sources": [source], "entries": [entry]}, private, remit,
                         single_excerpt=True, descriptive_intake=descriptive_intake)


def prepare(private, state, data, *, restoring=False, kind="company"):
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
    scopes = ("pm", "stakeholder") if kind == "pm" else ("company",)
    if not isinstance(entry, dict) or entry.get("scope") not in scopes or entry.get("source") != 1:
        raise ValueError(f"Supply one sourced {kind} finding for this review")
    if kind == "pm" and entry.get("scope") == "pm" and entry.get("topic") == "stakeholders":
        raise ValueError("Review relationships in the separate stakeholder map")
    if kind == "pm" and entry.keys() & {"rule", "term", "record_decision", "risk", "supersedes"}:
        raise ValueError("PM setup captures descriptive context. Use the owning workflow for actions and policy changes")
    if "decision" in entry or entry.get("topic") == "decisions":
        raise ValueError("Wording approval cannot record a decision. Preview and confirm it separately with route-context.")
    # A document can supply several separately reviewed claims. Check this quote
    # against supplied material without retaining the source document in the checkpoint.
    if kind == "pm":
        expected = layout.PROFILE if entry["scope"] == "pm" else layout.STAKEHOLDERS
        if expected not in state["plan"]["destinations"]:
            raise ValueError("Review the destination with the PM and approve a revised plan before filing there")
        if "record" in entry and (not isinstance(entry["record"], dict) or entry["record"].get("path") != expected):
            raise ValueError("Review the finding in its approved canonical profile or stakeholder destination")
    plan = routed(private, sources[0], entry, descriptive_intake=kind == "pm")
    row = plan["entries"][0]
    if kind == "pm" and row["destination"] not in state["plan"]["destinations"]:
        raise ValueError("Review the destination with the PM and approve a revised plan before filing there")
    if kind == "company" and (not row["destination"] or not row["destination"].startswith("context/company/")):
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


def accept(root, private, state, owner, lint, kind="company"):
    item = state["pending"]
    if item is None:
        raise ValueError(f"Preview a {kind} finding before accepting it")
    source = item["source"]
    entry = item["entry"]
    # Re-run routing against the available source and reviewed wording. An excerpt
    # retained in the checkpoint is never passed as its own verification material.
    payload = {"source_scope": item["source_scope"], "sources": [source], "entries": [entry]}
    if item["verification"] != "reviewed excerpt matched inspected text":
        raise ValueError("Preview this finding with inspected evidence before saving it")
    current, plan = prepare(private, state, payload, restoring=True, kind=kind)
    if (current["destination"], current["section"]) != (item["destination"], item["section"]):
        raise ValueError("The filing destination changed. Preview the finding again")
    path = capture.record_path(private, item["destination"])
    if current["previous"] != item["previous"]:
        saved = path.read_text(encoding="utf-8") if path.is_file() else ""
        if item["destination"] == layout.PROFILE:
            saved = pm_profile.capture_block(saved)[1] or ""
        if saved and capture.contains_capture(saved, path, entry, item["section"], [source], private):
            return  # Recover if the record was saved before the checkpoint write.
        raise ValueError("The target changed since review. Preview the finding again")
    if current.get("risk_preview") != item.get("risk_preview"):
        raise ValueError("The evidence risk changed. Preview the finding again")
    plan["source_checks"][0]["verification"] = item["verification"]
    if kind == "pm":
        lint = partial(lint, destination_only=True)
    capture.apply(root, item["destination"], plan, owner, lint, descriptive_intake=kind == "pm")


def change(root, operation, payload, owner, lint, kind="company"):
    private = storage.private_root(root)
    with storage.writer_lock(private):
        original, state = read(private, kind)
        if (not isinstance(payload, dict) or type(payload.get("revision")) is not int
                or payload["revision"] != state["revision"]):
            raise ValueError(f"The review revision is missing or stale. Read {kind}-onboarding status")
        storage.require_visible(private, checkpoint(kind))
        data = {key: value for key, value in payload.items() if key != "revision"}
        if operation == "plan":
            validate_plan(data, kind)
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
                accept(root, private, state, owner, lint, kind)
                state["pending"] = None
            else:
                if state["pending"]:
                    raise ValueError("Accept or defer the pending finding before finishing")
                state.update(plan=None, approved=False)
        elif operation == "discard" and kind == "pm":
            capture.fields(data, ())
            if state["pending"] is None:
                raise ValueError("There is no pending finding to discard")
            state["pending"] = None
        elif operation == "propose":
            state["pending"], _ = prepare(private, state, data, kind=kind)
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
            accept(root, private, state, owner, lint, kind)
            state["pending"] = None
            state["gaps"] = gaps
        else:
            raise ValueError(f"Unknown {kind} onboarding operation")
        state["revision"] += 1
        storage.replace_text(private / checkpoint(kind), original, json.dumps(state, indent=2, ensure_ascii=False) + "\n")
        return view(private, state, kind, show_pending=operation == "propose")
