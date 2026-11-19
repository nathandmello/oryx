"""Guide a PM conversation and keep an explicitly reviewed work checkpoint."""

from datetime import date
from hashlib import sha256
import json
from pathlib import Path
import re
import sys

import layout
import records
import storage
import upgrades
import workspace


GUIDE = "playbook/conversation.md"
MAX_DEFERRALS = 32
# Order matters when two findings change the same next decision.
WORKFLOWS = (
    "context-health", "launch-readiness", "outcome-review", "roadmap-selection",
    "discovery", "initiative-definition", "decision-coaching", "decision-reflection",
)
ACKNOWLEDGMENT = re.compile(
    r"(?:thank(?:s| you)(?: so much| very much)?|got it|makes sense|understood|noted|ok(?:ay)?|"
    r"great|sounds good|will do|that's helpful)(?:[.! ,]+(?:thank(?:s| you)|great|got it))*[.!, ]*", re.I
)
QUIET = re.compile(r"^(?:please\s+)?(?:quiet(?: mode)?|shut up|just capture)(?:\b|$)", re.I)
THOUGHT_PARTNER = re.compile(r"^(?:please\s+)?(?:exit quiet mode|resume coaching|thought-partner mode)\b", re.I)
DIRECT = re.compile(
    r"^(?:please\s+)?(?:(?:can|could|would) you\s+(?:please\s+)?)?"
    r"(?:summari[sz]e|show|list|look up|find|copy|capture|format|fix|translate|spell|read|"
    r"send|email|give|write|draft|open|tell|explain|what|which|who|when|where|how)\b", re.I
)
ROUTINE = re.compile(
    r"^(?:please\s+)?(?:(?:can|could|would) you\s+(?:please\s+)?)?"
    r"(?:summari[sz]e|show|list|look up|copy|capture|format|fix|translate|spell|read|"
    r"what (?:is|are|was|were|did)|who|where|when)\b", re.I
)
DISCUSSION_FOLLOW_UP = re.compile(
    r"^(?:what do we know about|how does (?:this|that)|why does (?:this|that)|"
    r"what would change|would (?:this|that)|does (?:this|that))\b", re.I
)
CONSEQUENTIAL = re.compile(
    r"\b(?:weigh|choose|decide|reopen|prioritiz[ei]|trade[- ]?off|go\s*[/ -]\s*no[- ]?go|"
    r"commit(?:ting|ment)?|approve|roadmap|stop rollout|timebox|launch decision|customer update|should we)\b", re.I
)
MODE = re.compile(r"^[^\r\n|]+$")
REVISION = re.compile(r"[a-f0-9]{64}")
BLOCK = re.compile(r"(?m)^<!-- pm:conversation (.*) -->\r?$")
UPDATES = {
    "state": "State", "mode": "Mode", "last_checkpoint": "Last checkpoint",
    "next_action": "Next action", "waiting_on": "Waiting on", "resume_when": "Resume when",
}


def acknowledgement(prompt):
    return bool(ACKNOWLEDGMENT.fullmatch(prompt.strip()))


def requested_mode(prompt):
    if QUIET.match(prompt.strip()):
        return "quiet"
    if THOUGHT_PARTNER.match(prompt.strip()):
        return "thought-partner"
    return None


def continues_work(prompt):
    """Keep an active pointer after a reply without injecting prior private evidence."""
    prompt = prompt.strip()
    return (acknowledgement(prompt) or bool(DISCUSSION_FOLLOW_UP.match(prompt))
            or bool(prompt and "?" not in prompt and not DIRECT.match(prompt)))


def fingerprint(text):
    return sha256(text.encode("utf-8")).hexdigest()


def scope_key(scope):
    if not isinstance(scope, dict):
        raise ValueError("Choose a known company, product, area, or initiative scope")
    if (scope.get("company") is True and set(scope) <= {"company", "product", "area", "initiative"}
            and all(scope.get(key) is None for key in ("product", "area", "initiative"))):
        return ("company",)
    if (set(scope) <= {"product", "area", "initiative"} and isinstance(scope.get("product"), str)
            and layout.SLUG.fullmatch(scope["product"])
            and all(value is None or isinstance(value, str) and layout.SLUG.fullmatch(value)
                    for value in scope.values())):
        return tuple(scope.get(key) for key in ("product", "area", "initiative"))
    raise ValueError("Choose a known company, product, area, or initiative scope")


def offer_key(value):
    workflow, source, revision = (value.get(key) for key in ("workflow", "source", "revision"))
    if (workflow not in WORKFLOWS or not isinstance(source, str) or not MODE.fullmatch(source)
            or len(source) > 400 or "-->" in source
            or not isinstance(revision, str) or not REVISION.fullmatch(revision)):
        raise ValueError("Choose an available workflow, evidence source, and evidence revision")
    return workflow, scope_key(value.get("scope")), source


