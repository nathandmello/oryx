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
import outcome_context
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
                       r"update (?:it|that|this)\b|make (?:it|that|this)\b|what about\b|"
                       r"(?:did|has) (?:it|that|this) (?:improve[d]?|get(?:ten)? better)[?!.]?$)", re.I)
SWITCH = re.compile(
    r"^(?:(?:please|now|let's|let’s)\s+)*(?:switch|move)\s+(?:from\b.+?\b)?to\s+", re.I
)
WORK_RECORD = re.compile(r"(?:(?:studio|private|workspace)/)?(workspace/[\w./-]+?\.md)\b")
# Personal methods can contain examples with the same names as real PM records.
CUSTOMIZATION_PATH = re.compile(
    r"""(["'`])(?:(?:/[^"'\x60\n]*/)?(?:studio|private|workspace)/)?customizations/[^"'\x60\n]+\1"""
    r"|<(?:(?:/[^<>\n]*/)?(?:studio|private|workspace)/)?customizations/[^<>\n]+>"
    r"|(?:(?<![\w.-])(?:studio|private|workspace)/|(?<![\w./-]))customizations/[\w./%+-]+", re.I)
STAKEHOLDER_QUERY = re.compile(
    r"\bstakeholder (?:map|context)\b|\b(?:list|show|map|who are) (?:me )?(?:the |my |our )?stakeholders\b|"
    r"\breporting (?:lines?|relationships?|structure)\b|"
    r"\bwho (?:do|does) [^?.!]{1,60} report to\b|"
    r"\b(?:who|which (?:person|team|role)) (?:can |typically |usually |currently )?"
    r"(?:approves?|decides?|recommends?|advises?|owns?|signs? off|has (?:the )?final say|"
    r"is (?:the (?:approver|decision maker)|responsible for|accountable for))\b", re.I)
COMPANY_QUERY = re.compile(r"\bcompany(?:-wide| context| overview| policy)\b", re.I)
# In a company-only Studio, a standalone question about the business model has
# an identifiable subject. A named organisation or comparison needs clarification.
COMPANY_BUSINESS_QUESTION = re.compile(
    r"(?:how|where|when|why|who|what) (?:does|did|can|will) the (?:company|business) "
    r"(?:earn|make|generate|moneti[sz]e|charge|sell|serve|deliver|create|grow|compete|operate|distribute|fund)"
    r"\b[^.!?]*[?]?", re.I)
OTHER_BUSINESS = re.compile(r"\b(?:versus|vs|compar\w*|other|another|competitor[s]?|rival[s]?)\b", re.I)
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
        "area": entity.name if layout.area_identity(relative) else None,
        "initiative": initiative, "parent": parent, "text": text, "company": entity == Path(layout.COMPANY).parent,
        "sources": {row[0]: {**dict(zip(records.SOURCE_COLUMNS, row)), "coverage": coverage.get(row[0], "unrecorded")}
                    for row in sources
                    if re.fullmatch(r"S[1-9]\d*", row[0]) and not records.uses_customization_source(name, row[1])},
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
    for name, doc in list(documents.items()):
        if doc["initiative"] and not doc["product"] and doc["parent"] in documents:
            doc["product"] = documents[doc["parent"]]["product"]
        if doc["area"] and doc["kind"] != "product-area-context":
            overview = (layout.entity(name) / "overview.md").as_posix()
            if documents.get(overview, {}).get("kind") != "product-area-context":
                del documents[name]


def resolved_artifact(name, documents):
    if name in documents:
        if layout.stakeholder_record(name):
            return {"stakeholders": True}
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


CONTEXT_SUBJECT = re.compile(
    r"^(?:(?:please|help (?:me|us)|let['’]s)\s+)*(?:think through|work on|draft|review|show|assess|evaluate)"
    r"\s+(?:(?:me|the|our|a|product)\s+)*(?:strategy|context|outcomes?|performance|results?) (?:for|of) "
    r"(?:the |our )?([^?.!]+)[?.!]*$", re.I)


