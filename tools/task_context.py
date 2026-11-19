"""Resolve current private Hub records for one task."""

from datetime import date, datetime
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import re
import time
from urllib.parse import urlsplit

import layout
import metric_registry
import records
import storage
import upgrades


KEEP = {"Data boundaries", "Constraints", "Constraints and open questions", "Ownership and constraints",
        "Dependencies and constraints", "Decisions already closed", "Review and approvals"}
AREA = re.compile(r"<!-- product-area:([a-z0-9-]+) -->")
SUPERSEDED = re.compile(r" \*\(Superseded by \[(S[1-9]\d*)\]\)\*")
STOP_WORDS = set("about again and api app are can from give have here how its our plan please the this use what when "
                 "which will with work workspace would draft context overview product write update support "
                 "should task rule note requirement area current review who did after before need for but has had "
                 "ingest utc file read data source captured pending questions owner follow".split())
FOLLOW_UP = re.compile(r"^(?:please\s+)?(?:(?:can|could|would) you\s+(?:please\s+)?)?"
                       r"(?:continue\b|resume\b|revise (?:it|that|this)\b|"
                       r"update (?:it|that|this)\b|make (?:it|that|this)\b|what about\b)", re.I)
SWITCH = re.compile(r"^(?:please\s+)?switch\s+from\b.+?\bto\s+", re.I)
IDENTIFIER = re.compile(r"\b[a-z][\w-]*\.[a-z][\w.-]*[a-z0-9]\b", re.I)
DATE = re.compile(r"\b(?:as of|on)\s+(\d{4}-\d{2}-\d{2}|"
                  r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"
                  r" \d{1,2}, \d{4})\b", re.I)


def words(value):
    tokens = {word for word in re.findall(r"[^\W_]+", value.casefold())
              if len(word) >= 3 and not word.isdigit() and word not in STOP_WORDS}
    return {word[:-2] if len(word) >= 6 and word.endswith("ed")
            else word[:-1] if len(word) >= 5 and word.endswith("s") and not word.endswith("ss") else word
            for word in tokens}


def title(path, text):
    match = re.search(r"(?m)^# (.+)$", text)
    return match[1].strip() if match else path.stem


def private_files(private, domain):
    excluded = upgrades.source_paths(private)
    for path in storage.inventory(private):
        relative = path.relative_to(private)
        if (relative.parts[0] in domain and relative.name != "README.md" and relative.suffix == ".md"
                and not any(part.startswith(".") or part in {"sources", "secrets"} for part in relative.parts)
                and relative.as_posix() not in excluded and path.resolve() == path and path.is_file()):
            yield relative, path


def context_documents(private):
    documents = {}
    for relative, path in private_files(private, {"context"}):
        text = path.read_text(encoding="utf-8")
        kind = records.MARKER.match(text)
        if not kind or kind[1] not in records.CONTEXT_KINDS or records.context_location(kind[1], relative):
            continue
        name = relative.as_posix()
        entity = layout.entity(relative)
        parent = records.parent_reference(name, text)
        product = entity.parts[2] if entity.parts[1] == "products" else None
        initiative = None
        if entity.parts[1] == "initiatives" or entity.parts[3:4] == ("initiatives",):
            owner = entity / "overview.md"
            if kind[1] == "context-note":
                parent = owner.as_posix()
            initiative = entity.name
            if parent and layout.brief_kind(parent) == "product-context":
                product = Path(parent).parts[2]
        sources, _ = records.table(text, "Sources", records.SOURCE_COLUMNS)
        documents[name] = {
            "record": name, "kind": kind[1], "title": title(relative, text), "product": product,
            "area": entity.name if entity.parts[3:4] == ("areas",) else None,
            "initiative": initiative, "parent": parent, "text": text, "company": entity == Path(layout.COMPANY).parent,
            "sources": {row[0]: dict(zip(records.SOURCE_COLUMNS, row)) for row in sources
                        if re.fullmatch(r"S[1-9]\d*", row[0])},
        }
    for doc in documents.values():
        if doc["initiative"] and not doc["product"] and doc["parent"] in documents:
            doc["product"] = documents[doc["parent"]]["product"]
    return documents


