"""Resolve current private Hub records for one task."""

from datetime import date, datetime
from collections import Counter
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import time
from urllib.parse import urlsplit

import conversation
import preferences
import evidence_reviews
import context_index
import context_search
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
SWITCH = re.compile(
    r"^(?:(?:please|now|let's|let’s)\s+)*(?:switch|move)\s+(?:from\b.+?\b)?to\s+", re.I
)
WORK_RECORD = re.compile(r"(?:private/)?(workspace/[\w./-]+?\.md)\b")
COMPANY_QUERY = re.compile(r"\bcompany(?:-wide| context| overview| policy)\b", re.I)
IDENTIFIER = re.compile(r"\b[a-z][\w-]*\.[a-z][\w.-]*[a-z0-9]\b", re.I)
DATE = re.compile(r"\b(?:as of|on)\s+(\d{4}-\d{2}-\d{2}|"
                  r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"
                  r" \d{1,2}, \d{4})\b", re.I)


def tokens(value):
    terms = (word for word in re.findall(r"[^\W_]+", value.casefold())
             if len(word) >= 3 and not word.isdigit() and word not in STOP_WORDS)
    return [word[:-2] if len(word) >= 6 and word.endswith("ed")
            else word[:-1] if len(word) >= 5 and word.endswith("s") and not word.endswith("ss") else word
            for word in terms]


def words(value):
    return set(tokens(value))


def title(path, text):
    match = re.search(r"(?m)^# (.+)$", text)
    return match[1].strip() if match else path.stem


def private_files(private, domain):
    excluded = upgrades.source_paths(private)
    for path in storage.inventory(private):
        relative = path.relative_to(private)
        if (relative.parts[0] in domain and relative.name != "README.md" and relative.suffix == ".md"
                and not any(part.startswith(".") or part in {"sources", "secrets"} for part in relative.parts)
                and relative.as_posix() not in excluded and path.resolve() == path and path.is_file() and os.access(path, os.R_OK)):
            yield relative, path


def read_document(relative, path, *, text=None, through=None):
    if text is None:
        text = path.read_text(encoding="utf-8")
    kind = records.MARKER.match(text)
    if not kind or kind[1] not in records.CONTEXT_KINDS or records.context_location(kind[1], relative):
        return None
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
    sources, _ = records.table(records.visible_section_markup(text), "Sources", records.SOURCE_COLUMNS)
    coverage = {ref: state for ref, state, checked in records.SOURCE_COVERAGE.findall(records.section(text, "Sources") or "")
                if through is None or checked <= through.isoformat()}
    return {
        "record": name, "kind": kind[1], "title": title(relative, text), "product": product,
        "area": entity.name if entity.parts[3:4] == ("areas",) else None,
        "initiative": initiative, "parent": parent, "text": text, "company": entity == Path(layout.COMPANY).parent,
        "sources": {row[0]: {**dict(zip(records.SOURCE_COLUMNS, row)), "coverage": coverage.get(row[0], "unrecorded")}
                    for row in sources
                    if re.fullmatch(r"S[1-9]\d*", row[0])},
    }


def context_documents(private, *, override=None, through=None):
    documents = {}
    paths = dict(private_files(private, {"context"}))
    if override:
        relative = Path(override[0])
        paths[relative] = private / relative
    for relative, path in paths.items():
        try:
            doc = read_document(relative, path, through=through,
                                text=override[1] if override and relative.as_posix() == override[0] else None)
        except (FileNotFoundError, PermissionError):
            continue
        if doc:
            documents[doc["record"]] = doc
    inherit_products(documents)
    return documents


def inherit_products(documents):
    for doc in documents.values():
        if doc["initiative"] and not doc["product"] and doc["parent"] in documents:
            doc["product"] = documents[doc["parent"]]["product"]


def resolved_artifact(name, documents):
    if name in documents:
        doc = documents[name]
        if doc["company"]:
            return {"company": True, "product": None, "area": None, "initiative": None}
        return {key: doc[key] for key in ("product", "area", "initiative")}
    parts = Path(name).parts
    products = {doc["product"] for doc in documents.values() if doc["product"]}
    if len(parts) >= 3 and parts[0] == "workspace":
        product = parts[2] if len(parts) >= 4 else Path(parts[2]).stem
        if product in products:
            initiative = parts[3] if len(parts) >= 5 and parts[1] in {"initiatives", "experiments"} else None
            return {"product": product, "initiative": initiative, "area": None}
    return {}


