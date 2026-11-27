"""Validate purpose, entity, and the reader need for every new record."""

from os.path import relpath
from pathlib import Path
import re
from urllib.parse import quote, unquote, urlsplit

import layout
import records
import storage
import upgrades

BASES = ("event-history", "maintained-reference", "independent-deliverable")
SLUG = layout.SLUG
GENERIC = {"all", "catch-all", "catchall", "everything", "new", "random", "stuff", "inbox", "unclassified",
           "uncategorised", "uncategorized", "unfiled", "unsorted", "unorganised", "unorganized", "various", "archive", "archives", "area", "areas", "audit", "audits", "context", "data", "detail",
           "details", "doc", "docs", "document", "documents", "file", "files", "general", "info",
           "information", "items", "item", "materials", "material", "content", "contents", "misc", "miscellaneous", "note", "notes", "other", "overview", "record",
           "records", "reference", "references", "research", "source", "sources", "temp", "tmp"}
PERIOD = re.compile(r"(?:[12][0-9]{3}|(?:fy|q|week|month|quarter)[0-9]+)")


def home(name):
    if layout.valid_work(name):
        return Path(name).parent
    return layout.entity(name)


def area_parent(private, name):
    if not records.is_area_path(name):
        raise ValueError("Choose the standard product area overview path")
    product, area, group = layout.area_identity(name)
    records.area_brief_path(product, area, private=private, group=group)
    options = records.product_briefs(private, Path(name).parts[2])
    if len(options) != 1:
        raise ValueError("Establish the owning product overview before creating product area context")
    return options[0]


def area_contract(private, name, parent, basis, reason, trigger):
    owning = area_parent(private, name)
    if (parent and parent != owning) or (basis and basis != "maintained-reference"):
        raise ValueError("Product area context is a maintained reference under its owning product brief")
    check_purpose(reason, trigger)
    return {"parent": owning, "basis": "maintained-reference", "reason": reason, "trigger": trigger}


def check_purpose(*values):
    if not all(isinstance(v, str) and records.specific(v.strip()) and len(v.splitlines()) == 1
               and "|" not in v for v in values):
        raise ValueError("Give the reader's independent need and a concrete review or completion trigger")


def note_path(private, name):
    path = private / name
    if (Path(name).is_absolute() or Path(name).as_posix() != str(name) or path.resolve() != path or len(Path(name).parts) < 2 or
            any(p.startswith(".") or p in {"sources", "secrets"} for p in Path(name).parts)):
        raise ValueError("Choose a regular record inside the private repository")
    return path


def filing_fields(text):
    rows, errors = records.table(text, "Filing", ("Field", "Value"))
    if errors or len(rows) != len(dict(rows)):
        raise ValueError("Invalid filing decision")
    return dict(rows)


def validate_question(value):
    check_purpose(value)
    if not value.endswith("?") or len(value.split()) < 3:
        raise ValueError("State the recurring reader question that defines this topic")
    return value


def question_key(question):
    return tuple(re.findall(r"\w+", question.casefold()))


def topic_directories(private, owner):
    root = private / owner
    if not root.is_dir() or root.resolve() != root:
        return []
    reserved = {"sources", "secrets"}
    if len(owner.parts) == 3 and owner.parts[:2] == ("context", "products"):
        reserved.update(("areas", "initiatives"))
        for overview in root.glob("*/*/overview.md"):
            relative = overview.relative_to(private)
            if layout.area_identity(relative) and records.marked_area(overview):
                reserved.add(relative.parts[3])
    return sorted(child.name for child in root.iterdir() if child.name not in reserved
                  and not child.name.startswith(".") and not child.is_symlink() and child.is_dir())