def activity_subjects(documents, prompt):
    """A name in a claim or an example need not be the subject of the PM's request."""
    match = CONTEXT_SUBJECT.match(prompt.strip())
    subject = match[1] if match else outcome_context.subject(prompt)
    if not subject:
        return []
    phrase = " ".join(subject.casefold().replace("-", " ").split())
    matches, pilot_scopes = set(), set()
    for doc in documents.values():
        product = doc["product"]
        if not product:
            continue
        # Older briefs identify areas in individual entries rather than in dedicated records.
        subjects = [(a, None, a) for a in doc["areas"]]
        if doc["kind"] in {"product-context", "product-area-context", "initiative-context"}:
            subjects.extend((doc["area"], doc["initiative"], label)
                            for label in (doc["title"], doc["area"] or doc["initiative"] or product))
        for area, initiative, label in subjects:
            name = label.casefold().replace("-", " ")
            labels = (name, product.replace("-", " ") + " " + name)
            identity = (product, area or "", initiative or "")
            if phrase in labels:
                matches.add(identity)
            elif not initiative and phrase.endswith(" pilot") and phrase[:-6] in labels:
                # Search this subject for the pilot cohort; an actual pilot record takes precedence.
                pilot_scopes.add(identity)
    return sorted(matches or pilot_scopes)


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


def choose_scope(private, documents, prompt, cwd, previous, explicit, relationships):
    overview = {doc["product"]: doc for doc in documents.values() if doc["kind"] == "product-context"}
    switched = bool(SWITCH.match(prompt))
    followup = not switched and FOLLOW_UP.match(prompt.strip())
    relationship = STAKEHOLDER_QUERY.search(prompt) or (previous and previous.get("stakeholders") and followup)

    def with_relationship(scope):
        return {**scope, "stakeholders": True} if relationship and scope.get("product") else scope

    if explicit:
        return with_relationship(explicit), []
    if conversation.acknowledgement(prompt):
        return {}, []
    prompt = SWITCH.sub("", prompt)
    artifacts = re.findall(r"(?:(?:studio|private|workspace)/)?((?:context|workspace)/[\w./-]+?\.(?:md|json))\b", prompt)
    known = [scope for name in artifacts if (name.endswith(".md") or layout.initiative_work_identity(name))
             and (scope := resolved_artifact(name, documents))]
    for value in re.findall(r"\bproduct/([a-z0-9-]+)(?:/area/([a-z0-9-]+))?", prompt):
        known.append({"product": value[0], "area": value[1] or None, "initiative": None})
    for product, doc in overview.items():
        identifier = doc["id"]
        if identifier and (match := re.search(r"\b" + re.escape(identifier) + r"/([a-z0-9-]+)\b", prompt)):
            known.append({"product": product, "area": None, "initiative": match[1]})
    if any(item.get("stakeholders") for item in known):
        others = [item for item in known if not item.get("stakeholders")]
        if others:
            return {}, sorted({"stakeholders", *(item.get("product") or "company" for item in others)})
        return {"stakeholders": True}, []
    if known:
        products = sorted({item["product"] for item in known if item["product"]})
        scopes = {(item["product"], item["area"], item["initiative"]) for item in known}
        if len(scopes) > 1:
            specific = [item for item in known if item["area"] or item["initiative"]]
            if len(products) > 1 or len({(item["area"], item["initiative"]) for item in specific}) > 1:
                return {}, sorted({"/".join(value for value in scope if value) or "company" for scope in scopes})
            return with_relationship((specific or known)[0]), []
        return with_relationship(known[0]), []

    if not relationship and COMPANY_QUERY.search(prompt):
        return {"company": True}, []

    terms = words(prompt)
    named = sorted(product for product, doc in overview.items()
                   if mentions(prompt, product) or mentions(prompt, doc["title"]))
    if len(named) == 1:
        # A consumer's own, reviewed statement can identify the requested shared area.
        product = named[0]
        links = relationships(product)
        mentioned = {subject.rsplit("/", 1)[1] for subject in links if mentions(prompt, subject.rsplit("/", 1)[1])}
        if links:
            for meta in documents.values():
                if (meta["kind"] == "product-area-context" and f"product/{meta['product']}/area/{meta['area']}" in links
                        and words(meta["title"]) - {"context", "overview"} and mentions(prompt, meta["title"])):
                    mentioned.add(meta["area"])
        if len(mentioned) == 1:
            return with_relationship({"product": product, "area": next(iter(mentioned)), "initiative": None}), []
        if mentioned:
            return {}, sorted(subject for subject in relationships(product) if subject.rsplit("/", 1)[1] in mentioned)
    subjects = activity_subjects(documents, prompt)
    if subjects:
        # A named parent disambiguates homonymous children. A product of the same name remains a candidate.
        if len(named) == 1:
            parent = named[0]
            qualifier = re.search(r"\b(?:in|within|under|on)\s+([^?.!,]+)[?.!]*$", prompt.strip(), re.I)
            if qualifier and qualifier[1].casefold() in {parent.replace("-", " "), overview[parent]["title"].casefold()}:
                qualified = [choice for choice in subjects if choice[0] == parent]
                subjects = qualified or subjects
        if len(subjects) == 1 and set(named) <= {subjects[0][0]}:
            product, area, initiative = subjects[0]
            return with_relationship({"product": product, "area": area or None, "initiative": initiative or None}), []
        choices = {f"product/{p}/area/{a}" if a else f"{p}/{i}" if i else p for p, a, i in subjects}
        return {}, sorted(choices | (set(named) - {p for p, _, _ in subjects}))
    if len(named) == 1:
        return with_relationship(inferred_scope(documents, named[0], terms)), []
    if named:
        return {}, named
    if relationship:
        if followup and previous and previous.get("product") in overview:
            return with_relationship(previous), []
        return {"stakeholders": True}, []
    if re.search(r"\bour (?:company|business)\b", prompt, re.I):
        return {"company": True}, []
    if previous and followup:
        if previous.get("stakeholders") or previous.get("company") or previous.get("product") in overview:
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
    if (not overview and layout.COMPANY in documents and COMPANY_BUSINESS_QUESTION.fullmatch(prompt.strip())
            and not OTHER_BUSINESS.search(prompt)
            and not re.search(r"\b[A-Z]\w*", prompt.strip().partition(" ")[2])):
        return {"company": True}, []
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
                   "binding": binding, **({"product_area": row[1]} if row else {})}