def mentions(prompt, name):
    phrase = r"[\s-]+".join(re.escape(part) for part in re.split(r"[\s-]+", name.strip()))
    return bool(phrase and re.search(r"(?<!\w)" + phrase + r"(?!\w)", prompt, re.I))


def routing_metadata(doc):
    aliases, providers = set(), set()
    for row in doc["sources"].values():
        label, separator, target = row["Source"].partition("](")
        label_words = words(label)
        aliases.update(label_words)
        if separator and target.startswith(("https://", "http://")):
            try:
                labels = (urlsplit(target[:-1]).hostname or "").split(".")
            except ValueError:
                continue
            if len(labels) > 1 and labels[-1] not in {"test", "example", "invalid", "localhost"}:
                provider = labels[-3] if len(labels) >= 3 and labels[-2] in {"co", "com", "org"} else labels[-2]
                providers.update(words(provider) & label_words)
    controls, _ = records.table(doc["text"], "Context controls", ("Field", "Value"))
    leads = {}
    for heading, _, start, end in records.section_blocks(doc["text"]):
        lead, _ = records.split_context_lead(doc["text"][start:end])
        if lead and records.valid_context_lead(lead):
            leads[heading] = lead
    visible = SUPERSEDED.sub("", records.visible_section_markup(doc["text"]))
    reviewable = ("Decisions already closed" in visible or "- Rule:" in visible
                  or bool(evidence_reviews.RISK_LANGUAGE.search(visible) or evidence_reviews.GATE.search(visible)))
    return {"reviewable": reviewable, "journal": evidence_reviews.HEADING in doc["text"], "leads": leads, "due": dict(controls).get("Review by", ""), **{k: v for k, v in doc.items() if k not in {"sources", "text"}},
            "identifiers": sorted(set(IDENTIFIER.findall(records.visible_section_markup(doc["text"]).casefold()))),
            "providers": sorted(providers), "aliases": sorted(aliases), "areas": AREA.findall(doc["text"]),
            "id": records.work_state(doc["text"])[0].get("ID")}


def scope_inventory(private, index, through):
    docs, loaded, stamps = {}, {}, {}
    # A journal in another product can explicitly target this initiative.
    for relative, path in private_files(private, {"context"}):
        name = relative.as_posix()
        try:
            stamp = context_index.signature(path)
            hit, meta = index.metadata(name, stamp)
            if not hit:
                doc = read_document(relative, path, through=through)
                meta = routing_metadata(doc) if doc else None
                if stamp != context_index.signature(path):
                    raise InventoryChanged()
                index.store(name, stamp, meta)
                if doc:
                    loaded[name] = doc
            if meta:
                docs[name], stamps[name] = meta, stamp
        except (FileNotFoundError, PermissionError):
            continue
    index.prune()
    inherit_products(docs)
    return docs, loaded, stamps


class InventoryChanged(Exception):
    pass


def source_matches(scoped, prompt, terms):
    identifiers = set(IDENTIFIER.findall(prompt.casefold()))
    aliases = set()
    direct = False
    for doc in scoped:
        direct |= bool(identifiers.intersection(doc["identifiers"]) or terms.intersection(doc["providers"]))
        aliases.update(doc["aliases"])
    return direct, len(terms & aliases)


