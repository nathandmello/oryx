"""Review one sourced claim at a time in a private, stable stakeholder profile."""

from datetime import date
from hashlib import sha256
import json
from pathlib import Path
import re
import sys
import unicodedata

import context_capture
import context_index
import layout
import storage
import source_evidence
import upgrades
import workspace


HOME = Path("context/stakeholders/profiles")
INDEX = HOME / ".identities.json"
STAMPS = Path(".state/stakeholder-identity-stamps.json")
TOPICS = ("role", "relationships", "goals", "concerns", "evidence", "communication", "history")
KINDS = ("observed", "reported", "hypothesis")
SUBJECT = re.compile(rf"product/{layout.SLUG.pattern}(?:/(?:area|initiative)/{layout.SLUG.pattern})?")
CLAIM_ID = re.compile(r"claim-[a-f0-9]{24}")
DIGEST = re.compile(r"[a-f0-9]{64}")
CLAIM_FIELDS = ("topic", "kind", "wording", "source", "excerpt", "scope", "subject", "observed_on", "attribution", "replaces")
CLAIM_OPTIONS = ("evidence", "review_by")
IDENTITY_FIELDS = ("id", "name", "role")
REVIEW_FIELDS = ("change", "base_revision", "destination", "duplicate", "review_id")


def fingerprint(value):
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def text(value, name, limit=1200):
    context_capture.line(value, name)
    if len(value) > limit or any(unicodedata.category(c) in {"Cc", "Cs"} for c in value):
        raise ValueError(f"Use a concise, single-line {name}")
    return value


def normalized(value):
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def slug(value):
    if len(layout.slug(value)) > 100:
        raise ValueError("Use a short stable profile ID")
    return value


def claim(data):
    context_capture.fields(data, CLAIM_FIELDS, CLAIM_OPTIONS)
    if isinstance(data["source"], str) and data["source"].startswith("ingestion:") and "evidence" not in data:
        raise ValueError("Retain the checked source evidence when reviewing an ingested claim")
    if "evidence" in data:
        import stakeholder_signals
        if not stakeholder_signals.valid_evidence(data["evidence"]):
            raise ValueError("Invalid checked source evidence")
    if "review_by" in data:
        day = text(data["review_by"], "review date")
        if date.fromisoformat(day).isoformat() != day:
            raise ValueError("Use a YYYY-MM-DD review date")
    if data["topic"] not in TOPICS or data["kind"] not in KINDS:
        raise ValueError("Choose a supported profile topic and an observed, reported, or PM hypothesis claim")
    for key in ("wording", "source", "excerpt", "scope", "attribution"):
        text(data[key], key)
    subject = text(data["subject"], "subject")
    if subject not in {"general", "unknown"} and not SUBJECT.fullmatch(subject):
        raise ValueError("Choose an explicit profile subject: general, unknown, or a qualified product, area, or initiative")
    if data["observed_on"] != "unknown":
        context_capture.iso_day(data["observed_on"], "Observation date")
    if data["replaces"] is not None and not (isinstance(data["replaces"], str) and CLAIM_ID.fullmatch(data["replaces"])):
        raise ValueError("Choose a current claim ID for a correction")
    if data["kind"] == "hypothesis" and data["attribution"] != "PM":
        raise ValueError("Record only an explicitly PM-attributed hypothesis")
    return data


def identity(data):
    result = {"id": slug(data["id"]), "name": text(data["name"], "name", 160), "role": text(data["role"], "role", 240)}
    aliases = data.get("aliases", [])
    if not isinstance(aliases, list) or len(aliases) > 32:
        raise ValueError("Use a short list of confirmed names for this person")
    names = set()
    for item in aliases:
        key = normalized(text(item, "alias", 160))
        if key in names or key == normalized(result["name"]):
            raise ValueError("Enter each confirmed alias once")
        names.add(key)
    if aliases:
        result["aliases"] = list(aliases)
    return result


def labels(person):
    return [person["id"], person["name"], person["role"], *person.get("aliases", [])]