def topic_structure_errors(private):
    """The CLI and external editors share the topic-name and breadth limits."""
    entities = set()
    for path in storage.inventory(private):
        relative = path.relative_to(private)
        kind = layout.brief_kind(relative)
        if kind and (kind != "product-area-context" or records.marked_area(path)):
            entities.add(layout.entity(relative))
    problems = []
    for owner in sorted(entities):
        child = layout.area_identity(owner / "overview.md")
        if child:
            product, area, group = child
            try:
                records.area_brief_path(product, area, private=private, group=group)
            except ValueError as exc:
                problems.append(f"{owner}: {exc}")
        topics = topic_directories(private, owner)
        if len(topics) > layout.MAX_TOPICS:
            problems.append(f"{owner}: reuse at most {layout.MAX_TOPICS} topic folders")
        for name in topics:
            try:
                valid_topic(name)
            except ValueError as exc:
                problems.append(f"{owner / name}: {exc}")
    return problems


def topic_choices(private, owner):
    topics = {name: set() for name in topic_directories(private, owner)}
    root = private / owner
    sources = upgrades.source_paths(private)
    for name in storage.inventory(private):
        if name.relative_to(private).as_posix() in sources:
            continue
        relative = name.relative_to(root) if root in name.parents else None
        if (not relative or len(relative.parts) != 2 or relative.parts[0] not in topics or
                name.suffix != ".md" or not name.is_file() or name.resolve() != name):
            continue
        with name.open("rb") as stream:
            if stream.readline(128).rstrip() != b"<!-- pm: context-note -->":
                continue
            fields = filing_fields(stream.read().decode("utf-8"))
        question = fields.get("Topic question")
        if question:
            topics[relative.parts[0]].add((validate_question(question), fields.get("Founding peer", "")))
    return topics


def valid_topic(name):
    words = name.split("-")
    if (not SLUG.fullmatch(name) or len(words) > 4 or name in GENERIC or "catch-all" in name or
            all(w in GENERIC for w in words) or any(w.isdigit() or PERIOD.fullmatch(w) for w in words)):
        raise ValueError("Choose a short topic by subject. Avoid generic labels, dates, and source names")


def check_source_label(category, references):
    """Reject a proposed topic named for an identifiable input document."""
    for reference in references:
        linked = re.fullmatch(r"\[([^\]]*)\]\(([^)]+)\)", reference)
        names = [reference] if not linked else [linked[1], unquote(urlsplit(linked[2]).path)]
        for name in names:
            stem = Path(name).stem.casefold()
            if "-".join(re.findall(r"[a-z0-9]+", stem)) == category:
                raise ValueError("Name the topic for the shared reader question, independently of its source")