def choose_scope(private, documents, prompt, cwd, previous, explicit):
    overview = {doc["product"]: doc for doc in documents.values() if doc["kind"] == "product-context"}
    if explicit:
        return explicit, []
    if conversation.acknowledgement(prompt):
        return {}, []
    switched = bool(SWITCH.match(prompt))
    prompt = SWITCH.sub("", prompt)
    artifacts = re.findall(r"(?:private/)?((?:context|workspace)/[\w./-]+?\.(?:md|json))\b", prompt)
    known = [scope for name in artifacts if (name.endswith(".md") or layout.initiative_work_identity(name))
             and (scope := resolved_artifact(name, documents))]
    for value in re.findall(r"\bproduct/([a-z0-9-]+)(?:/area/([a-z0-9-]+))?", prompt):
        known.append({"product": value[0], "area": value[1] or None, "initiative": None})
    for product, doc in overview.items():
        identifier = doc["id"]
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

    if COMPANY_QUERY.search(prompt):
        return {"company": True}, []

    terms = words(prompt)
    named = sorted(product for product, doc in overview.items()
                   if mentions(prompt, product) or mentions(prompt, doc["title"]))
    if len(named) == 1:
        return inferred_scope(documents, named[0], terms), []
    if named:
        return {}, named
    if previous and not switched and FOLLOW_UP.match(prompt.strip()):
        if previous.get("company") or previous.get("product") in overview:
            return previous, []
    if not switched and cwd and cwd != private and private in cwd.parents:
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
    areas.update(area for doc in candidates for area in doc["areas"])
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
    kind = doc["kind"]
    standard = records.context_sections(kind)
    content_sections = records.context_content(kind, text)
    for section, _, start, end in records.section_blocks(text):
        if section not in content_sections:
            continue
        lead, body = records.split_context_lead(text[start:end])
        if lead is not None and not records.valid_context_lead(lead):
            continue
        visible = records.visible_section_markup(body)
        table = section in records.CONTEXT_TABLES
        pattern = r"^\| [^\n]*" if table else rf"^({records.CONTEXT_ENTRY.pattern})(?:\n {{2,}}\S[^\n]*)*"
        for match in re.finditer(pattern, visible, re.M):
            value = match[0]
            row = AREA.search(body[match.start():match.start() + len(value.splitlines()[0])])
            if row and row[1] not in areas:
                continue
            refs = records.SOURCE_REFERENCE.findall(SUPERSEDED.sub("", value))
            sources = [doc["sources"][ref[1:-1]] for ref in dict.fromkeys(refs) if ref[1:-1] in doc["sources"]]
            requires_source = section == "Decisions already closed" or value.startswith(
                ("- Fact:", "- Rule:", "- Example:", "- Reported metric:"))
            if requires_source and (not sources or len(sources) != len(set(refs))):
                continue
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
            content = SUPERSEDED.sub("", value).strip()
            binding = bool(sources) and (section == "Decisions already closed" or (
                (section in KEEP or (lead is not None and section not in standard)) and value.startswith("- Rule:")
            ))
            if section == "Decisions already closed":
                decision_date = re.search(r", (\d{4}-\d{2}-\d{2})\s*\|", content)
                if decision_date and decision_date[1] > through.isoformat():
                    continue
            yield {"record": doc["record"], "section": section, "text": content, "sources": sources,
                   "binding": binding}


def live_document(private, name, loaded, stamps, through):
    if not stamps:
        return loaded[name]
    path = private / name
    try:
        if path.resolve() != path or context_index.signature(path) != stamps[name]:
            raise InventoryChanged()
        doc = loaded.get(name)
        if doc is None:
            doc = read_document(Path(name), path, through=through)
            if doc is None or context_index.signature(path) != stamps[name]:
                raise InventoryChanged()
            loaded[name] = doc
        return doc
    except (FileNotFoundError, PermissionError):
        raise InventoryChanged() from None


def resolve(private, prompt="", *, cwd=None, previous=None, explicit=None, explain=False, include_history=False):
    result, _ = resolve_inventory(private, prompt, cwd=cwd, previous=previous, explicit=explicit,
                                  explain=explain, include_history=include_history)
    return result


def resolve_inventory(private, prompt, *, cwd, previous, explicit, explain, include_history,
                      work_record=None, new_owner=None):
    through = as_of(prompt)

    def collect(index, docs, loaded, stamps):
        scope = explicit
        location, prior = cwd, previous
        if new_owner and not resolved_artifact(new_owner, docs):
            # A standalone owner gives neither scoped evidence nor permission to inherit another product.
            location, prior = None, None
        if work_record:
            record_scope = resolved_artifact(work_record, docs)
            if scope and not scope_contains(record_scope, scope):
                raise ValueError("Choose a work record in the current scope")
            scope = scope or record_scope or None
        result = resolve_current(private, prompt, location, prior, scope, explain, include_history, through,
                                 index, docs, loaded, stamps)
        return result, docs

    with context_index.opened(private) as index:
        try:
            docs, loaded, stamps = scope_inventory(private, index, through)
            return collect(index, docs, loaded, stamps)
        except InventoryChanged:
            # Routing metadata changed during retrieval. Recover from current source bytes.
            loaded = context_documents(private, through=through)
            docs = {name: routing_metadata(doc) for name, doc in loaded.items()}
            return collect(context_index.Index(), docs, loaded, {})