def resolved_artifact(name, documents):
    if name in documents:
        doc = documents[name]
        if doc["company"]:
            return {"product": None, "area": None, "initiative": None, "company": True}
        return {key: doc[key] for key in ("product", "area", "initiative")}
    parts = Path(name).parts
    products = {doc["product"] for doc in documents.values() if doc["product"]}
    if len(parts) >= 3 and parts[0] == "workspace":
        product = parts[2] if len(parts) >= 4 else Path(parts[2]).stem
        if product in products:
            initiative = parts[3] if len(parts) >= 4 and parts[1] in {"initiatives", "experiments"} else None
            return {"product": product, "initiative": initiative, "area": None}
    return {}


def mentions(prompt, name):
    phrase = r"[\s-]+".join(re.escape(part) for part in re.split(r"[\s-]+", name.strip()))
    return bool(phrase and re.search(r"(?<!\w)" + phrase + r"(?!\w)", prompt, re.I))


def source_matches(scoped, prompt, terms):
    """Use a provider or exact identifier as a stronger signal than topical overlap."""
    aliases = set()
    identifiers = set(IDENTIFIER.findall(prompt.casefold()))
    direct = False
    for doc in scoped:
        direct |= bool(identifiers.intersection(IDENTIFIER.findall(doc["text"].casefold())))
        for row in doc["sources"].values():
            reference = row["Source"]
            label, separator, target = reference.partition("](")
            aliases.update(words(label))
            if separator and target.startswith(("https://", "http://")):
                try:
                    host = urlsplit(target[:-1]).hostname or ""
                except ValueError:
                    continue
                labels = host.split(".")
                if len(labels) > 1 and labels[-1] not in {"test", "example", "invalid", "localhost"}:
                    provider = labels[-3] if len(labels) >= 3 and labels[-2] in {"co", "com", "org"} else labels[-2]
                    direct |= bool(words(provider) & terms & words(label))
    return direct, len(terms & aliases)


def choose_scope(private, documents, prompt, cwd, previous, explicit):
    overview = {doc["product"]: doc for doc in documents.values() if doc["kind"] == "product-context"}
    if explicit:
        return explicit, []
    prompt = SWITCH.sub("", prompt)
    artifacts = re.findall(r"(?:private/)?((?:context|workspace)/[\w./-]+?\.md)\b", prompt)
    known = [scope for name in artifacts if (scope := resolved_artifact(name, documents))]
    for value in re.findall(r"\bproduct/([a-z0-9-]+)(?:/area/([a-z0-9-]+))?", prompt):
        known.append({"product": value[0], "area": value[1] or None, "initiative": None})
    for product, doc in overview.items():
        identifier = records.work_state(doc["text"])[0].get("ID")
        if identifier and (match := re.search(r"\b" + re.escape(identifier) + r"/([a-z0-9-]+)\b", prompt)):
            known.append({"product": product, "area": None, "initiative": match[1]})
    if known:
        products = sorted({item["product"] for item in known if item["product"]})
        scopes = {(item["product"], item["area"], item["initiative"]) for item in known}
        if len(scopes) > 1:
            specific = [item for item in known if item["area"] or item["initiative"]]
            if len(products) > 1 or len({(item["area"], item["initiative"]) for item in specific}) > 1:
                return {}, sorted({"/".join(value for value in scope if value) or "company" for scope in scopes})
            return (specific or known)[0], []
        return known[0], []

    if re.search(r"\bcompany(?:-wide| context| overview| policy)\b", prompt, re.I):
        return {"company": True}, []

    terms = words(prompt)
    named = sorted(product for product, doc in overview.items()
                   if mentions(prompt, product) or mentions(prompt, doc["title"]))
    if len(named) == 1:
        return inferred_scope(documents, named[0], terms), []
    if named:
        return {}, named
    if previous and FOLLOW_UP.match(prompt.strip()):
        return previous, []
    if cwd and cwd != private and private in cwd.parents:
        scope = resolved_artifact((cwd / "scope.md").relative_to(private).as_posix(), documents)
        if scope:
            return scope, []

    strong, suggestions = [], []
    for product, doc in overview.items():
        scoped = [candidate for candidate in documents.values() if candidate["product"] == product]
        direct, related = source_matches(scoped, prompt, terms)
        if direct:
            strong.append(product)
        elif related >= 2 or terms & words(doc["title"]):
            suggestions.append(product)
    if len(strong) == 1:
        return inferred_scope(documents, strong[0], terms), []
    return {}, sorted(strong or suggestions)