def valid_deferral(value):
    if not isinstance(value, dict) or set(value) != {"workflow", "scope", "source", "revision", "review_on"}:
        raise ValueError("A deferral needs workflow, scope, source, revision, and review_on")
    offer_key(value)
    review_on = value["review_on"]
    if review_on is not None and (not isinstance(review_on, str)
                                 or date.fromisoformat(review_on).isoformat() != review_on):
        raise ValueError("Use an ISO review date or null to wait for changed evidence")
    return value


def select_offer(candidates, scope, *, deferrals=(), quiet=False, on=None):
    """Choose one in-scope, available workflow with current evidence."""
    if quiet or not scope:
        return None
    wanted = scope_key(scope)
    through = (on or date.today()).isoformat()
    held = {offer_key(row): row for row in map(valid_deferral, deferrals)
            if row["review_on"] is None or row["review_on"] > through}
    eligible = []
    for candidate in candidates:
        if candidate.get("workflow") not in WORKFLOWS:
            continue
        key = offer_key(candidate)
        if key[1] != wanted or not all(candidate.get(field) for field in ("reason", "next_action")):
            continue
        previous = held.get(key)
        if previous and previous["revision"] == candidate["revision"]:
            continue
        eligible.append(candidate)
    return min(eligible, key=lambda row: WORKFLOWS.index(row["workflow"]), default=None)


def context_offer(prompt, result, deferrals, quiet):
    """Offer an existing evidence check for a consequential, sourced finding."""
    if quiet or ROUTINE.match(prompt.strip()) or not CONSEQUENTIAL.search(prompt):
        return None
    candidates = []
    for conflict in result.get("conflicts", []):
        entries = conflict["entries"]
        sources = sorted({row["record"] for row in entries})
        locator = " and ".join(sources)
        if locator and len(locator) <= 400:
            candidates.append({
                "workflow": "context-health", "scope": result["scope"], "source": locator,
                "revision": fingerprint(json.dumps(entries, ensure_ascii=False, sort_keys=True)),
                "reason": "Scoped decisions give different next steps.",
                "next_action": "Compare the decision sources and verify which authority applies.",
            })
    for warning in result["warnings"]:
        match = re.fullmatch(r"Review overdue for (.+)\. Confirm current authority before relying on it\.", warning)
        if not match:
            continue
        source = match[1]
        evidence = [row for row in result["entries"] if row["record"] == source]
        if evidence:
            candidates.append({
                "workflow": "context-health", "scope": result["scope"], "source": source,
                "revision": fingerprint(json.dumps(evidence, ensure_ascii=False, sort_keys=True)),
                "reason": warning, "next_action": "Verify the applicable claims and their current source.",
            })
    return select_offer(candidates, result["scope"], deferrals=deferrals)


def record_path(private, name):
    if not isinstance(name, str):
        raise ValueError("Choose an existing workspace Markdown work record")
    relative = Path(name)
    target = private / relative
    if (relative.is_absolute() or relative.as_posix() != name
            or any(part.startswith(".") or part in {"sources", "secrets"} for part in relative.parts)
            or not layout.valid_work(relative) or target.resolve() != target
            or not target.is_file() or name in upgrades.source_paths(private)):
        raise ValueError("Choose an existing workspace Markdown work record")
    return target


def details(text):
    identifier, problems = records.state_errors(text)
    if problems:
        raise ValueError("Resolve the work-state fields before using this checkpoint: " + ", ".join(problems))
    state = records.work_state(text)[0]
    block = records.section(text, "Work state") or ""
    saved = BLOCK.findall(block)
    if block.count("<!-- pm:conversation ") != len(saved) or len(saved) > 1:
        raise ValueError("Resolve the invalid conversation checkpoint metadata")
    deferrals = storage.json_input(saved[0]) if saved else []
    if not isinstance(deferrals, list) or len(deferrals) > MAX_DEFERRALS:
        raise ValueError("Resolve the invalid conversation deferrals")
    if len({offer_key(valid_deferral(row)) for row in deferrals}) != len(deferrals):
        raise ValueError("Keep one current deferral for each scoped workflow and evidence source")
    return {"id": identifier, "work_state": state, "deferrals": deferrals}


def read_checkpoint(private, record):
    target = record_path(private, record)
    return {"record": record, **details(target.read_bytes().decode("utf-8"))}