def claim_details(data):
    return {key: data[key] for key in (*CLAIM_FIELDS, *CLAIM_OPTIONS) if key in data}


def path_for(private, identifier):
    path = private / HOME / (slug(identifier) + ".json")
    if path.resolve() != path or (path.exists() and not path.is_file()):
        raise ValueError("Use a regular file inside the private stakeholder profile directory")
    return path


def claim_id(identifier, data):
    return "claim-" + fingerprint([identifier, data])[:24]


def current_entries(entries):
    replaced = {row["replaces"] for row in entries}
    return [row for row in entries if row["id"] not in replaced]


def read(private, identifier):
    path = path_for(private, identifier)
    if not path.exists():
        return None, None
    name = path.relative_to(private).as_posix()
    if name in upgrades.source_paths(private):
        raise ValueError("Review the retained source at this location before using it as a stakeholder profile")
    storage.require_visible(private, name)
    return read_file(path, identifier)


def read_file(path, identifier):
    original = path.read_bytes()
    doc = storage.json_input(original)
    context_capture.fields(doc, (*IDENTITY_FIELDS, "format", "entries"), ("aliases", "current_role_from"))
    identity(doc)
    if (doc["id"] != identifier or type(doc["format"]) is not int or doc["format"] != 1
            or not isinstance(doc["entries"], list) or not doc["entries"]):
        raise ValueError(f"Invalid stakeholder profile at {HOME}/{identifier}.json")
    start = doc.get("current_role_from", 0)
    if type(start) is not int or not 0 <= start < len(doc["entries"]):
        raise ValueError("Invalid beginning of the current stakeholder role")
    seen, active, receipts = set(), set(), set()
    for row in doc["entries"]:
        context_capture.fields(row, (*CLAIM_FIELDS, "id", "review_id"), CLAIM_OPTIONS)
        data = claim(claim_details(row))
        receipt = row["review_id"]
        if (row["id"] != claim_id(identifier, data) or row["id"] in seen
                or not isinstance(receipt, str) or not DIGEST.fullmatch(receipt) or receipt in receipts):
            raise ValueError(f"Invalid claim or review receipt in {identifier}")
        if data["replaces"] is not None:
            if data["replaces"] not in active:
                raise ValueError(f"Correction in {identifier} must refer to one current earlier claim")
            active.remove(data["replaces"])
        seen.add(row["id"])
        active.add(row["id"])
        receipts.add(receipt)
    return original, doc


def summary(doc, original):
    return {**identity(doc), "path": (HOME / (doc["id"] + ".json")).as_posix(),
            "revision": sha256(original).hexdigest()}


def profile_paths(private):
    folder = private / HOME
    if folder.resolve() != folder or (folder.exists() and not folder.is_dir()):
        raise ValueError("Use a regular private stakeholder profile directory")
    retained = upgrades.source_paths(private)
    return {path.stem: path_for(private, path.stem) for path in storage.inventory(private)
            if path.parent == folder and path.suffix == ".json" and path != private / INDEX
            and path.relative_to(private).as_posix() not in retained and path.exists()}


def directory(private):
    path = private / INDEX
    if path.resolve() != path or (path.exists() and not path.is_file()):
        raise ValueError("Use a regular private identity directory")
    if not path.exists():
        return None, {}
    storage.require_visible(private, INDEX)
    original = path.read_bytes()
    data = storage.json_input(original)
    if not isinstance(data, dict):
        raise ValueError("Invalid private identity directory")
    for identifier, item in data.items():
        context_capture.fields(item, (*IDENTITY_FIELDS, "revision", "path"), ("aliases",))
        identity(item)
        if (item["id"] != identifier or item["path"] != (HOME / (identifier + ".json")).as_posix()
                or not isinstance(item["revision"], str) or not DIGEST.fullmatch(item["revision"])):
            raise ValueError("Invalid private identity directory entry")
    return original, data