def inferred_scope(documents, product, terms):
    candidates = [doc for doc in documents.values() if doc["product"] == product]
    areas = {doc["area"] for doc in candidates if doc["area"]}
    areas.update(area for doc in candidates for area in AREA.findall(doc["text"]))
    initiatives = {doc["initiative"] for doc in candidates if doc["initiative"]}
    matches = []
    for choices in (areas, initiatives):
        selected = [name for name in choices if (name_words := words(name.replace("-", " "))) and name_words <= terms]
        matches.append(selected[0] if len(selected) == 1 else None)
    return dict(zip(("product", "area", "initiative"), (product, *matches)))


def as_of(prompt):
    match = DATE.search(prompt)
    if match:
        try:
            return date.fromisoformat(match[1]) if match[1][0].isdigit() else datetime.strptime(match[1], "%B %d, %Y").date()
        except ValueError:
            pass
    return date.today()


def linked_entries(doc, areas, through):
    text = doc["text"]
    for section, _, start, end in records.section_blocks(text):
        if section not in records.context_sections(doc["kind"]):
            continue
        for value in re.split(r"\n(?=- |\| )", text[start:end].strip()):
            row = AREA.search(value)
            if row and row[1] not in areas:
                continue
            refs = records.SOURCE_REFERENCE.findall(SUPERSEDED.sub("", value))
            sources = [doc["sources"][ref[1:-1]] for ref in dict.fromkeys(refs) if ref[1:-1] in doc["sources"]]
            if any(source["Source date"] not in {"unknown", "undated"} and
                   source["Source date"] > through.isoformat() for source in sources):
                continue
            superseded = SUPERSEDED.search(value)
            if superseded:
                replacement = doc["sources"].get(superseded[1])
                if replacement and (replacement["Source date"] in {"unknown", "undated"}
                                    or replacement["Source date"] <= through.isoformat()):
                    continue
            if records.PLACEHOLDER.search(value) or not value.strip() or value.lstrip().startswith(("| ---", "| Term", "| Question")):
                continue
            content = SUPERSEDED.sub("", AREA.sub("", value)).strip()
            binding = bool(sources) and (section == "Decisions already closed" or (
                section in KEEP and value.lstrip().startswith("- Rule:")
            ))
            if section == "Decisions already closed":
                decision_date = re.search(r", (\d{4}-\d{2}-\d{2})\s*\|", content)
                if decision_date and decision_date[1] > through.isoformat():
                    continue
            yield {"record": doc["record"], "section": section, "text": content, "sources": sources,
                   "binding": binding}


