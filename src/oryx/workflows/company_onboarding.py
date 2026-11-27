"""Review one context finding under a PM-approved source plan."""

from datetime import date
from functools import partial
import hashlib
import json
import re
from ingestion_signals import within_scope

import context_capture as capture
import layout
import onboarding_review
import pm_profile
import product_intake
import records
import storage

FILE = "workspace/onboarding/company.json"
PM_FILE = "workspace/onboarding/pm.json"
PRODUCT_FILE = "workspace/onboarding/product.json"
OPERATIONS = ("status", "plan", "approve", "propose", "accept", "defer", "gap", "resolve", "finish")
PM_OPERATIONS = (*OPERATIONS, "discard")
PRODUCT_OPERATIONS = PM_OPERATIONS
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

PRODUCT_NEXT = {
    **PM_NEXT,
    "welcome": "Use the confirmed remit to discuss the product as it operates today.",
    "existing": "Use the existing product or area brief. Review one relevant finding at a time.",
    "review": "Offer to reopen the product finding with product-onboarding status --pending.",
}
PRODUCT_SETUP = re.compile(r"\b(?:product (?:onboarding|setup|context|brief)|area (?:context|brief))\b", re.I)


def checkpoint(kind):
    return {"pm": PM_FILE, "company": FILE, "product": PRODUCT_FILE}[kind]


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
        validate_gap(gap, kind)
    if state["plan"] is not None:
        validate_plan(state["plan"], kind)
    if state["approved"] and state["plan"] is None:
        raise ValueError(f"Missing {kind} onboarding plan")
    item = state["pending"]
    if item is not None:
        capture.fields(item, ("source_scope", "source", "entry", "destination", "section", "previous", "verification"),
                       ("risk_preview", "creates_parent", "local_source") if kind == "product" else ("risk_preview", "local_source"))
        if not state["approved"]:
            raise ValueError(f"Pending {kind} finding needs an approved plan")
        if kind in ("pm", "product"):
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
    next_steps = {"company": NEXT, "pm": PM_NEXT, "product": PRODUCT_NEXT}[kind]
    if kind == "product":
        current = product_intake.scope(private)
        subject = state["plan"]["subject"] if state["plan"] else (
            None if current["selection_required"] else current["subject"])
        if subject and "/area/" in subject:
            home = product_intake.places(state["plan"])[3] if state["plan"] else None
        else:
            home = layout.product(subject.split("/")[1]) if subject else None
    phase = active_phase(state)
    if phase is None:
        if kind == "product":
            existing = bool(home and (private / home).is_file())
        elif kind == "company":
            existing = has_company_context(private)
        else:
            existing = any((private / path).is_file() for path in (layout.PROFILE, layout.STAKEHOLDERS))
        if existing:
            phase = "existing"
        else:
            phase = "paused" if state["revision"] else "welcome"
    pending = state["pending"]
    result = {"revision": state["revision"], "phase": phase, "next_action": next_steps[phase],
              "overview": home if home and (private / home).is_file() else None, "plan": state["plan"]}
    if kind == "product":
        result.update(responsibilities=current["responsibilities"], subject=subject)
        if state["plan"] and subject not in current["choices"]:
            result["next_action"] = "The saved plan's subject is outside the current remit. Check the change with the PM."
        elif state["plan"] and current["stage"] in {"product", "area"} and subject != current["subject"]:
            result["next_action"] = ("The saved plan covers a different step. Review any pending wording with the PM. "
                                     "Discard it or defer it with consent, then finish that plan before starting the current step.")
        if current["remit_problem"]:
            result["remit_problem"] = current["remit_problem"]
    if kind in ("pm", "product"):
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
        if kind not in ("pm", "product") or gap not in result["gap_selectors"]:
            label = "PM" if kind == "pm" else kind
            raise ValueError(f"Choose a current {label} gap selector from {kind}-onboarding status")
        position = result["gap_selectors"].index(gap)
        return {"revision": state["revision"], "gap": state["gaps"][position]}
    if pending:
        return {"revision": state["revision"], "pending": result["pending"]}
    journey = onboarding_review.status(private)
    stage = "area" if kind == "product" and journey["stage"] == "area" else kind
    result["walkthrough"] = journey["walkthroughs"][stage]
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


