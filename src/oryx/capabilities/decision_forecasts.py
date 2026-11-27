"""Opt-in, revision-bound forecasts about binary events attached to reviewed decisions."""

from datetime import date
from decimal import Decimal
import json
from pathlib import Path
import re
import sys

import decision_authority
import evidence_reviews
import initiative_events
import initiative_store
import layout
import records
import storage
import workspace


HOME = Path("workspace/forecasts")
ID = re.compile(r"forecast-[a-f0-9]{24}")
DIGEST = re.compile(r"[a-f0-9]{64}")
ORIGINAL = ("decision", "event", "criterion", "made_on", "resolve_on", "probability")
fingerprint = decision_authority.fingerprint


def today():
    return date.today().isoformat()


def fields(value, names):
    if not isinstance(value, dict) or set(value) != set(names):
        raise ValueError("Expected fields: " + ", ".join(names))


def day(value):
    if not initiative_events.iso_date(value):
        raise ValueError("Choose an ISO calendar date (YYYY-MM-DD)")
    return value


def probability(value):
    if type(value) not in {int, float} or not 0 <= value <= 100:
        raise ValueError("Enter the PM's stated event probability as a percentage from 0 to 100")


def forecast_id(data):
    normalized = " ".join(data["event"].casefold().split())
    return "forecast-" + fingerprint([data["decision"], normalized, data["resolve_on"]])[:24]


def target_for(private, identifier):
    if not isinstance(identifier, str) or not ID.fullmatch(identifier):
        raise ValueError("Choose an existing forecast ID")
    path = private / layout.work_path(HOME, private) / (identifier + ".json")
    if path.resolve() != path or (path.exists() and not path.is_file()):
        raise ValueError("Use regular files in the private forecast directory")
    return path


def evidence_path(private, reference):
    if not isinstance(reference, str):
        raise ValueError("Supply an inspected evidence source")
    if initiative_events.is_url(reference):
        return None
    name = Path(reference)
    if (name.as_posix() != reference or not name.parts or layout.work_parts(name)[0] not in {"context", "workspace"}
            or name.suffix.lower() not in {".md", ".txt"} or "\\" in reference
            or any(part.startswith(".") or part == "secrets" for part in name.parts)):
        raise ValueError("Evidence needs an HTTPS source or a regular private Markdown or text file")
    return private / layout.work_path(name, private)


def validate_evidence(private, evidence):
    fields(evidence, ("source", "quote", "observed_on", "file_digest"))
    path = evidence_path(private, evidence["source"])
    if not initiative_events.text(evidence["quote"]):
        raise ValueError("Cite the observed evidence in the original wording")
    day(evidence["observed_on"])
    digest = evidence["file_digest"]
    if (path is None and digest is not None) or (path is not None and not
            (isinstance(digest, str) and DIGEST.fullmatch(digest))):
        raise ValueError("Evidence has an invalid archived file digest")


def inspect_evidence(private, evidence):
    fields(evidence, ("source", "quote", "observed_on"))
    path = evidence_path(private, evidence["source"])
    result = {**evidence, "file_digest": None}
    if path is not None:
        if path.resolve() != path or not path.is_file():
            raise ValueError("The cited evidence is missing or redirected")
        storage.require_visible(private, path.relative_to(private))
        material = path.read_bytes()
        if not isinstance(evidence["quote"], str) or evidence["quote"] not in material.decode("utf-8"):
            raise ValueError("The cited quote differs from the local source")
        result["file_digest"] = initiative_store.digest(material)
    validate_evidence(private, result)
    return result