def resolve_current(private, prompt, cwd, previous, explicit, explain, include_history, through,
                    index, docs, loaded, stamps):
    scope, choices = choose_scope(private, docs, prompt, cwd, previous, explicit)

    def live(name):
        doc = live_document(private, name, loaded, stamps, through)
        doc["product"] = docs[name]["product"]
        return doc

    risk_ids = set(re.findall(r"\brisk-[0-9a-f]{20}\b", prompt))
    journals = (live(name) for name, meta in docs.items() if meta["journal"])
    saved_reviews = evidence_reviews.stored(journals, through.isoformat())
    if not scope and not explicit and len(risk_ids) == 1:
        requested = next(iter(risk_ids))
        review = saved_reviews.get(requested)
        if review is None:
            peers = (live(name) for name, meta in docs.items() if meta["reviewable"])
            candidates = evidence_reviews.pair_candidates(evidence_reviews.observations(peers, through))
            review = next((candidate for candidate in candidates if candidate["id"] == requested), None)
        if review:
            scope = review["scope"] if review["scope"].get("product") else {"company": True}
            choices = []
    status = "ambiguous" if choices else "resolved" if scope else "unscoped"
    result = {"status": status, "scope": scope, "choices": choices, "entries": [], "warnings": []}
    metrics = metric_registry.effective(private.parent, private, scope.get("product"), through.isoformat())
    if not scope:
        if explain:
            result["retrieval"] = {"mode": status, "eligible": 0}
        selected_metrics = metric_registry.matching(metrics, prompt)
        if selected_metrics:
            result["metrics"] = selected_metrics
        return result
    product, area, initiative = (scope.get(key) for key in ("product", "area", "initiative"))
    areas = {area} if area else set()
    signed_reviews = []
    if product and (private / layout.initiative_register(product)).is_file():
        import initiative_store
        try:
            _, _, register = initiative_store.read(private.parent, product)
            import initiative_views
            for item in register.items.values():
                item_slug = item["id"].split("/", 1)[1]
                if initiative and item_slug != initiative:
                    continue
                item_areas = {s.rsplit("/", 1)[-1] for s in item["areas"]}
                if area and area not in item_areas:
                    continue
                if initiative:
                    areas.update(item_areas)
                if through >= date.today():
                    signed_reviews.extend({**r, "initiative": item["id"]} for r in initiative_views.signal_reviews(private, item))
                elif item.get("_signal_reviews"):
                    result["warnings"].append(f"{item['id']}: verify the signed evidence history for the requested date.")
        except (OSError, ValueError) as exc:
            result["warnings"].append(f"Could not verify the registered initiative scope: {exc}")
    overview = docs.get(layout.product(product)) if product else None
    company = (overview["parent"] or layout.COMPANY) if overview else layout.COMPANY if scope.get("company") else None
    if product and not overview:
        result["warnings"].append(f"Missing product context for {product}.")
    if company and company not in docs:
        result["warnings"].append(f"Missing inherited context at {company}.")
    terms = words(prompt)
    rows, base, due_dates = [], set(), {}
    labels, cached_notes = {}, {}
    view = json.dumps([through.isoformat(), sorted(areas)])
    review_documents = []
    for name, meta in docs.items():
        if not evidence_reviews.in_scope(meta, scope, areas, company):
            continue
        if meta["reviewable"]:
            review_documents.append(live(name))
        if meta["kind"] != "context-note" or name in prompt or mentions(prompt, meta["title"]):
            base.add(name)
        elif not terms:
            continue
        due_dates[name] = meta["due"]
        optional_note = name not in base
        candidates = index.projection(name, view) if optional_note and name not in loaded else None
        if candidates is None:
            doc = live(name)
            candidates = list(linked_entries(doc, areas, through))
            if optional_note:
                index.save_projection(name, view, candidates)
        else:
            cached_notes[name] = (len(rows), len(candidates))
        for row in candidates:
            heading = row["section"]
            key = (name, heading)
            if key not in labels:
                labels[key] = " ".join(filter(None, (meta["title"], heading if heading != "Context" else "",
                                                    meta["leads"].get(heading))))
        rows.extend(candidates)

    hits, scores, mode = context_search.rank(prompt, scope, rows, labels, index, tokens, IDENTIFIER)
    admitted = base | {rows[i]["record"] for i in hits}
    if not hits and "?" in prompt and not any(name in prompt for name in base):
        result["evidence_gap"] = "No close passage matched the question. Verify the answer against the scoped records."
    for name in admitted.intersection(cached_notes):
        start, count = cached_notes[name]
        doc = live(name)
        current = list(linked_entries(doc, areas, through))
        projection = [{key: val for key, val in row.items() if key != "sources"} for row in current]
        if projection != rows[start:start + count]:
            index.save_projection(name, view, current)
            raise InventoryChanged()
        rows[start:start + count] = current
    entries = []
    for i, row in enumerate(rows):
        name = row["record"]
        governed = row["binding"] or row["section"] == "Data boundaries"
        if name in base or i in hits or (governed and name in admitted):
            # Preserve inherited constraints ahead of constraints from newly discovered notes.
            priority = (0 if name in base else 1) if governed else 2
            exact, fused, semantic = scores[i]
            order = (priority, row["section"] != "Data boundaries", not row["binding"], name not in prompt,
                     not exact, -fused, -semantic, name)
            entries.append((order, row))
    entries.sort(key=lambda item: item[0])
    entries = [row for _, row in entries]
    if explain:
        result["retrieval"] = {"mode": mode if terms else "navigation", "eligible": len(rows),
                               "ranked_matches": len(hits), "supplemental_records": sorted(admitted - base),
                               "model": "potion-base-8M int8" if mode.startswith("hybrid") else None,
                               "cache_available": index.db is not None}
    for name, due in due_dates.items():
        if name in admitted and re.fullmatch(r"\d{4}-\d{2}-\d{2}", due) and due < date.today().isoformat():
            result["warnings"].append(f"Review overdue for {name}. Confirm current authority before relying on it.")
    relevant = evidence_reviews.scoped_reviews(loaded, review_documents, saved_reviews, scope, areas, through,
                                              recall_ids=risk_ids, recall_all=include_history)
    for review in signed_reviews:
        relevant[("signal", review["initiative"], review["id"])] = review
    active = [r for r in relevant.values() if r.get("active", r["state"] in evidence_reviews.OPEN)
              and r["state"] != "routine"]
    if active:
        result["risks"] = [{k: v for k, v in risk.items() if k != "history"} for risk in active]
        result["warnings"].extend(f"{r['id']} ({r['state']}): {r['reason']}" for r in active)
        contested = {}
        for risk in active:
            for claim in risk["claims"]:
                contested.setdefault((claim.get("record"), claim.get("text")), []).append(risk["id"])
        for row in entries:
            if (key := (row["record"], row["text"])) in contested:
                row["risk_reviews"] = contested[key]
    resolved = [r for r in relevant.values() if r.get("disposition") and r["state"] in {"dismiss", "resolve"}]
    if resolved:
        result["risk_dispositions"] = [r["disposition"] for r in resolved]
    if include_history or risk_ids:
        result["risk_history"] = [r for k, r in relevant.items() if include_history or k in risk_ids]
    decisions = Counter((row["record"], *row["text"].split("|")[1:3]) for row in entries
                        if row["section"] == "Decisions already closed" and row["binding"])
    for (record, *_), count in decisions.items():
        if count > 1:
            result["warnings"].append(f"Resolve repeated active decisions in {record} before relying on their outcome.")
    budget = 6500 - len("[]")
    for row in entries:
        size = len(json.dumps(row, ensure_ascii=False)) + (2 if result["entries"] else 0)
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
        result.pop("evidence_gap", None)
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
    if path:
        try:
            if time.time() - path.stat().st_mtime < 86400:
                state = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(state, dict):
                    return state
        except (OSError, ValueError):
            pass
    return {}