def followup(private, prompt, company_scope, kind="company", *, subject=None):
    setup_words = {"company": COMPANY_SETUP, "pm": PM_SETUP, "product": PRODUCT_SETUP}[kind]
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
    if resuming and kind == "product" and state["plan"] and subject and setup["subject"] != subject:
        return None
    if resuming and kind == "product" and setup["phase"] == "review":
        return "Offer to reopen the pending product finding with product-onboarding status --pending."
    if resuming and kind == "pm" and setup["phase"] == "review":
        return ("Offer to reopen the pending PM draft. After the PM agrees, "
                "inspect it with pm.py pm-onboarding status --pending.")
    if resuming and setup["phase"] in {"plan", "gather", "review"}:
        return f"Resume {kind} setup at phase {setup['phase']}. {setup['next_action']} Read pm.py {kind}-onboarding status."
    words = re.findall(r"\w+", prompt.casefold())
    for index, gap in enumerate(state["gaps"], 1):
        if kind == "product":
            if not subject and resuming:
                subject = setup["subject"]
            if subject == gap["subject"] and cue_matches(gap["resume_when"], words, resuming):
                return ("Offer to revisit the scoped product question if relevant. With the PM's agreement, "
                        f"inspect product-onboarding status --gap {state['revision']}/{index}.")
            continue
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


def decision_kind(payload):
    """Identify one documented choice eligible for the separate recording workflow."""
    if not isinstance(payload, dict) or set(payload) != {"sources", "entries"}:
        return None
    sources, entries = payload["sources"], payload["entries"]
    if not isinstance(sources, list) or len(sources) != 1 or not isinstance(entries, list) or len(entries) != 1:
        return None
    entry = entries[0]
    if not isinstance(entry, dict) or entry.get("topic") != "decisions" or "decision" not in entry:
        return None
    kind = entry.get("scope")
    fields = {"scope", "topic", "source", "location", "quote", "decision", "record_decision"}
    if kind == "product":
        fields.update(("product", "product_area", "area_group"))
    if kind in ("company", "product") and entry.keys() <= fields:
        return kind


def decision_plan(private, kind, payload, remit, *, destination=None):
    """Recheck the approved round, exact destination and inspected excerpt on preview and under the write lock."""
    _, state = read(private, kind)
    if not state["approved"]:
        raise ValueError(f"Approve the {kind} source plan before reviewing a {kind} decision")
    if state["pending"]:
        raise ValueError(f"Accept or defer the pending {kind} finding before reviewing a decision")
    reference = capture.source_rows(payload["sources"])[0]["reference"]
    if not any(within_scope(scope, reference) for scope in state["plan"]["sources"]):
        raise ValueError(f"Decision source is outside the approved {kind} plan")
    approved_homes = [layout.COMPANY]
    if kind == "product":
        entry, approved_homes = product_intake.finding(private, state["plan"], payload["entries"][0])
        if entry.get("product_area") and not capture.record_path(private, layout.product(entry["product"])).is_file():
            raise ValueError("Review and accept the parent product brief before recording an area decision")
        payload = dict(payload, entries=[entry])
    plan = capture.route(payload, private, remit, single_excerpt=True, descriptive_intake=kind == "product")
    target = plan["entries"][0]["destination"]
    if target not in approved_homes or destination not in (None, target):
        raise ValueError("Use the reviewed decision's approved destination")
    if plan["source_checks"][0]["verification"] != "reviewed excerpt matched inspected text":
        raise ValueError(f"Supply inspected source text or a readable local source for this {kind} decision")
    if kind == "product":
        title = state["plan"].get("titles", {}).get(target)
        if not title and not entry.get("product_area"):
            title = entry["product"].replace("-", " ")
        if title:
            plan["brief_title"] = title
    return plan