SHARED_AREA = re.compile(rf"^  Shared area: (product/{layout.SLUG.pattern}/area/{layout.SLUG.pattern})$", re.M)


def sources_checked(row, through):
    return bool(row["sources"]) and all(
        source.get("coverage") in {"read", "partial"}
        and re.fullmatch(r"\d{4}-\d{2}-\d{2}", source["Checked on"])
        and source["Checked on"] <= through.isoformat() for source in row["sources"])


def shared_row_reviews(row, reviews):
    """Identify an active qualification without importing other products' review material."""
    for review in reviews.values():
        if review["state"] not in evidence_reviews.OPEN:
            continue
        unreadable = review["classification"] == "unreadable history" and review["owner"] == row["record"]
        if unreadable or any(claim.get("record") == row["record"] and claim.get("section") == row["section"]
                             and claim.get("text") and claim["text"] in row["text"] for claim in review["claims"]):
            yield review["id"]


def shared_area_links(doc, through):
    """A current sourced fact in the consumer's overview is the authority for following a link."""
    if not doc or doc["kind"] != "product-context" or doc["record"] != layout.product(doc["product"]):
        return {}
    links = {}
    if "  Shared area: " not in doc["text"]:
        return links
    for row in linked_entries(doc, set(), through):
        matches = SHARED_AREA.findall(row["text"])
        if len(matches) != 1 or not row["text"].startswith("- Fact:") or evidence_status(row) != "source statement":
            continue
        if not sources_checked(row, through):
            continue
        subject = matches[0]
        if subject.split("/")[1] != doc["product"]:
            links[subject] = row
    return links