def note_contract(private, name, parent, basis, reason, trigger, topic_question=None, topic_peer=None):
    path = note_path(private, name)
    owner = layout.entity(name)
    if records.context_location("context-note", name):
        raise ValueError(records.context_location("context-note", name))
    if not isinstance(parent, str) or not parent:
        raise ValueError("A separate record needs its existing parent path")
    parent_path = note_path(private, parent)
    if not parent_path.is_file() or parent in upgrades.source_paths(private):
        raise ValueError("Choose an existing owning overview or work artifact")
    with parent_path.open(encoding="utf-8") as stream:
        marker = records.MARKER.match(stream.readline())
    if marker and (marker[1] in layout.WORK_FOLDERS or marker[1] in records.OPPORTUNITY_KINDS):
        if not layout.valid_work(parent, marker[1]):
            raise ValueError("Choose a working artifact from workspace/")
    elif not marker or layout.brief_kind(parent) != marker[1] or home(parent) != owner:
        raise ValueError("Choose the owning entity overview or a specific work artifact")
    if basis not in BASES:
        raise ValueError("Choose a separate record basis: " + ", ".join(BASES))
    check_purpose(reason, trigger)
    contract = {"parent": parent, "basis": basis, "reason": reason, "trigger": trigger}
    if path.parent == private / owner:
        if topic_question or topic_peer:
            raise ValueError("Topic details apply only to a note in a topic folder")
        return contract
    category = path.parent.name
    valid_topic(category)
    choices = topic_choices(private, owner)
    known = choices.get(category, set())
    if len(known) > 1:
        raise ValueError("Resolve conflicting reader questions in the existing topic")
    if known:
        established, peer_id = next(iter(known))
        if not peer_id:
            raise ValueError("The existing topic needs its founding peer ID")
        if topic_question is not None and question_key(validate_question(topic_question)) != question_key(established):
            raise ValueError("Use the existing topic's reader question")
        if topic_peer:
            raise ValueError("Reuse the existing topic without a new peer")
        return dict(contract, topic_question=established, peer_id=peer_id)
    if len(set(choices) | {category}) > layout.MAX_TOPICS:
        raise ValueError(f"Reuse one of the {layout.MAX_TOPICS} topic folders or retain a flat note")
    if not isinstance(topic_question, str):
        raise ValueError("A new topic needs its recurring reader question and an existing peer")
    question = validate_question(topic_question)
    for existing, questions in choices.items():
        if any(question_key(question) == question_key(other) for other, _ in questions):
            raise ValueError(f"Reuse the existing topic {existing}")
    if not isinstance(topic_peer, str):
        raise ValueError("Give a different existing flat note of the same entity as the topic peer")
    peer = note_path(private, topic_peer)
    if peer.parent != private / owner or peer.stem == path.stem or not peer.is_file() or topic_peer in upgrades.source_paths(private):
        raise ValueError("A topic needs a different qualified flat note in this entity")
    with peer.open(encoding="utf-8") as stream:
        peer_text = stream.read()
    if not peer_text.startswith("<!-- pm: context-note -->\n"):
        raise ValueError("Choose an independently qualified context note as the topic peer")
    for text in (peer_text, parent_path.read_text(encoding="utf-8")):
        rows, _ = records.table(text, "Sources", records.SOURCE_COLUMNS)
        check_source_label(category, (row[1] for row in rows))
    verify_note(private, topic_peer, peer_text)
    peer_id, errors = records.state_errors(peer_text)
    if errors:
        raise ValueError("Repair the topic peer before using it")
    if any(peer_id == old for entries in choices.values() for _, old in entries):
        raise ValueError("This peer already supports an existing topic. Reuse that folder")
    return dict(contract, topic_question=question, peer_id=peer_id)


def add_contract(text, private, target, contract):
    link = quote(Path(relpath(private / contract["parent"], target.parent)).as_posix())
    rows = ("## Filing\n\n| Field | Value |\n| --- | --- |\n"
            f"| Owning record | [Parent]({link}) |\n| Basis | {contract['basis']} |\n"
            f"| Reader need | {contract['reason']} |\n| Review trigger | {contract['trigger']} |\n")
    if "topic_question" in contract:
        rows += f"| Topic question | {contract['topic_question']} |\n"
    if "peer_id" in contract:
        rows += f"| Founding peer | {contract['peer_id']} |\n"
    return text.replace("## Context controls\n", rows + "\n## Context controls\n", 1)


def check_new(private, kind, name, title, retiring=()):
    path = note_path(private, name)
    if re.search(r"-(?:copy|final|v\d+)$", path.stem):
        raise ValueError("Update the owning record or use a specific independent subject")
    import layout_upgrade
    blocked = [old for old in layout_upgrade.blocked(private, name) if old not in retiring]
    if blocked:
        raise ValueError("Resolve retained records before creating this destination: " + ", ".join(blocked))
    error = records.context_location(kind, name)
    if error:
        raise ValueError(error)
    owner = home(name)
    if kind == "context-note" and path.parent != private / owner:
        valid_topic(path.parent.name)
        if owner.parts[:2] == ("context", "products") and len(owner.parts) == 3 and path.parent.is_dir():
            if path.parent.name not in topic_directories(private, owner):
                raise ValueError("Choose a topic outside the product's area groups")
    label = (title or path.stem.replace("-", " ")).strip().casefold()
    for other in storage.inventory(private):
        rel = other.relative_to(private)
        if (rel.as_posix() in retiring or other == path or other.suffix != ".md"
                or other.resolve() != other or not other.is_file() or owner not in rel.parents
                or any(p.startswith(".") or p in {"sources", "secrets"} for p in rel.parts)):
            continue
        try:
            other_owner = home(rel)
        except ValueError:
            continue
        if other_owner != owner:
            continue
        with other.open("rb") as stream:
            if stream.readline(128).rstrip() == f"<!-- pm: {kind} -->".encode():
                existing = stream.readline().decode("utf-8").removeprefix("# ").strip().casefold()
                if rel.stem == path.stem or existing == label:
                    raise ValueError(f"Reuse the existing {kind}: {rel}")