def entries_in_product_round(private, entries):
    if not isinstance(entries, list):
        return False
    targets = [(entry.get("product"), entry.get("product_area")) for entry in entries
               if isinstance(entry, dict) and entry.get("scope") == "product"]
    if not targets:
        return False
    journey = onboarding_review.status(private)
    if journey["stage"] == "area" and any(area and f"product/{product}/area/{area}" == journey["product_scope"]["subject"]
                                          for product, area in targets):
        return True
    plan = read(private, "product")[1]["plan"]
    if not plan:
        return False
    product, area, parent, child = product_intake.places(plan)
    return ((child is not None and (product, area) in targets)
            or (parent in plan["destinations"] and (product, None) in targets))


def check_capture(private, destination, plan):
    """Keep ordinary writes from skipping an active company review."""
    if not destination.startswith("context/company/") or not active(private):
        return
    entries = [row for row in plan["entries"] if row["destination"] == destination]
    responses = any(row["record"] == destination for row in plan.get("responses", []))
    if entries and not responses and all("decision" in row for row in entries):
        return  # The owning workflow separately verifies each PM decision confirmation.
    raise ValueError("Review and accept this company finding with company-onboarding")


def product_capture_owns(private, destination):
    if not str(destination).startswith("context/products/"):
        return False
    identity = layout.area_identity(destination)
    if identity:
        journey = onboarding_review.status(private)
        if journey["stage"] == "area" and journey["product_scope"]["subject"] == f"product/{identity[0]}/area/{identity[1]}":
            return True
    plan = read(private, "product")[1]["plan"]
    if not plan:
        return False
    if identity:
        product, area, _, child = product_intake.places(plan)
        return child is not None and identity[:2] == (product, area)
    try:
        home = layout.entity(destination) / "overview.md"
    except ValueError:
        return False
    return home.as_posix() in plan["destinations"]


def validate_plan(plan, kind="company"):
    required = ("purpose", "sources")
    if kind in ("pm", "product"):
        required += ("destinations",)
    if kind == "product":
        required += ("subject",)
    capture.fields(plan, required, ("titles",) if kind == "product" else ())
    if kind == "product":
        product_intake.places(plan)
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


def validate_gap(gap, kind="company"):
    required = (*GAP_FIELDS, "subject", "destination") if kind == "product" else GAP_FIELDS
    capture.fields(gap, required, ("basis",))
    if kind == "product":
        product_intake.places({"subject": gap["subject"], "destinations": [gap["destination"]]})
    if "basis" in gap:
        capture.fields(gap["basis"], ("reference", "date", "location", "quote"))
        for field, value in gap["basis"].items():
            capture.line(value, field)
    for field in GAP_FIELDS:
        capture.line(gap[field], field)


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
    scopes = ("pm", "stakeholder") if kind == "pm" else (kind,)
    if not isinstance(entry, dict) or entry.get("scope") not in scopes or entry.get("source") != 1:
        raise ValueError(f"Supply one sourced {kind} finding for this review")
    if kind == "pm" and entry.get("scope") == "pm" and entry.get("topic") == "stakeholders":
        raise ValueError("Review relationships in the separate stakeholder map")
    if kind in ("pm", "product") and entry.keys() & {"rule", "term", "record_decision", "risk", "supersedes"}:
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
        approved_homes = [expected]
    if kind == "product":
        entry, approved_homes = product_intake.finding(private, state["plan"], entry)
    plan = routed(private, sources[0], entry, descriptive_intake=kind in ("pm", "product"))
    row = plan["entries"][0]
    if kind in ("pm", "product") and row["destination"] not in approved_homes:
        raise ValueError("Review the destination with the PM and approve a revised plan before filing there")
    if (kind == "product" and "product_area" in entry and "lead" in entry
            and row["destination"] == layout.product(entry["product"])):
        raise ValueError("Review the area answer on its own before changing a product-wide section lead")
    if kind == "company" and (not row["destination"] or not row["destination"].startswith("context/company/")):
        raise ValueError("Choose the company overview or a qualifying company supporting record")
    path = capture.record_path(private, row["destination"])
    verification = plan["source_checks"][0]["verification"]
    if not restoring and verification != "reviewed excerpt matched inspected text":
        raise ValueError("Supply inspected source text or a readable local source for the reviewed finding")
    pending = {"entry": entry, "source": source, "source_scope": scope, "destination": row["destination"],
               "section": row["section"], "previous": fingerprint(path), "verification": verification}
    if kind == "product" and "product_area" in entry:
        parent = layout.product(entry["product"])
        if not capture.record_path(private, parent).is_file():
            pending["creates_parent"] = parent
    if "local_source" in plan["source_checks"][0]:
        pending["local_source"] = plan["source_checks"][0]["local_source"]
    if plan.get("risk_preview"):
        pending["risk_preview"] = plan["risk_preview"]
    return pending, plan