def same_scope(first, second):
    if not first or not second:
        return not first and not second
    return conversation.scope_key(first) == conversation.scope_key(second)


def scope_contains(record_scope, scope):
    return all(value is None or scope.get(key) == value for key, value in record_scope.items())


def turn_context(private, prompt, *, cwd=None, saved=None, explicit=None, work_record=None, include_history=False, explain=False):
    """Resolve the current task separately from the turn's resumable work pointer."""
    previous = saved or {}
    prior_scope = previous.get("scope", {})
    if prior_scope:
        try:
            conversation.scope_key(prior_scope)
        except (TypeError, ValueError):
            prior_scope = {}
    can_continue = previous.get("can_continue", True)
    named = WORK_RECORD.search(prompt) if work_record is None else None
    selected_owner = work_record or (named[1] if named else None)
    selected_new_owner = selected_owner is not None and selected_owner != previous.get("record")
    checkpoint = conversation.read_checkpoint(private, work_record) if work_record is not None else None
    result, docs = resolve_inventory(private, prompt, cwd=cwd, explicit=explicit, explain=explain,
                                     previous=prior_scope if can_continue else None, include_history=include_history,
                                     work_record=work_record, new_owner=selected_owner if selected_new_owner else None)
    if selected_new_owner and not resolved_artifact(selected_owner, docs):
        prior_scope = {}
    scope = result["scope"]
    switched = bool(SWITCH.match(prompt))
    neutral = conversation.acknowledgement(prompt)
    follows = bool(FOLLOW_UP.match(prompt.strip()))
    same_work = same_scope(scope, prior_scope)
    if scope:
        active = scope
        can_continue = True
    else:
        active = prior_scope
        can_continue = (can_continue and not result["choices"] and not switched
                        and (follows or conversation.continues_work(prompt)))
        same_work = can_continue

    if work_record is None and not switched:
        candidate = selected_owner or (previous.get("record") if same_work else None)
        if candidate:
            candidate_scope = resolved_artifact(candidate, docs)
            can_read = (scope_contains(candidate_scope, scope) if scope else
                        bool(named and follows and not result["choices"] and not candidate_scope))
            if can_read:
                try:
                    checkpoint = conversation.read_checkpoint(private, candidate)
                except (OSError, ValueError):
                    # A routine read can name Markdown without selecting a checkpoint.
                    pass
    if checkpoint and scope and not scope_contains(resolved_artifact(checkpoint["record"], docs), scope):
        raise ValueError("Choose a work record in the current scope")
    if checkpoint and not result["choices"] and not switched:
        can_continue = True

    retains_mode = same_work and not selected_new_owner and not switched
    mode_override = conversation.requested_mode(prompt)
    if mode_override is None and retains_mode:
        mode_override = previous.get("mode")
    work_mode = previous.get("work_mode") if retains_mode else None
    if checkpoint:
        work_mode = checkpoint["work_state"]["Mode"]
    mode = mode_override or work_mode or "thought-partner"
    turn = {"mode": mode}
    try:
        turn["reply_preferences"] = preferences.effective(preferences.load(private))
    except (OSError, ValueError):
        turn["reply_preferences"] = preferences.effective({})
    if neutral:
        turn["acknowledgment"] = True
    if switched and not scope:
        turn["unresolved_switch"] = True
    if checkpoint:
        deferrals = [row for row in checkpoint["deferrals"] if scope and same_scope(row["scope"], scope)]
        turn["checkpoint"] = {**checkpoint, "deferrals": deferrals}
    else:
        deferrals = []
    if not checkpoint and can_continue and active and not scope and not neutral:
        turn["scope_to_confirm"] = active
    if not neutral and scope:
        offer = conversation.context_offer(prompt, result, deferrals, mode == "quiet")
        if offer is not None:
            turn["suggestion"] = offer
    result["conversation"] = turn
    record = previous.get("record") if same_work and not scope and not selected_new_owner else None
    if checkpoint:
        record = checkpoint["record"]
    return result, {"scope": active, "can_continue": can_continue, "record": record,
                    "mode": mode_override, "work_mode": work_mode, "binding": [
                        {"record": row["record"], "section": row["section"]}
                        for row in result["entries"] if row["binding"]
                    ], "warnings": result["warnings"]}


def remember_scope(private, session, state):
    path = session_state(private, session)
    if path:
        with storage.writer_lock(private):
            original = path.read_text(encoding="utf-8") if path.is_file() else None
            storage.replace_text(path, original, json.dumps(state), mode=0o600)