def question_key(row, label):
    for line in row["text"].splitlines():
        if line.startswith(label):
            return row["record"], row["section"], line[len(label):].strip()
    return None


def evidence_status(row):
    """Keep authority and unresolved qualifications explicit in the agent's task context."""
    text = row["text"]
    if row.get("risk_reviews"):
        return "under review"
    if "\n  Open question at capture:" in text:
        return "unresolved"
    if row["section"] == "Decisions already closed":
        return "recorded decision"
    if text.startswith("- Unknown:"):
        return "open question"
    if text.startswith("- Interpretation:"):
        return "interpretation"
    if text.startswith("- Assumption:"):
        return "assumption to verify"
    if text.startswith("- Reported metric:"):
        return "reported metric"
    if not row["sources"]:
        return "unverified record"
    return "sourced rule" if row["binding"] else "source statement"


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
    prompt = CUSTOMIZATION_PATH.sub(" ", prompt)
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
        if result["status"] != "ambiguous" and conversation.strategy_activity(prompt, result["scope"].get("product")):
            result["activity_check"] = conversation.strategy_prerequisite(result)
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


def relevant_company_questions(private, prompt):
    """Retrieve present uncertainties as context. Follow-up timing belongs to the coaching hook."""
    import company_onboarding

    if not (private / company_onboarding.FILE).exists():
        return []
    # Checkpoints contain current gaps and carry no historical validity interval.
    if re.search(r"\b(as of|at the time|previously|historical(?:ly)?|last (?:week|month|quarter|year)|in (?:19|20)\d{2})\b",
                 prompt, re.I):
        return []
    terms = words(prompt) - {"company", "business", "does", "will", "did", "know", "would", "has",
                             "question", "their", "about", "there", "find", "understand"}
    if not terms:
        return []
    _, state = company_onboarding.read(private)
    ranked = []
    for gap in state["gaps"]:
        subject = terms.intersection(words(gap["question"]))
        reason = terms.intersection(words(gap["why"]))
        if subject or len(reason) >= 2:
            # An exact topical match to the question outranks a match to its rationale.
            ranked.append(((len(subject), len(reason)), gap))
    ranked.sort(key=lambda pair: pair[0], reverse=True)
    remaining, results = 1800, []
    for _, gap in ranked:
        row = {field: gap[field] for field in ("question", "why", "resume_when")}
        size = len(json.dumps(row, ensure_ascii=False))
        if size <= remaining:
            results.append(row)
            remaining -= size
            if len(results) == 3:
                break
    return results