def write_directory(private, original, data):
    body = json.dumps(data, sort_keys=True, ensure_ascii=False, indent=2) + "\n"
    if original != body.encode():
        storage.require_visible(private, INDEX)
        storage.replace_text(private / INDEX, original, body, mode=0o600)


def read_stamps(private):
    path = private / STAMPS
    if path.resolve() != path or (path.exists() and not path.is_file()):
        raise ValueError("Use a regular local identity check file")
    original = path.read_bytes() if path.exists() else None
    stamps = storage.json_input(original) if original is not None else {}
    if not isinstance(stamps, dict):
        raise ValueError("Invalid local identity checks")
    return original, stamps


def save_stamps(private, raw, stamps):
    content = json.dumps(stamps, sort_keys=True) + "\n"
    if raw != content.encode():
        storage.replace_text(private / STAMPS, raw, content, mode=0o600)


def verified_stamps(private, identities, *, except_id=None):
    raw, stamps = read_stamps(private)
    paths = profile_paths(private)
    checked = set(paths) | set(identities) | set(stamps)
    checked.discard(except_id)
    for key in checked:
        if (key not in paths or key not in identities
                or stamps.get(key) != [identities[key]["revision"], context_index.signature(paths[key])]):
            raise ValueError("Refresh the private directory with stakeholder-profile index before selecting a person")
    return raw, stamps


def index_profiles(private, *, preview=False):
    """An explicit maintenance pass may inspect all records to restore their identity directory."""
    with storage.writer_lock(private):
        original, previous = directory(private)
        raw_stamps, previous_stamps = read_stamps(private)
        data, stamps = {}, {}
        for identifier, path in profile_paths(private).items():
            before = context_index.signature(path)
            raw, doc = read_file(path, identifier)
            if context_index.signature(path) != before:
                raise ValueError("A profile changed while rebuilding its directory. Retry with the current records")
            data[identifier] = summary(doc, raw)
            stamps[identifier] = [data[identifier]["revision"], before]
        if preview:
            return {"profiles": len(data), "refresh_needed": data != previous or stamps != previous_stamps}
        if data or original is not None:
            write_directory(private, original, data)
            save_stamps(private, raw_stamps, stamps)
        return {"indexed": len(data)}


def indexed_labels(people, *, short_names=False):
    result = {}
    for person in people:
        names = {normalized(label) for label in labels(person)}
        if short_names:
            names.add(normalized(person["name"]).split()[0])
        for name in names:
            result.setdefault(name, []).append(person)
    return result


def lookup(private, query=None):
    """Match private identity metadata before opening any person's evidence."""
    _, identities = directory(private)
    verified_stamps(private, identities)
    if query is None:
        return list(identities.values())
    return indexed_labels(identities.values()).get(normalized(query), [])


def show(private, identifier, topic=None):
    if topic is not None and topic not in TOPICS:
        raise ValueError("Choose a supported stakeholder profile topic")
    original, doc = read(private, identifier)
    if doc is None:
        raise ValueError("No accepted profile for this ID")
    rows = [row for row in current_entries(doc["entries"]) if topic is None or row["topic"] == topic]
    past_role = {row["id"] for row in doc["entries"][:doc.get("current_role_from", 0)]}
    rows = [{**row, **({"earlier_role": True} if row["id"] in past_role else {})} for row in rows]
    return {**summary(doc, original), "entries": [row for row in rows if row["kind"] != "hypothesis"],
            "pm_hypotheses": [row for row in rows if row["kind"] == "hypothesis"]}


def check_workspace(private):
    try:
        _, identities = directory(private)
        paths = profile_paths(private)
        for identifier, path in paths.items():
            raw, doc = read_file(path, identifier)
            if identities and summary(doc, raw) != identities.get(identifier):
                raise ValueError("Refresh the private identity directory with stakeholder-profile index")
        if set(identities) - set(paths):
            raise ValueError("Refresh the private identity directory with stakeholder-profile index")
    except (OSError, ValueError) as exc:
        return [f"{private.name}/{HOME}: {exc}"]
    return []