def note_id(private, entity, candidate):
    relative = candidate.relative_to(private)
    if (candidate.suffix != ".md" or not candidate.is_file() or candidate.resolve() != candidate or
            entity not in relative.parents or records.context_location("context-note", relative) or
            layout.entity(relative) != entity or any(p.startswith(".") or p in {"sources", "secrets"} for p in relative.parts)):
        return None
    with candidate.open("rb") as stream:
        if stream.readline(128).rstrip() == b"<!-- pm: context-note -->":
            text = stream.read().decode("utf-8")
            if records.section(text, "Filing"):
                return records.work_state(text)[0].get("ID")
    return None


def verify_note(private, name, text):
    """Check the fields that justify a standalone artifact and its topic."""
    marker = records.MARKER.match(text)
    if not marker or marker[1] not in {"context-note", "product-area-context"}:
        return
    data = filing_fields(text)
    required = {"Owning record", "Basis", "Reader need", "Review trigger"}
    if not required <= data.keys() <= required | {"Topic question", "Founding peer"}:
        raise ValueError(f"Invalid filing decision in {name}")
    parent = re.fullmatch(r"\[Parent\]\(([^)]+)\)", data.get("Owning record", ""))
    if not parent:
        raise ValueError(f"Identify the owning parent in {name}")
    owner = (private / name).parent / unquote(parent[1])
    resolved = owner.resolve().relative_to(private).as_posix()
    if marker[1] == "product-area-context":
        if data.keys() != required or data.get("Basis") != "maintained-reference":
            raise ValueError("Use the maintained-reference basis for product area context")
        expected = area_contract(private, name, resolved, data["Basis"], data["Reader need"], data["Review trigger"])
        if records.parent_reference(name, text) != expected["parent"]:
            raise ValueError("The product area must inherit its owning product context")
        return
    entity = layout.entity(name)
    path = Path(name)
    if path.parent == entity:
        if data.keys() != required:
            raise ValueError("Flat references use the basic filing decision")
        note_contract(private, name, resolved, data["Basis"], data["Reader need"], data["Review trigger"])
        return
    # Validate the parent and the independent filing test without creating a topic.
    note_contract(private, (entity / path.name).as_posix(), resolved, data["Basis"], data["Reader need"], data["Review trigger"])
    if len(path.relative_to(entity).parts) != 2:
        raise ValueError("Use only one topic level inside the entity")
    valid_topic(path.parent.name)
    question = validate_question(data.get("Topic question"))
    founding_peer = data.get("Founding peer", "")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{2,79}", founding_peer):
        raise ValueError("Identify the qualified founding peer by its stable record ID")
    protected = upgrades.source_paths(private)
    if not any(note_id(private, entity, candidate) == founding_peer for candidate in storage.inventory(private)
               if candidate != private / name and candidate.relative_to(private).as_posix() not in protected):
        # A peer can itself move into its topic through a verified filing plan.
        if (records.work_state(text)[0].get("ID") != founding_peer or not any(
                child != private / name and child.is_file() and child.resolve() == child and
                child.suffix == ".md" and f"| Founding peer | {founding_peer} |" in child.read_text(encoding="utf-8", errors="replace")
                for child in (private / path.parent).glob("*.md"))):
            raise ValueError("The topic needs its distinct existing qualified peer in this entity")
    topics = topic_choices(private, entity)
    if len(set(topics) | {path.parent.name}) > layout.MAX_TOPICS:
        raise ValueError("Too many topic folders for one entity")
    for category, questions in topics.items():
        if category == path.parent.name and any((question_key(q), peer) != (question_key(question), founding_peer)
                                                for q, peer in questions):
            raise ValueError("Use one reader question per topic")
        if category != path.parent.name and any(question_key(q) == question_key(question) or peer == founding_peer
                                                for q, peer in questions):
            raise ValueError(f"Reuse the existing topic {category}")