def resolve_current(private, prompt, cwd, previous, explicit, explain, include_history, through,
                    index, docs, loaded, stamps):
    def live(name):
        doc = live_document(private, name, loaded, stamps, through)
        doc["product"] = docs[name]["product"]
        return doc

    relationships_by_product = {}
    def relationships(product):
        if product not in relationships_by_product:
            parent = layout.product(product)
            relationships_by_product[product] = shared_area_links(live(parent), through) if parent in docs else {}
        return relationships_by_product[product]

    scope, choices = choose_scope(private, docs, prompt, cwd, previous, explicit, relationships)
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
            if layout.stakeholder_record(review["owner"]):
                scope = {"stakeholders": True}
            choices = []
    status = "ambiguous" if choices else "resolved" if scope else "unscoped"
    result = {"status": status, "scope": scope, "choices": choices, "entries": [], "warnings": []}
    shared = None
    if scope.get("area"):
        product, area = scope["product"], scope["area"]
        try:
            local = records.area_brief_path(product, area, private=private)
            links = {subject: row for subject, row in relationships(product).items() if subject.endswith("/area/" + area)}
            if links:
                choices = set(links)
                if local in docs or any(doc["product"] == product and area in doc["areas"] for doc in docs.values()):
                    choices.add(f"product/{product}/area/{area}")
                if len(choices) != 1:
                    result.update(status="ambiguous", scope={}, choices=sorted(choices),
                                  warnings=["Confirm which area and product the PM means before using the evidence."])
                    return result
                subject, relation = next(iter(links.items()))
                if review_id := next(shared_row_reviews(relation, saved_reviews), None):
                    raise ValueError(f"Confirm the relationship to {subject}: {review_id} remains open.")
                owner = subject.split("/")[1]
                shared = records.area_brief_path(owner, area, private=private)
                parent = layout.product(owner)
                if (shared not in docs or docs[shared]["kind"] != "product-area-context"
                        or parent not in docs or docs[shared]["parent"] != parent):
                    raise ValueError(f"The cited relationship points to {subject}, but its reviewed brief is unavailable.")
                result["shared_area"] = {"subject": subject, "area_brief": shared, "relationship": relation}
        except ValueError as exc:
            result.update(status="ambiguous", scope={}, warnings=[str(exc)])
            return result
    metrics = metric_registry.effective(private.parent, private, scope.get("product"), through.isoformat())
    for key in sorted(metric_registry.qualified_ids(prompt) - metrics.keys()):
        result["warnings"].append(f"No approved definition of {key} exists for this scope on {through.isoformat()}.")
    if not scope:
        if explain:
            result["retrieval"] = {"mode": status, "eligible": 0}
        selected_metrics = metric_registry.matching(metrics, prompt)
        if selected_metrics:
            result["metrics"] = selected_metrics
        return result
    if scope.get("company") and through == date.today():
        try:
            gaps = relevant_company_questions(private, prompt)
        except (OSError, ValueError):
            result["warnings"].append("Company onboarding questions could not be checked. Review the saved checkpoint.")
        else:
            if gaps:
                result["unresolved_company_questions"] = gaps
    product, area, initiative = (scope.get(key) for key in ("product", "area", "initiative"))
    areas = {area} if area else set()
    shape_strategy = bool(product and conversation.strategy_activity(prompt, product))
    assessment = outcome_context.assessment_request(prompt) if product and not scope.get("stakeholders") else None
    lookup = None
    signed_reviews, targets = [], []
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
                    if assessment and initiative:
                        # Keep signed targets separate from actual observations. The initiative view verifies readings and corrections.
                        lookup = ["initiative", "show", product, item["id"]]
                        targets = outcome_context.target_preview(item, product)
                    signed_reviews.extend({**r, "initiative": item["id"]} for r in initiative_views.signal_reviews(private, item))
                elif item.get("_signal_reviews"):
                    result["warnings"].append(f"{item['id']}: verify the signed evidence history for the requested date.")
        except (OSError, ValueError) as exc:
            result["warnings"].append(f"Could not verify the registered initiative scope: {exc}")
    if initiative:
        for inherited_area in sorted(areas):
            try:
                records.area_brief_path(product, inherited_area, private=private)
            except ValueError as exc:
                areas.remove(inherited_area)
                result["warnings"].append(str(exc))
    overview = docs.get(layout.product(product)) if product else None
    company = (overview["parent"] or layout.COMPANY) if overview else layout.COMPANY if scope.get("company") else None
    if scope.get("stakeholders") and layout.STAKEHOLDERS not in docs:
        result["warnings"].append(f"No readable stakeholder map was found at {layout.STAKEHOLDERS}.")
    if product and not overview:
        result["warnings"].append(f"Missing product context for {product}.")
    if company and company not in docs:
        result["warnings"].append(f"Missing inherited context at {company}.")
    terms = words(prompt)
    rows, base, due_dates = [], set(), {}
    labels, cached_notes = {}, {}
    view = json.dumps([through.isoformat(), sorted(areas), "scoped-entries"])
    review_documents = []
    map_product = product if scope.get("stakeholders") else None

    def names_product(text):
        # The source location can name a different product. Use the recorded statement and its heading.
        statement = re.sub(r"\[S[1-9]\d*\][^\n]*", "", text)
        return mentions(statement, map_product) or bool(overview and words(overview["title"]) and mentions(statement, overview["title"]))

    for name, meta in docs.items():
        if name != shared and not evidence_reviews.in_scope(meta, scope, areas, company):
            continue
        if meta["reviewable"]:
            review_documents.append(live(name))
        if meta["kind"] != "context-note" or name in prompt or mentions(prompt, meta["title"]):
            base.add(name)
        elif not terms:
            continue
        due_dates[name] = meta["due"]
        scoped_map = map_product and layout.stakeholder_record(name)
        optional_note = name not in base and not scoped_map
        candidates = index.projection(name, view) if optional_note and name not in loaded else None
        if candidates is None:
            doc = live(name)
            candidates = list(linked_entries(doc, areas, through))
            if name == shared:
                candidates = [row for row in candidates if sources_checked(row, through)]
                for row in candidates:
                    if ids := list(shared_row_reviews(row, saved_reviews)):
                        row["risk_reviews"] = ids
            if scoped_map:
                candidates = [row for row in candidates if names_product(row["text"]) or names_product(row["section"])]
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

    query = prompt
    if shape_strategy:
        query += " Company objective, product contribution and customer problem."
    outcome_subject, criteria = set(), set()
    if assessment:
        outcome_subject = {i for i, row in enumerate(rows) if outcome_context.same_subject(row, docs[row["record"]], scope)}
        criteria = {i for i in outcome_subject if outcome_context.definition(rows[i])}
        # The overview is live on both cold and warm lookups. Its wording helps find measured results in notes.
        clues = [context_search.passage(rows[i]).splitlines()[0][:200] for i in sorted(criteria)
                 if rows[i]["record"] in base and outcome_context.usable_candidate(rows[i])]
        query += " Success measure, cohort, baseline and observed result. " + " ".join(clues[:4])
    hits, scores, mode = context_search.rank(query, scope, rows, labels, index, tokens, IDENTIFIER)
    hits.update(criteria)
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
            if shape_strategy and not governed and (name != layout.COMPANY or row["section"] != "Direction and goals"):
                priority += 1
            if assessment and not governed:
                priority += 0 if i in criteria else 1 if i in outcome_subject else 2
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
    if map_product:
        relevant = {key: review for key, review in relevant.items()
                    if not layout.stakeholder_record(review["owner"]) or
                    all(names_product(claim["text"]) or names_product(claim.get("section", "")) for claim in review["claims"])}
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
    # Keep a historical qualification and its later, dated answer together even
    # when only the qualified passage matched the query in a supporting note.
    answers = {}
    for row in rows:
        if row["record"] not in admitted or not row.get("sources"):
            continue
        key = question_key(row, "  Answers: ")
        if key and all(s["Source date"] not in {"unknown", "undated"} or s["Checked on"] <= through.isoformat()
                       for s in row["sources"]):
            answers.setdefault(key, []).append({"text": row["text"], "sources": row["sources"],
                                               "evidence_status": evidence_status(row)})
    budget = 6500 - len("[]")
    for row in entries:
        row = dict(row, evidence_status=evidence_status(row))
        if row["record"] == shared:
            row["applies_within"] = result["shared_area"]["subject"]
        key = question_key(row, "  Open question at capture: ")
        if key and key in answers:
            row["subsequent_answers"] = answers[key]
            if row["evidence_status"] == "unresolved":
                row["evidence_status"] = "qualified source with subsequent evidence"
        size = len(json.dumps(row, ensure_ascii=False)) + (2 if result["entries"] else 0)
        if size > budget:
            if row["binding"]:
                warning = f"Read the remaining binding entries in {row['record']} before acting."
                if warning not in result["warnings"]:
                    result["warnings"].append(warning)
            continue
        result["entries"].append(row)
        budget -= size
    if assessment:
        candidates = [n for n, row in enumerate(result["entries"], 1)
                      if outcome_context.same_subject(row, docs[row["record"]], scope) and outcome_context.definition(row)
                      and outcome_context.usable_candidate(row)]
        result["activity_check"] = outcome_context.check(candidates, targets, lookup, assessment.groupdict().get("measure"))
    numeric_context = " ".join(row["text"] for row in result["entries"] if row["text"].startswith("- Reported metric:"))
    selected_metrics = metric_registry.matching(metrics, f"{prompt} {numeric_context}")
    if selected_metrics:
        result["metrics"] = selected_metrics
        result.pop("evidence_gap", None)
    profile = private / layout.PROFILE
    if profile.resolve() == profile and profile.is_file() and layout.PROFILE not in upgrades.source_paths(private):
        profile_text = profile.read_text(encoding="utf-8")
        preferences = records.section(profile_text, "Working preferences")
        if scope.get("stakeholders") and (records.section(profile_text, "PM stakeholders") or "").strip():
            result["warnings"].append(f"Review existing stakeholder notes in {layout.PROFILE} with the PM before reusing them.")
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
    mode_override, prompt = conversation.mode_request(prompt)
    prior_scope = previous.get("scope", {})
    if prior_scope:
        try:
            conversation.scope_key(prior_scope)
        except (TypeError, ValueError):
            prior_scope = {}
    can_continue = previous.get("can_continue", True)
    accepted_offer = (previous.get("offered_expedite") is True and mode_override is None
                      and conversation.AFFIRM_PACE.fullmatch(prompt) is not None)
    if accepted_offer:
        mode_override, prompt = "expedite", ""
        if can_continue and prior_scope:
            explicit = explicit or prior_scope
    if mode_override == "expedite" and not prompt and not can_continue:
        # Keep the accepted pace while the PM identifies the new task's product.
        prior_scope = {}
        can_continue = True
    named = WORK_RECORD.search(CUSTOMIZATION_PATH.sub(" ", prompt)) if work_record is None else None
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
                        and (follows or conversation.continues_work(prompt) or (mode_override is not None and not prompt)))
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
    if mode_override is None and retains_mode:
        mode_override = previous.get("mode")
    if (mode_override is None and previous.get("mode") == "expedite" and previous.get("can_continue")
            and not prior_scope and not previous.get("record") and scope and not switched):
        # The PM may choose the pace before identifying the product for this work.
        mode_override = "expedite"
    work_mode = previous.get("work_mode") if retains_mode else None
    if checkpoint:
        work_mode = checkpoint["work_state"]["Mode"]
    mode = mode_override or work_mode or "thought-partner"
    turn = {"mode": mode}
    if accepted_offer:
        turn["accepted_expedite_offer"] = True
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
        offer = conversation.context_offer(prompt, result, deferrals, mode in {"quiet", "expedite"})
        if offer is not None:
            turn["suggestion"] = offer
    if mode not in {"quiet", "expedite"}:
        import company_onboarding
        cue = company_onboarding.followup(private, prompt, company_scope=scope.get("company"))
        if cue:
            turn["company_followup"] = cue
        pm_cue = company_onboarding.followup(private, prompt, company_scope=False, kind="pm")
        if pm_cue:
            turn["pm_followup"] = pm_cue
        subject = f"product/{scope['product']}" if scope.get("product") and not scope.get("stakeholders") else None
        if subject and scope.get("area"):
            subject += f"/area/{scope['area']}"
        if subject or (result["status"] == "unscoped" and company_onboarding.PRODUCT_SETUP.search(prompt)):
            product_cue = company_onboarding.followup(private, prompt, company_scope=False, kind="product",
                                                      subject=subject)
            if product_cue:
                turn["product_followup"] = product_cue
    result["conversation"] = turn
    record = previous.get("record") if same_work and not scope and not selected_new_owner else None
    if checkpoint:
        record = checkpoint["record"]
    return result, {"scope": active, "can_continue": can_continue, "record": record,
                    "mode": mode_override, "work_mode": work_mode, "binding": [
                        {"record": row["record"], "section": row["section"]}
                        for row in result["entries"] if row["binding"]
                    ], "warnings": result["warnings"]}


def remember_scope(private, session, state, *, expected=None):
    path = session_state(private, session)
    if path:
        with storage.writer_lock(private):
            if expected is not None and previous_scope(private, session) != expected:
                return
            original = path.read_text(encoding="utf-8") if path.is_file() else None
            storage.replace_text(path, original, json.dumps(state), mode=0o600)
