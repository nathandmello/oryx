"""Identify one reviewed decision, preserving its owning scope and the cited evidence."""

from datetime import date
from os.path import normpath
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit

import initiative_events
import initiative_store
import layout
import records
import storage
import task_context


def fingerprint(value):
    return initiative_store.digest(initiative_store.canonical(value))


def registered(root, product, initiative=None):
    _, payload, register = initiative_store.read(root, product)
    if not register.setup or (initiative and initiative not in register.items):
        raise ValueError("Choose an existing registered product and initiative")
    identity = register.setup["references"]["product_id"]
    owner_revision = fingerprint(payload)
    areas = {}
    decisions = []
    for ordinal, event in enumerate(payload["events"], 1):
        item = event.get("initiative")
        if event["type"] in {"capture", "set-areas"}:
            areas[item] = event.get("areas", [])
        if event["type"] == "decision" and (initiative is None or item == initiative):
            ref = {"kind": "registered", "product": product, "initiative": item,
                   "ordinal": ordinal, "digest": fingerprint(event)}
            authority = {"product": product, "areas": areas[item], "initiative": item,
                         "record": layout.initiative_register(product), "artifact_id": identity,
                         "on": event["on"], "entry": event, "sources": [event["source"]], "owner_revision": owner_revision}
            decisions.append({"decision": ref, "authority": authority})
    return decisions


def cited_archive(private, record, source):
    """Keep the dated bibliography and fingerprint any locally cited evidence file."""
    archive = dict(source)
    attachments = {}
    for name in re.findall(r"\[[^\]\n]+\]\((<[^>\n]+>|[^\s)]+)\)", source["Source"]):
        parsed = urlsplit(name.strip("<>"))
        if parsed.scheme or parsed.netloc or not parsed.path:
            continue
        raw = Path(unquote(parsed.path))
        if raw.is_absolute() or "\\" in str(raw):
            raise ValueError("Choose a local decision source inside the private workspace")
        relative = Path(normpath((Path(record).parent / raw).as_posix()))
        target = private / relative
        if (any(part.startswith(".") or part == "secrets" for part in relative.parts)
                or target.resolve() != target or not target.is_file()):
            raise ValueError("The closed decision references missing or redirected source material")
        storage.require_visible(private, relative)
        attachments[relative.as_posix()] = initiative_store.digest(target.read_bytes())
    if attachments:
        archive["files"] = attachments
    return archive


def context(private, record):
    if not isinstance(record, str):
        raise ValueError("Choose a reviewed context record")
    docs = task_context.context_documents(private)
    doc = docs.get(record)
    if not doc or layout.brief_kind(record) != doc["kind"] or doc["kind"] == "context-note":
        raise ValueError("Choose a context record in its authoritative scope")
    text = doc["text"]
    state, _ = records.work_state(text)
    identifier, errors = records.state_errors(text)
    if sum(records.work_state(d["text"])[0].get("ID") == identifier for d in docs.values()) != 1:
        raise ValueError("Resolve the duplicate context identity before selecting a decision")
    texts = {name: data["text"] for name, data in docs.items()}
    context_errors, _ = records.context_errors(record, text, doc["kind"], texts, records.context_content(doc["kind"], text))
    errors.extend(context_errors)
    if errors:
        raise ValueError(f"{record}: " + "; ".join(errors))
    if state["State"] == "draft":
        raise ValueError("Review the context record before using its decisions")
    if doc["parent"] and doc["parent"] not in docs:
        raise ValueError("The owning context record needs its valid parent")
    heading = "Decisions already closed"
    if records.section(text, heading) is None:
        return []
    # Keep the original area marker, but only accept rows visible to the context reader.
    rows, errors = records.table(text, heading, records.CONTEXT_TABLES[heading])
    if errors:
        raise ValueError(f"{record}: " + "; ".join(errors))
    area_names = set(task_context.AREA.findall(text))
    visible = {row["text"] for row in task_context.linked_entries(doc, area_names, date.today())
               if row["section"] == heading and row["binding"]}
    reviewed = dict(records.table(text, "Context controls", ("Field", "Value"))[0])["Last reviewed"]
    decisions = []
    active_keys = set()
    for row in rows:
        formatted = "| " + " | ".join(row) + " |"
        if (task_context.SUPERSEDED.search(formatted)
                or records.visible_section_markup(formatted).strip() not in visible):
            continue
        key = tuple(cell.casefold() for cell in row[:2])
        if key in active_keys:
            raise ValueError("Resolve repeated active decisions for this question and scope in the owning context")
        active_keys.add(key)
        on = row[2].rpartition(", ")[2]
        if not initiative_events.iso_date(reviewed) or reviewed < on:
            continue
        sources = [doc["sources"][ref[1:-1]] for ref in dict.fromkeys(records.SOURCE_REFERENCE.findall(row[3]))]
        if not sources or any(not initiative_events.iso_date(source["Source date"]) or
                              source["Checked on"] > reviewed for source in sources):
            continue
        area = doc["area"]
        marked = task_context.AREA.search(row[1])
        if marked:
            if not doc["product"] or (area and marked[1] != area):
                continue
            area = marked[1]
        areas = [f"product/{doc['product']}/area/{area}"] if area else []
        authority = {"product": doc["product"], "areas": areas, "initiative": doc["initiative"],
                     "record": record, "artifact_id": identifier, "on": on, "entry": row,
                     "sources": [cited_archive(private, record, source) for source in sources]}
        ref = {"kind": "context", "record": record, "artifact_id": identifier, "digest": fingerprint(authority)}
        authority["owner_revision"] = fingerprint(text)
        decisions.append({"decision": ref, "authority": authority})
    return decisions


def lookup(root, ref):
    if not isinstance(ref, dict):
        raise ValueError("Select the exact decision returned by forecast decisions")
    if ref.get("kind") == "registered":
        candidates = registered(root, ref.get("product"), ref.get("initiative"))
    elif ref.get("kind") == "context":
        candidates = context(storage.private_root(root), ref.get("record"))
    else:
        raise ValueError("Select a signed initiative decision or a reviewed closed context decision")
    matches = [entry["authority"] for entry in candidates if fingerprint(ref) == fingerprint(entry["decision"])]
    if len(matches) != 1:
        raise ValueError("The decision is missing, ambiguous, superseded or changed. Select its current reference.")
    return matches[0]