def accept(root, private, state, owner, lint, kind="company", *, publish=None, draft_token=None):
    if publish is None:
        publish = storage.replace_text
    item = state["pending"]
    if item is None:
        raise ValueError(f"Preview a {kind} finding before accepting it")
    source = item["source"]
    entry = item["entry"]
    if item.get("local_source") is not None:
        text, locator = capture.source_evidence.capture_material(private, source, item["local_source"])
        source = {**source, "text": text, "ingestion": {"source_id": locator["source_id"], "offset": locator["offset"]}}
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
        recorded = entry
        if kind == "product" and layout.brief_kind(item["destination"]) == "product-area-context":
            recorded = {key: value for key, value in entry.items() if key != "product_area"}
        if saved and capture.contains_capture(saved, path, recorded, item["section"], [source], private):
            return False  # The official record was saved before the checkpoint write.
        raise ValueError("The target changed since review. Preview the finding again")
    if current.get("creates_parent") and current["creates_parent"] != item.get("creates_parent"):
        raise ValueError("The parent product brief changed. Preview the finding again")
    if current.get("risk_preview") != item.get("risk_preview"):
        raise ValueError("The evidence risk changed. Preview the finding again")
    plan["source_checks"][0]["verification"] = item["verification"]
    descriptive = kind in ("pm", "product")
    parent = None
    if kind == "product" and current.get("creates_parent"):
        parent = private / current["creates_parent"]
        title = state["plan"].get("titles", {}).get(current["creates_parent"])
        scaffold = product_intake.scaffold(root, private, current["creates_parent"], lint, title, publish=publish, draft_token=draft_token)

    if descriptive:
        lint = partial(lint, destination_only=True)
    try:
        if kind == "product":
            title = state["plan"].get("titles", {}).get(item["destination"])
            if not title and item["destination"] == layout.product(entry["product"]):
                title = entry["product"].replace("-", " ")
            return capture.apply(root, item["destination"], plan, owner, lint, descriptive_intake=True, title=title, publish=publish, draft_token=draft_token)
        else:
            return capture.apply(root, item["destination"], plan, owner, lint, descriptive_intake=descriptive, publish=publish, draft_token=draft_token)
    except (ValueError, OSError):
        # A failed first area write must not leave an unused shell. Never remove an edited parent.
        if parent and scaffold and not path.exists() and parent.is_file() and parent.read_bytes() == scaffold.encode():
            parent.unlink()
        raise