def review_protection(root, record, text):
    kind = layout.governed_kind(record)
    if kind not in {*layout.INITIATIVE_BRIEFS, "prioritization"}:
        return
    import initiative_store

    _, payload, _ = initiative_store.read(root, Path(record).parts[2])
    for event in payload["events"]:
        reference = event.get("references", {})
        if (reference.get("path") == record and event.get("action") != "start-discovery"
                and reference.get("sha256") == fingerprint(text)):
            raise ValueError("The signed review binds this file. Use an editable owning work record.")


def updated_text(text, changes):
    if (not isinstance(changes, dict) or not changes
            or set(changes) - (set(UPDATES) | {"deferral", "clear_deferral"})):
        raise ValueError("Provide work-state fields or a deferral change")
    if "deferral" in changes and "clear_deferral" in changes:
        raise ValueError("Choose to save or clear one workflow deferral")
    state = details(text)
    section = next((item for item in records.section_blocks(text) if item[0] == "Work state"), None)
    if section is None:
        raise ValueError("Resolve the Work state heading before saving a checkpoint")
    _, _, start, end = section
    body = text[start:end]
    for key, field in UPDATES.items():
        if key not in changes:
            continue
        value = changes[key]
        if not isinstance(value, str) or not MODE.fullmatch(value) or value != value.strip():
            raise ValueError(f"{field} needs a single concrete value without a vertical bar")
        pattern = rf"(?m)^([ \t]*\|[ \t]*{re.escape(field)}[ \t]*\|)[^\r\n|]*\|[ \t]*(?=\r?$)"
        body, count = re.subn(pattern, lambda match: f"{match[1]} {value} |", body)
        if count != 1:
            raise ValueError(f"Resolve the {field} row before saving a checkpoint")

    if "deferral" in changes or "clear_deferral" in changes:
        saved = changes.get("deferral")
        workflow = (valid_deferral(saved)["workflow"] if "deferral" in changes
                    else changes["clear_deferral"])
        if workflow not in WORKFLOWS:
            raise ValueError("Choose an available workflow")
        if saved:
            deferrals = [row for row in state["deferrals"] if offer_key(row) != offer_key(saved)] + [saved]
        else:
            deferrals = [row for row in state["deferrals"] if row["workflow"] != workflow]
        body = BLOCK.sub("", body)
        if deferrals:
            newline = "\r\n" if "\r\n" in body else "\n"
            data = json.dumps(deferrals, ensure_ascii=False, sort_keys=True).replace("--", "\\u002d\\u002d")
            body = body.rstrip("\r\n") + f"{newline}{newline}<!-- pm:conversation {data} -->{newline}{newline}"
    candidate = text[:start] + body + text[end:]
    return candidate, details(candidate)


def preview(root, private, record, changes):
    target = record_path(private, record)
    original = target.read_bytes().decode("utf-8")
    candidate, checkpoint = updated_text(original, changes)
    if original != candidate:
        review_protection(root, record, original)
    proposal = {
        "record": record, "base": fingerprint(original), "changes": changes,
        "checkpoint": checkpoint, "revision": fingerprint(candidate),
    }
    return proposal, target, original, candidate


def add_commands(commands):
    conversation = commands.add_parser("conversation", help="Inspect or review changes to a PM work checkpoint")
    conversation.set_defaults(hub_action=run)
    domain = conversation.add_subparsers(dest="conversation_domain", required=True)
    checkpoint = domain.add_parser("checkpoint", help="Keep the checkpoint in the owning work record")
    operations = checkpoint.add_subparsers(dest="operation", required=True)
    operations.add_parser("show", help="Read the owning checkpoint").add_argument("record")
    operations.add_parser("preview", help="Review JSON work-state changes from stdin").add_argument("record")
    operations.add_parser("apply", help="Apply the reviewed JSON receipt from stdin").add_argument("record")


def run(root, args, prepare_write):
    private = workspace.repo(root, "workspace")
    workspace.settings(root)
    if args.operation == "show":
        result = read_checkpoint(private, args.record)
    else:
        payload = storage.json_input(sys.stdin.read())
        if args.operation == "preview":
            result, _, _, _ = preview(root, private, args.record, payload)
        else:
            if not isinstance(payload, dict) or "changes" not in payload:
                raise ValueError("Apply requires the reviewed checkpoint preview")
            prepare_write(root)
            with storage.writer_lock(private):
                result, target, original, candidate = preview(root, private, args.record, payload["changes"])
                if payload != result:
                    raise ValueError("The checkpoint preview is stale or modified. Review it again.")
                storage.require_visible(private, target.relative_to(private))
                if candidate != original:
                    storage.replace_text(target, original, candidate)
    print(json.dumps(result, ensure_ascii=False, indent=2))