def validate_record(private, data):
    fields(data, ("version", "id", *ORIGINAL, "authority", "revisions", "resolution"))
    if type(data["version"]) is not int or data["version"] != 1:
        raise ValueError("Unsupported forecast format")
    if not all(initiative_events.text(data[key]) for key in ("event", "criterion")):
        raise ValueError("Describe the future event and the observable test for its outcome")
    probability(data["probability"])
    made, due = day(data["made_on"]), day(data["resolve_on"])
    if made > today() or due <= made:
        raise ValueError("The original forecast needs its stated date and a later resolution date")
    if data["id"] != forecast_id(data):
        raise ValueError("Forecast identity differs from the decision, event or resolution window")
    ref, authority = data["decision"], data["authority"]
    base_fields = ("product", "areas", "initiative", "record", "artifact_id", "on", "entry", "sources", "owner_revision")
    optional = ("advisories",) if isinstance(authority, dict) and "advisories" in authority else ()
    fields(authority, (*base_fields, *optional))
    if (not isinstance(authority["owner_revision"], str) or not DIGEST.fullmatch(authority["owner_revision"])
            or day(authority["on"]) > made or not initiative_events.text(authority["artifact_id"])
            or not isinstance(authority["areas"], list) or not isinstance(authority["sources"], list)
            or not authority["sources"] or not isinstance(ref, dict)
            or any(not isinstance(area, str) or not initiative_events.AREA_SUBJECT.fullmatch(area)
                   or area.split("/")[1] != authority["product"] for area in authority["areas"])):
        raise ValueError("Invalid archived decision scope, evidence or date")
    if ref.get("kind") == "registered":
        if optional:
            raise ValueError("Read approved decision evidence from its verified entry")
        fields(ref, ("kind", "product", "initiative", "ordinal", "digest"))
        entry = authority["entry"]
        if (type(ref["ordinal"]) is not int or ref["ordinal"] < 1 or not isinstance(entry, dict)
                or not initiative_events.VALIDATORS["initiative ID"](ref["initiative"])
                or entry.get("type") != "decision" or ref["initiative"] != entry.get("initiative")
                or authority["initiative"] != ref["initiative"] or authority["product"] != ref["product"]
                or authority["on"] != entry.get("on") or authority["sources"] != [entry.get("source")]
                or authority["record"] != layout.initiative_register(ref["product"])
                or ref["initiative"].partition("/")[0] != authority["artifact_id"]
                or ref["digest"] != fingerprint(entry)):
            raise ValueError("Invalid archived approved decision identity")
        initiative_events.validate_event(entry, approved=True)
    elif ref.get("kind") == "context":
        fields(ref, ("kind", "record", "artifact_id", "digest"))
        entry = authority["entry"]
        if (not isinstance(ref["record"], str) or layout.brief_kind(ref["record"]) not in records.CONTEXT_KINDS
                or not isinstance(entry, list) or len(entry) != 5 or not all(isinstance(cell, str) for cell in entry)
                or entry[2].rpartition(", ")[2] != authority["on"]):
            raise ValueError("Invalid archived closed decision row")
        for source in authority["sources"]:
            if (not isinstance(source, dict) or set(source) - {"files", "coverage"} != set(records.SOURCE_COLUMNS)
                    or source.get("coverage", "unrecorded") not in ("unrecorded", "read", "partial")
                    or day(source["Source date"]) > made):
                raise ValueError("A forecast needs decision evidence dated on or before its original estimate")
        advisories = authority.get("advisories", [])
        if not isinstance(advisories, list):
            raise ValueError("Expected a list of decision advisories")
        for item in advisories:
            fields(item, ("id", "record", "state", "reason"))
            if (not isinstance(item["id"], str) or not re.fullmatch(r"risk-[a-f0-9]{20}", item["id"])
                    or not all(initiative_events.text(item[key]) for key in ("reason", "record"))
                    or not isinstance(item["state"], str) or item["state"] not in evidence_reviews.OPEN):
                raise ValueError("Invalid archived evidence review")
        if (ref["digest"] != decision_authority.context_digest(authority)
                or ref["record"] != authority["record"]
                or ref["artifact_id"] != authority["artifact_id"]):
            raise ValueError("Invalid archived context decision identity")
    else:
        raise ValueError("Unknown decision authority")
    previous = made
    if not isinstance(data["revisions"], list):
        raise ValueError("Forecast revisions must be an ordered list")
    for revision in data["revisions"]:
        fields(revision, ("on", "probability", "evidence"))
        probability(revision["probability"])
        validate_evidence(private, revision["evidence"])
        when = day(revision["on"])
        if (when < previous or when >= due or when > today()
                or not made <= revision["evidence"]["observed_on"] <= when):
            raise ValueError("A probability revision needs dated evidence before the resolution date")
        previous = when
    resolution = data["resolution"]
    if resolution is not None:
        fields(resolution, ("on", "outcome", "evidence", "score"))
        if type(resolution["outcome"]) is not bool:
            raise ValueError("Resolve only a known binary outcome using true or false")
        when = day(resolution["on"])
        validate_evidence(private, resolution["evidence"])
        if not due <= resolution["evidence"]["observed_on"] <= when <= today():
            raise ValueError("Resolve using evidence observed on or after the resolution date")
        expected = score(data["probability"], resolution["outcome"])
        if type(resolution["score"]) not in {int, float} or resolution["score"] != expected:
            raise ValueError("Score the immutable original probability against the observed outcome")