def change_for(args):
    required = (*IDENTITY_FIELDS, "topic", "kind", "wording", "source", "excerpt")
    optional = ("observed_on", "scope", "subject", "attribution", "replaces", "distinct_from", "update_identity", "aliases", *CLAIM_OPTIONS)
    context_capture.fields(args, required, optional)
    details = {"observed_on": "unknown", "scope": "unknown", "subject": "unknown", "replaces": None,
               "attribution": "PM" if args["kind"] == "hypothesis" else args["source"]}
    details.update(claim_details(args))
    distinct = args.get("distinct_from", [])
    if not isinstance(distinct, list) or not all(isinstance(v, str) and layout.SLUG.fullmatch(v) for v in distinct):
        raise ValueError("List stable profile IDs when distinguishing two people with the same name")
    update_identity = args.get("update_identity", False)
    if type(update_identity) is not bool:
        raise ValueError("Use true to explicitly review a changed name or role for this profile ID")
    return {**identity(args), **claim(details), "distinct_from": sorted(set(distinct)), "update_identity": update_identity}


def updated_identity(change, doc):
    person = identity(change)
    if doc:
        # An omitted list keeps approved aliases. Renames keep the previous name with the stable ID.
        aliases = list(change.get("aliases", doc.get("aliases", [])))
        if normalized(person["name"]) != normalized(doc["name"]):
            if normalized(doc["name"]) not in {normalized(name) for name in aliases}:
                aliases.append(doc["name"])
        aliases = [name for name in aliases if normalized(name) != normalized(person["name"])]
        person.pop("aliases", None)
        if aliases:
            person["aliases"] = aliases
    return identity(person)


def check_identity(private, change, doc):
    changed = doc is not None and identity(doc) != updated_identity(change, doc)
    if changed and not change["update_identity"]:
        raise ValueError("The saved name or role differs. Confirm the person and preview again with update_identity")
    if doc is None or changed:
        person = updated_identity(change, doc)
        names = {normalized(value) for value in [person["name"], *person.get("aliases", [])]}
        matches = [item for item in lookup(private) if item["id"] != person["id"] and
                   names.intersection(normalized(value) for value in [item["name"], *item.get("aliases", [])])]
        if sorted(item["id"] for item in matches) != change["distinct_from"]:
            raise ValueError("Clarify the matching people and supply their IDs in distinct_from before creating or renaming")


def review_for(private, change, original, doc):
    check_identity(private, change, doc)
    details = claim_details(change)
    active = current_entries(doc["entries"]) if doc else []
    identifier = claim_id(change["id"], details)
    duplicate = any(row["id"] == identifier for row in active)
    if not duplicate and change["replaces"] is not None and not any(row["id"] == change["replaces"] for row in active):
        raise ValueError("The claim to replace is no longer current. Read the profile and review the correction")
    if doc and not duplicate and any(row["id"] == identifier for row in doc["entries"]):
        raise ValueError("This claim was superseded. Review the new evidence as a correction to a current claim")
    content = {"base_revision": sha256(original).hexdigest() if original is not None else "absent",
               "destination": (HOME / (change["id"] + ".json")).as_posix(), "change": change,
               "duplicate": duplicate}
    return {**content, "review_id": fingerprint(content)}


def preview(private, data):
    """Build a review in memory. Source access and storage approval are independent."""
    if not isinstance(data, dict):
        raise ValueError("Supply the proposed claim")
    data = dict(data)
    source_read = data.pop("source_read", None)
    change = change_for(data)
    validate_source(private, change, source_read)
    original, doc = read(private, change["id"])
    return review_for(private, change, original, doc)


def validate_source(private, change, source_read):
    if "evidence" in change:
        import stakeholder_signals
        stakeholder_signals.validate_change(private, change, source=source_read)
    else:
        reference = source_evidence.source_target(change["source"].strip())
        if (source_read is not None or source_evidence.local_name(reference) is not None
                or re.match(r"(?:https?://|(?:transcript|document|article|meeting):)", reference, re.I)):
            raise ValueError("Use checked passage evidence for a source document. Cite a PM account separately")