def change(root, operation, payload, owner, lint, kind="company"):
    private = storage.private_root(root)
    with storage.writer_lock(private):
        original, state = read(private, kind)
        if (not isinstance(payload, dict) or type(payload.get("revision")) is not int
                or payload["revision"] != state["revision"]):
            raise ValueError(f"The review revision is missing or stale. Read {kind}-onboarding status")
        storage.require_visible(private, checkpoint(kind))
        data = {key: value for key, value in payload.items() if key != "revision"}
        assessments = None
        accept_finding = accept
        if operation in {"accept", "resolve"} and storage.selected_workspace(root) is not None:
            from oryx.workflows.capture_review import review_accept
            accept_finding = partial(review_accept, original=original, operation=operation, question=data.get("question"))
        if operation == "plan":
            validate_plan(data, kind)
            if kind == "product":
                product_intake.check_plan(private, data)
            if state["pending"]:
                raise ValueError("Accept or defer the pending finding before changing the source plan")
            state.update(plan=data, approved=False)
        elif operation in {"approve", "finish", "accept"}:
            capture.fields(data, ())
            if operation == "approve":
                if state["plan"] is None or state["approved"]:
                    raise ValueError("Present the proposed plan before approving it")
                if kind == "product":
                    product_intake.check_plan(private, state["plan"])
                state["approved"] = True
            elif operation == "accept":
                accept_finding(root, private, state, owner, lint, kind)
                state["pending"] = None
            else:
                if state["pending"]:
                    raise ValueError("Accept or defer the pending finding before finishing")
                state.update(plan=None, approved=False)
        elif operation == "discard" and kind in ("pm", "product"):
            capture.fields(data, ())
            if state["pending"] is None:
                raise ValueError("There is no pending finding to discard")
            state["pending"] = None
        elif operation == "propose":
            state["pending"], plan = prepare(private, state, data, kind=kind)
            assessments = plan["ingestion_reviews"]
        elif operation in {"defer", "gap"}:
            if kind == "product":
                capture.fields(data, (*GAP_FIELDS, "destination"))
                if not state["approved"] or data["destination"] not in state["plan"]["destinations"]:
                    raise ValueError("Review the product question and its destination in an approved plan")
                data["subject"] = state["plan"]["subject"]
                if operation == "defer" and state["pending"] and data["destination"] != state["pending"]["destination"]:
                    raise ValueError("Defer this question in the pending finding's destination")
                if operation == "gap":
                    _, area, parent, _ = product_intake.check_plan(private, state["plan"])
                    if area and data["destination"] == parent:
                        raise ValueError("Keep a new area question with its own brief")
            validate_gap(data, kind)
            existing = next((gap for gap in state["gaps"] if gap["question"] == data["question"]
                             and gap.get("destination") == data.get("destination")
                             and gap.get("subject") == data.get("subject")), {})
            if "basis" in existing:
                data["basis"] = existing["basis"]
            if operation == "defer":
                if state["pending"] is None:
                    raise ValueError("There is no pending finding to defer")
                item = state["pending"]
                data["basis"] = {**{k: item["source"][k] for k in ("reference", "date")},
                                 **{k: item["entry"][k] for k in ("location", "quote")}}
                state["pending"] = None
            state["gaps"] = [gap for gap in state["gaps"] if gap is not existing] + [data]
        elif operation == "resolve":
            capture.fields(data, ("question",))
            destination = (state["pending"] or {}).get("destination")
            gaps = [gap for gap in state["gaps"] if gap["question"] != data["question"] or
                    (kind == "product" and (gap["destination"] != destination or
                                            gap["subject"] != (state["plan"] or {}).get("subject")))]
            if len(gaps) == len(state["gaps"]):
                raise ValueError("Choose an existing gap to resolve")
            if not state["pending"] or state["pending"]["entry"].get("answers") != data["question"]:
                raise ValueError("Review a sourced answer to the exact open question before resolving it")
            accept_finding(root, private, state, owner, lint, kind)
            state["pending"] = None
            state["gaps"] = gaps
        else:
            raise ValueError(f"Unknown {kind} onboarding operation")
        state["revision"] += 1
        storage.replace_text(private / checkpoint(kind), original, json.dumps(state, indent=2, ensure_ascii=False) + "\n")
        result = view(private, state, kind, show_pending=operation == "propose")
        if assessments is not None:
            result["ingestion_reviews"] = assessments
        return result