def score(percent, result):
    return float((Decimal(str(percent)) / 100 - int(result)) ** 2)


def read(private, identifier):
    target = target_for(private, identifier)
    if not target.exists():
        return None, None
    storage.require_visible(private, target.relative_to(private))
    original = target.read_text(encoding="utf-8")
    envelope = storage.json_input(original)
    fields(envelope, ("revision", "forecast"))
    value = envelope["forecast"]
    if fingerprint(value) != envelope["revision"]:
        raise ValueError("Forecast differs from its saved revision. Review private Git history.")
    validate_record(private, value)
    if identifier != value["id"]:
        raise ValueError("The filename must match its forecast ID")
    return original, value


def list_records(private):
    folder = private / layout.work_path(HOME, private)
    if folder.resolve() != folder or (folder.exists() and not folder.is_dir()):
        raise ValueError("Use a regular private forecast directory")
    if not folder.exists():
        return []
    result = []
    for path in sorted(folder.iterdir()):
        if path.suffix != ".json" or not ID.fullmatch(path.stem):
            raise ValueError(f"Unexpected forecast record: {path.name}")
        result.append(read(private, path.stem)[1])
    return result


def check_workspace(private):
    try:
        list_records(private)
    except (OSError, ValueError) as exc:
        return [f"{private.name}/{HOME}: {exc}"]
    return []


def request_for(data):
    res = data["resolution"]
    if res is not None:
        operation = "resolve"
        change = {key: value for key, value in res.items() if key != "score"}
    elif data["revisions"]:
        operation, change = "revise", data["revisions"][-1]
    else:
        return {"operation": "create", **{key: data[key] for key in ORIGINAL}}
    evidence = {key: value for key, value in change["evidence"].items() if key != "file_digest"}
    return {"operation": operation, "id": data["id"], **change, "evidence": evidence}


def history(data):
    state = {**data, "revisions": [], "resolution": None}
    yield state
    for revision in data["revisions"]:
        state = {**state, "revisions": [*state["revisions"], revision]}
        yield state
    if data["resolution"] is not None:
        yield data


def receipt(previous, data):
    return {"base": fingerprint(previous) if previous else None, "revision": fingerprint(data), "forecast": data}