def resolve(private, prompt="", *, cwd=None, previous=None, explicit=None):
    docs = context_documents(private)
    scope, choices = choose_scope(private, docs, prompt, cwd, previous, explicit)
    status = "ambiguous" if choices else "resolved" if scope else "unscoped"
    result = {"status": status, "scope": scope, "choices": choices, "entries": [], "warnings": []}
    through = as_of(prompt)
    metrics = metric_registry.effective(private.parent, private, scope.get("product"), through.isoformat())
    if not scope:
        selected_metrics = metric_registry.matching(metrics, prompt)
        if selected_metrics:
            result["metrics"] = selected_metrics
        return result
    product, area, initiative = (scope.get(key) for key in ("product", "area", "initiative"))
    areas = {area} if area else set()
    if product and initiative and (private / layout.initiative_register(product)).is_file():
        import initiative_store
        try:
            _, _, register = initiative_store.read(private.parent, product)
            item = register.items.get(f"{register.setup['references']['product_id']}/{initiative}")
            if item:
                areas.update(subject.rsplit("/", 1)[-1] for subject in item["areas"])
        except (OSError, ValueError) as exc:
            result["warnings"].append(f"Could not verify the registered initiative scope: {exc}")
    overview = docs.get(layout.product(product)) if product else None
    company = (overview["parent"] or layout.COMPANY) if overview else layout.COMPANY if scope.get("company") else None
    if product and not overview:
        result["warnings"].append(f"Missing product context for {product}.")
    if company and company not in docs:
        result["warnings"].append(f"Missing inherited context at {company}.")
    terms = words(prompt)
    entries = []
    for name, doc in docs.items():
        if not ((company and doc["company"]) or
                (product and doc["product"] == product and (doc["area"] is None or doc["area"] in areas)
                 and doc["initiative"] in (None, initiative))):
            continue
        if doc["kind"] == "context-note" and name not in prompt and not terms & words(doc["title"]):
            continue
        controls, _ = records.table(doc["text"], "Context controls", ("Field", "Value"))
        due = dict(controls).get("Review by", "")
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", due) and due < date.today().isoformat():
            result["warnings"].append(f"Review overdue for {name}. Confirm current authority before relying on it.")
        entries.extend(linked_entries(doc, areas, through))
    decisions = Counter((row["record"], *row["text"].split("|")[1:3]) for row in entries
                        if row["section"] == "Decisions already closed" and row["binding"])
    for (record, *_), count in decisions.items():
        if count > 1:
            result["warnings"].append(f"Resolve repeated active decisions in {record} before relying on their outcome.")
    entries.sort(key=lambda row: (row["section"] != "Data boundaries", not row["binding"],
                                  -len(terms & words(row["text"])), row["record"]))
    budget = 6500
    for row in entries:
        size = len(json.dumps(row, ensure_ascii=False))
        if size > budget:
            if row["binding"]:
                warning = f"Read the remaining binding entries in {row['record']} before acting."
                if warning not in result["warnings"]:
                    result["warnings"].append(warning)
            continue
        result["entries"].append(row)
        budget -= size
    numeric_context = " ".join(row["text"] for row in result["entries"] if row["text"].startswith("- Reported metric:"))
    selected_metrics = metric_registry.matching(metrics, f"{prompt} {numeric_context}")
    if selected_metrics:
        result["metrics"] = selected_metrics
    profile = private / layout.PROFILE
    if profile.resolve() == profile and profile.is_file() and layout.PROFILE not in upgrades.source_paths(private):
        preferences = records.section(profile.read_text(encoding="utf-8"), "Working preferences")
        if preferences and preferences.strip():
            result["pm_preferences"] = preferences.strip()[:1200]
    return result


def catalog(private):
    docs = context_documents(private)
    items = []
    for relative, path in private_files(private, {"context", "workspace"}):
        name = relative.as_posix()
        text = docs[name]["text"] if name in docs else path.read_text(encoding="utf-8")
        marker = records.MARKER.match(text)
        state, _ = records.work_state(text)
        items.append({"record": name, "title": title(relative, text),
                      "type": marker[1] if marker else "pm-context" if name == layout.PROFILE else "working-notes",
                      "id": state.get("ID"), "state": state.get("State"), **resolved_artifact(name, docs)})
    return items


def session_state(private, session):
    if not isinstance(session, str) or not session:
        return None
    path = private / ".state" / "task-context" / sha256(session.encode()).hexdigest()
    return path if path.resolve() == path else None


def previous_scope(private, session):
    path = session_state(private, session)
    if path and path.is_file() and time.time() - path.stat().st_mtime < 86400:
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def remember_scope(private, session, result, numeric):
    path = session_state(private, session)
    if path:
        with storage.writer_lock(private):
            storage.replace_text(path, path.read_text(encoding="utf-8") if path.is_file() else None,
                                 json.dumps({"scope": result["scope"], "binding": [
                                     {"record": row["record"], "section": row["section"]}
                                     for row in result["entries"] if row["binding"]
                                 ], "warnings": result["warnings"], "numeric": numeric}))