def accept(private, data):
    context_capture.fields(data, ("review", "approved_wording"), ("source_read",))
    review = data["review"]
    context_capture.fields(review, REVIEW_FIELDS)
    change = change_for(review["change"])
    if (review["review_id"] != fingerprint({key: review[key] for key in REVIEW_FIELDS if key != "review_id"})
            or change != review["change"] or data["approved_wording"] != change["wording"]):
        raise ValueError("Approve the exact reviewed wording, source and destination. Preview any edits again")
    identifier = change["id"]
    path = path_for(private, identifier)
    with storage.writer_lock(private):
        original, doc = read(private, identifier)
        index_raw, identities = directory(private)
        raw_stamps, stamps = verified_stamps(private, identities, except_id=identifier)
        if doc and any(row["review_id"] == review["review_id"] for row in doc["entries"]):
            # A retry also finishes an interrupted directory update.
            saved = summary(doc, original)
            write_directory(private, index_raw, {**identities, identifier: saved})
            save_stamps(private, raw_stamps, {**stamps, identifier: [saved["revision"], context_index.signature(path)]})
            return {**saved, "written": False}
        validate_source(private, change, data.get("source_read"))
        if review_for(private, change, original, doc) != review:
            raise ValueError("The profile changed since review. Read it and preview the proposed wording again")
        if review["duplicate"] and identity(doc) == updated_identity(change, doc):
            return {**summary(doc, original), "written": False}
        details = claim_details(change)
        if review["duplicate"]:
            raise ValueError("Cite a new or corrected claim for the changed profile identity")
        row = {**details, "id": claim_id(identifier, details), "review_id": review["review_id"]}
        result = {**updated_identity(change, doc), "format": 1, "entries": [*(doc["entries"] if doc else []), row]}
        if doc:
            start = len(doc["entries"]) if normalized(doc["role"]) != normalized(change["role"]) else doc.get("current_role_from")
            if start:
                result["current_role_from"] = start
        body = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        storage.require_visible(private, path.relative_to(private))
        storage.require_visible(private, INDEX)
        storage.replace_text(path, original, body, mode=0o600)
        saved = summary(result, body.encode())
        write_directory(private, index_raw, {**identities, identifier: saved})
        save_stamps(private, raw_stamps, {**stamps, identifier: [saved["revision"], context_index.signature(path)]})
        return {**saved, "claim_id": row["id"], "written": True}


def register(commands):
    group = commands.add_parser("stakeholder-profile", help="Review and use individual stakeholder profiles")
    group.set_defaults(hub_action=run)
    operations = group.add_subparsers(dest="operation", required=True)
    index = operations.add_parser("index", help="Restore identity metadata from accepted private profiles")
    index.add_argument("--preview", action="store_true", help="Check the directory against the original profiles")
    listing = operations.add_parser("list", help="List identities or find exact name, role, or ID matches")
    listing.add_argument("query", nargs="?")
    display = operations.add_parser("show", help="Read current claims about one confirmed person")
    display.add_argument("id")
    display.add_argument("--topic", choices=TOPICS)
    operations.add_parser("preview", help="Review a sourced claim without filing it")
    operations.add_parser("accept", help="File the PM's exact reviewed wording from standard input")


def run(root, args, prepare):
    private = workspace.repo(root, "workspace")
    if args.operation == "index":
        if args.preview:
            workspace.settings(root)
        else:
            prepare(root)
        result = index_profiles(private, preview=args.preview)
    elif args.operation == "accept":
        prepare(root)
        result = accept(private, storage.json_input(sys.stdin.read()))
    else:
        workspace.settings(root)
        if args.operation == "list":
            result = lookup(private, args.query)
        elif args.operation == "show":
            result = show(private, args.id, args.topic)
        else:
            result = preview(private, storage.json_input(sys.stdin.read()))
    print(json.dumps(result, ensure_ascii=False, indent=2))