def preview(root, request):
    private = storage.private_root(root)
    if not isinstance(request, dict) or request.get("operation") not in ("create", "revise", "resolve"):
        raise ValueError("Choose create, revise or resolve")
    action = request["operation"]
    if action == "create":
        fields(request, ("operation", *ORIGINAL))
        if not initiative_events.text(request["event"]):
            raise ValueError("Describe the future event in the PM's words")
        identifier = forecast_id(request)
    else:
        fields(request, ("operation", "id", "on", "evidence", "probability" if action == "revise" else "outcome"))
        identifier = request["id"]
    _, existing = read(private, identifier)
    previous = None
    if existing:
        for state in history(existing):
            if initiative_store.canonical(request_for(state)) == initiative_store.canonical(request):
                return receipt(previous, state)
            previous = state
    if action == "create":
        if existing:
            raise ValueError("This event and resolution date already have a forecast. Preview a separate revision.")
        authority = decision_authority.lookup(root, request["decision"])
        data = {"version": 1, "id": identifier, **{key: request[key] for key in ORIGINAL}, "authority": authority,
                "revisions": [], "resolution": None}
        if day(data["resolve_on"]) <= today():
            raise ValueError("Choose a future resolution date for a new forecast")
    else:
        if not existing or existing["resolution"] is not None:
            raise ValueError("Choose an existing unresolved forecast")
        change = {"on": request["on"], "evidence": inspect_evidence(private, request["evidence"])}
        if action == "revise":
            if today() >= existing["resolve_on"]:
                raise ValueError("The resolution date has arrived. Preserve the original and earlier probabilities.")
            change["probability"] = request["probability"]
            data = {**existing, "revisions": [*existing["revisions"], change]}
        else:
            if type(request["outcome"]) is not bool:
                raise ValueError("Resolve only a known binary outcome using true or false")
            change.update(outcome=request["outcome"], score=score(existing["probability"], request["outcome"]))
            data = {**existing, "resolution": change}
    validate_record(private, data)
    return receipt(existing, data)


def apply(root, proposal):
    fields(proposal, ("base", "revision", "forecast"))
    private = storage.private_root(root)
    with storage.writer_lock(private):
        data = proposal["forecast"]
        validate_record(private, data)
        expected = preview(root, request_for(data))
        if initiative_store.canonical(expected) != initiative_store.canonical(proposal):
            raise ValueError("The forecast or its source changed. Review a fresh preview.")
        target = target_for(private, data["id"])
        storage.require_visible(private, target.relative_to(private))
        original, current = read(private, data["id"])
        if current and any(fingerprint(state) == proposal["revision"] for state in history(current)):
            return {"id": data["id"], "revision": proposal["revision"]}
        if (fingerprint(current) if current else None) != proposal["base"]:
            raise ValueError("Forecast changed during review. Preview again.")
        saved = {"revision": proposal["revision"], "forecast": data}
        storage.replace_text(target, original, json.dumps(saved, ensure_ascii=False, indent=2) + "\n")
    return {"id": data["id"], "revision": proposal["revision"]}


def add_commands(subparsers):
    group = subparsers.add_parser("forecast", help="Review and record a forecast tied to an accepted decision")
    operations = group.add_subparsers(dest="operation", required=True)
    decisions = operations.add_parser("decisions", help="Find verified, scoped decision references")
    source = decisions.add_mutually_exclusive_group(required=True)
    source.add_argument("--product")
    source.add_argument("--context")
    decisions.add_argument("--initiative", help="Filter approved decisions by their registered initiative ID")
    operations.add_parser("preview", help="Review a new forecast, probability revision or binary resolution from stdin")
    operations.add_parser("apply", help="Save the exact forecast preview confirmed by the PM")
    listing = operations.add_parser("list", help="Read private forecasts and their dated history")
    listing.add_argument("--product")


def run(root, args, prepare_write):
    workspace.repo(root, "workspace")
    if args.operation == "apply":
        proposal = storage.json_input(sys.stdin.read())
        prepare_write(root)
        print(json.dumps(apply(root, proposal), ensure_ascii=False, indent=2))
        return
    workspace.settings(root)
    private = storage.private_root(root)
    if args.operation == "decisions":
        if args.context and args.initiative:
            raise ValueError("Use --initiative with --product")
        result = (decision_authority.context(private, args.context) if args.context else
                  decision_authority.registered(root, args.product, args.initiative))
    elif args.operation == "list":
        result = [data for data in list_records(private)
                  if args.product is None or data["authority"]["product"] == args.product]
    else:
        result = preview(root, storage.json_input(sys.stdin.read()))
    print(json.dumps(result, ensure_ascii=False, indent=2))
