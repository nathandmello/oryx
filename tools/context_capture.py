"""Route source excerpts and open questions, then write one selected context brief."""

from datetime import date
from html import escape
import json
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit

import records
import filing
import storage

COMPANY_PATH = "context/company.md"
REMIT_PATH = "context/pm-remit.json"
TOPICS = records.CONTEXT_TOPICS
DEFERRED = {"delivery", "detail", "unclear"}
SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
SUBJECT = re.compile(r"(product|area|topic)/[a-z0-9]+(?:-[a-z0-9]+)*")


def fields(value, required, optional=()):
    required_keys = set(required)
    allowed_keys = required_keys | set(optional)
    if not isinstance(value, dict) or not required_keys <= value.keys() <= allowed_keys:
        raise ValueError(f"Expected fields: {', '.join(required)}; optional: {', '.join(optional) or 'none'}")


def line(value, name):
    if not isinstance(value, str) or not value.strip() or value.splitlines() != [value]:
        raise ValueError(f"{name} needs one nonempty line")
    return value


def iso_day(value, name):
    value = line(value, name)
    try:
        result = date.fromisoformat(value)
    except ValueError:
        raise ValueError(f"{name} needs a YYYY-MM-DD date") from None
    if value != result.isoformat() or result > date.today():
        raise ValueError(f"{name} needs a YYYY-MM-DD date through today")
    return result


def source_rows(inputs):
    if not isinstance(inputs, list):
        raise ValueError("sources must be a list")
    result, seen = [], set()
    for source in inputs:
        fields(source, ("reference", "date", "coverage"), ("checked_on", "text"))
        reference = line(source["reference"], "Source reference")
        if not records.specific(reference) or "|" in reference or records.PLACEHOLDER.search(reference):
            raise ValueError("Use a source reference without table separators or placeholders")
        if reference in seen:
            raise ValueError("List each supplied source once")
        seen.add(reference)
        published = line(source["date"], "Source date")
        if published not in ("unknown", "undated"):
            iso_day(published, "Source date")
        coverage = source["coverage"]
        if coverage not in ("read", "partial", "unavailable"):
            raise ValueError("Source coverage must be read, partial, or unavailable")
        checked = source.get("checked_on")
        if coverage == "unavailable":
            if checked is not None:
                raise ValueError("An unavailable source cannot have a checked_on date")
        else:
            iso_day(checked, "Checked on")
            if published not in ("unknown", "undated") and published > checked:
                raise ValueError("Source date cannot follow Checked on")
        if "text" in source and (coverage == "unavailable" or not isinstance(source["text"], str) or not source["text"].strip()):
            raise ValueError("Supply only source text that was accessible and inspected")
        result.append({key: value for key, value in source.items() if key != "text"})
    return result


COMMITMENT = re.compile(r"\b(?:will|shall|must|never|prohibited|forbidden|excluded|cannot|won['’]t)\b", re.I)


def verify_excerpts(inputs, entries, private):
    """Check literal coverage in inspected text. Qualitative relevance still needs review."""
    reports = []
    for index, source in enumerate(inputs, 1):
        material = source.get("text")
        link = re.fullmatch(r"\[[^\]\n]+\]\((<[^>\n]+>|[^\s)]+)\)", source["reference"])
        if material is None and link and source["coverage"] == "read":
            url = urlsplit(link[1].strip("<>"))
            local = Path(unquote(url.path))
            if (not url.scheme and not url.netloc and not local.is_absolute() and local.parts
                    and local.suffix.lower() in (".md", ".txt") and
                    all(not part.startswith(".") and part != "secrets" for part in local.parts)):
                path = private / local
                if path.resolve() == path and path.is_file():
                    material = path.read_text(encoding="utf-8")
        if material is None:
            reports.append({"source": index, "verification": "unavailable" if source["coverage"] == "unavailable"
                            else "prepared excerpts only"})
            continue
        # Unwrap line-wrapped source paragraphs while preserving their sentence boundaries.
        def normalize(value):
            return " ".join(value.split())
        paragraphs = [normalize(block) for block in re.split(r"\n[ \t]*\n", material)]
        whole = normalize(material)
        excerpts = [normalize(entry["quote"]) for entry in entries if entry.get("source") == index]
        spans = []
        for quote in set(excerpts):
            matches = list(re.finditer(re.escape(quote), whole))
            if not matches:
                raise ValueError(f"Source {index}: excerpt differs from the supplied text; retain its original wording")
            spans.extend(match.span() for match in matches)
        spans.sort()
        statements = []
        offset = 0
        for paragraph in paragraphs:
            for sentence in re.split(r"(?<=[.!?])\s+", paragraph):
                sentence = sentence.lstrip(">#-* ").strip()
                if not sentence:
                    continue
                start = whole.index(sentence, offset)
                end = offset = start + len(sentence)
                if not COMMITMENT.search(sentence):
                    continue
                statements.append(sentence)
                cursor = start
                for left, right in spans:
                    if right <= cursor or left >= end:
                        continue
                    gap = whole[cursor:max(cursor, left)]
                    if cursor > start:
                        gap = re.sub(r"\band\b", "", gap, flags=re.I)
                    if re.search(r"\w", gap):
                        break
                    cursor = min(end, right)
                if re.search(r"\w", whole[cursor:end]):
                    raise ValueError(f"Source {index}: route or explicitly defer the entire commitment: {sentence}")
        reports.append({"source": index, "verification": "supplied text", "commitment_sentences": len(statements)})
    return reports


def product_path(slug):
    if not isinstance(slug, str) or not SLUG.fullmatch(slug):
        raise ValueError("Use an established product slug or route this entry as unclear")
    return f"products/{slug}/context.md"


def initiative_path(product, initiative):
    if not isinstance(initiative, str) or not SLUG.fullmatch(initiative):
        raise ValueError("Use an established initiative slug")
    return f"{Path(product_path(product)).parent.as_posix()}/initiatives/{initiative}/context.md"


def brief_path(path):
    parts = Path(path).parts
    return path == COMPANY_PATH or (
        bool(parts) and parts[0] == "products" and parts[-1] == "context.md"
        and (len(parts) == 3 or (len(parts) == 5 and parts[2] == "initiatives"))
    )


def record_path(private, value, *, markdown=True):
    relative = Path(line(value, "Record path"))
    parts = relative.parts
    if (relative.is_absolute() or relative.as_posix() != value or (markdown and relative.suffix != ".md")
            or len(parts) < 2 or any(part.startswith(".") or part == "secrets" for part in parts)):
        raise ValueError("Use a direct workspace-relative record path")
    if parts[0] != "context" and not (parts[0] == "products" and len(parts) >= 3 and SLUG.fullmatch(parts[1])):
        raise ValueError("Use context/ or products/<product>/ for a record")
    target = private / relative
    if target.resolve() != target or (target.exists() and not target.is_file()):
        raise ValueError("Select a regular workspace record")
    return target


def subject_key(value, prefixes=("product", "area", "topic")):
    key = line(value, "Subject")
    match = SUBJECT.fullmatch(key)
    if not match or match[1] not in prefixes:
        raise ValueError(f"Use a subject such as {prefixes[0]}/example")
    return key


def subject_list(value):
    if not isinstance(value, list):
        raise ValueError("Expected a list of subjects")
    subjects = [subject_key(item) for item in value]
    if len(set(subjects)) != len(subjects):
        raise ValueError("List each subject once")
    return subjects


def validate_remit(private, remit):
    fields(remit, ("responsibilities", "follow"))
    subject_list(remit["follow"])
    if not isinstance(remit["responsibilities"], list):
        raise ValueError("Expected a list of responsibilities")
    seen = set()
    for responsibility in remit["responsibilities"]:
        fields(responsibility, ("subject", "role", "goals", "depends_on"))
        subject = subject_key(responsibility["subject"], ("product", "area"))
        if subject in seen:
            raise ValueError(f"Duplicate responsibility: {subject}")
        seen.add(subject)
        if responsibility["role"] not in ("owner", "shared"):
            raise ValueError("A responsibility role must be owner or shared")
        if subject in subject_list(responsibility["depends_on"]):
            raise ValueError(f"A responsibility cannot depend on itself: {subject}")
        if not isinstance(responsibility["goals"], list):
            raise ValueError("Use a list of existing goal or metric links")
        for goal in responsibility["goals"]:
            parsed = urlsplit(line(goal, "Goal link"))
            if parsed.scheme in ("https", "http") and parsed.hostname and not (
                parsed.username or parsed.password
            ):
                continue
            if parsed.scheme or parsed.netloc or parsed.query:
                raise ValueError("Use a workspace path or an HTTP(S) goal link without credentials")
            if not record_path(private, unquote(parsed.path), markdown=False).is_file():
                raise ValueError(f"Goal link has no workspace record: {goal}")
    return remit


def remit_path(private):
    path = private / REMIT_PATH
    if path.resolve() != path or (path.exists() and not path.is_file()):
        raise ValueError("PM remit must be a regular file inside the workspace")
    return path


def read_remit(private):
    path = remit_path(private)
    if path.is_file():
        return validate_remit(private, json.loads(path.read_text(encoding="utf-8")))
    return None


def write_remit(private, remit):
    validate_remit(private, remit)
    target = remit_path(private)
    original = target.read_text(encoding="utf-8") if target.is_file() else None
    candidate = json.dumps(remit, indent=2, ensure_ascii=False) + "\n"
    if original != candidate:
        with storage.writer_lock(private):
            storage.replace_text(target, original, candidate)


def relevance(remit, subject, affects):
    if remit is None:
        return ("company" if subject == "company" else "unknown"), []
    direct, affected, dependencies = [], [], []
    for responsibility in remit["responsibilities"]:
        key = responsibility["subject"]
        if key == subject:
            direct.append(responsibility)
        elif key in affects:
            affected.append(responsibility)
        elif subject in responsibility["depends_on"]:
            dependencies.append(responsibility)
    if direct:
        return ("owned" if direct[0]["role"] == "owner" else "shared"), direct + affected
    if affected:
        return "affected", affected
    if dependencies:
        return "dependency", dependencies
    if subject == "company":
        return "company", []
    return ("following" if subject in remit["follow"] else "fyi"), []


def target_section(text, entry, section):
    if entry["scope"] == "product" and records.section(text, section) is None:
        legacy = records.LEGACY_PRODUCT_TOPICS.get(entry.get("topic"))
        if legacy and records.section(text, legacy) is not None:
            return legacy
    return section


def route_home(private, entry, scope, canonical, section, alternatives):
    if "record" not in entry:
        if section:
            path = record_path(private, canonical)
            if not path.exists() and private.is_dir():
                if canonical not in alternatives:
                    alternatives[canonical] = records.existing_briefs(private, canonical, scope)
                options = alternatives[canonical]
                if len(options) > 1:
                    return None, None, "ambiguous"
                if options:
                    canonical = options[0]
                    path = record_path(private, canonical)
            if path.is_file():
                return canonical, target_section(path.read_text(encoding="utf-8"), entry, section), "existing"
            return canonical, section, "new-brief"
        return None, None, "deferred" if scope in DEFERRED else "source"
    if scope in DEFERRED:
        raise ValueError("Delivery, detail, and unclear entries stay with their source or await review")
    record = entry["record"]
    fields(record, ("path", "reason"), ("parent", "basis", "trigger"))
    if not records.specific(line(record["reason"], "Record reason")):
        raise ValueError("Give a concrete reason to use this record")
    target = record_path(private, record["path"])
    if scope in ("product", "initiative"):
        product_dir = (private / product_path(entry["product"])).parent
        if product_dir not in target.parents:
            raise ValueError("A product record belongs under its own product")
    elif target.relative_to(private).parts[0] != "context":
        raise ValueError("Company, area, and reference records belong under context/")
    if brief_path(record["path"]) and (record["path"] != canonical or not section):
        raise ValueError("Select a topic and scope matching the standard context path")
    parts = target.relative_to(private).parts
    if scope == "initiative" and len(parts) >= 4 and parts[2] == "initiatives" and parts[3] != entry["initiative"]:
        raise ValueError("Choose a record belonging to the declared initiative")
    if scope == "product" and len(filing.home(record["path"]).parts) != 2:
        raise ValueError("A product note belongs to the product, outside its initiatives")
    if scope == "initiative" and filing.home(record["path"]) != filing.home(canonical):
        raise ValueError("Choose the declared initiative home")
    if target.is_file():
        text = target.read_text(encoding="utf-8")
        marker = records.MARKER.match(text)
        kind = marker[1] if marker else None
        if kind == "context-note":
            return record["path"], "Context", "existing"
        if scope in TOPICS and kind == f"{scope}-context" and section:
            return record["path"], target_section(text, entry, section), "existing"
        return record["path"], None, "existing"
    if brief_path(record["path"]):
        return canonical, section, "new-brief"
    filing.note_contract(private, record["path"], record.get("parent"), record.get("basis"), record["reason"], record.get("trigger"))
    filing.check_new(private, "context-note", record["path"], None)
    return record["path"], "Context", "new-note"


def validate_entry_shape(entry, section):
    table_field = {"Vocabulary": "term", "Decisions already closed": "decision"}.get(section)
    expected = {table_field} if table_field else set()
    if (entry.keys() & {"term", "decision"}) != expected:
        raise ValueError("Vocabulary and decisions need a structured term or decision in their matching section")
    if table_field:
        if entry.keys() & {"question", "answers", "interpretation", "rule"}:
            raise ValueError("Use the structured fields for vocabulary and decisions")
        data = entry[table_field]
        if table_field == "term":
            fields(data, ("name", "owner", "avoid"))
        else:
            fields(data, ("question", "scope", "person", "date", "next_step"))
            iso_day(data["date"], "Decision date")
        for key, value in data.items():
            line(value, key)
            if key != "avoid" and not records.specific(value):
                raise ValueError(f"{key} needs a specific value")
    if "rule" in entry:
        if "interpretation" in entry or "question" in entry or not section:
            raise ValueError("A rule needs a context section and its own entry")
        rule = line(entry["rule"], "Rule")
        quote = entry.get("quote")
        if (isinstance(quote, str) and re.search(r"\b(?:not|never|cannot|prohibited|forbidden|excluded)\b", quote, re.I)
                and rule != quote):
            raise ValueError("Keep the original wording of an exclusion in the rule; record its application separately")


def route(payload, private, remit=None):
    """Plan destinations and PM relevance independently from prepared excerpts."""
    fields(payload, ("sources", "entries"))
    sources = source_rows(payload["sources"])
    if not isinstance(payload["entries"], list):
        raise ValueError("entries must be a list")

    alternatives = {}
    entries = []
    for entry in payload["entries"]:
        fields(entry, ("scope",), ("topic", "product", "initiative", "subject", "record", "affects", "source",
                                    "location", "quote", "question", "answers", "interpretation",
                                    "rule", "term", "decision"))
        scope = line(entry["scope"], "Scope")
        if scope not in TOPICS and scope not in DEFERRED | {"area", "reference"}:
            raise ValueError(f"Unknown context scope: {scope}")
        if scope not in ("product", "initiative") and "product" in entry:
            raise ValueError("Use product for product or initiative scope")
        if scope != "initiative" and "initiative" in entry:
            raise ValueError("Use initiative only for initiative scope")
        canonical, subject = None, None
        if scope == "product":
            canonical = product_path(entry.get("product"))
            subject = f"product/{entry['product']}"
        elif scope == "initiative":
            canonical = initiative_path(entry.get("product"), entry.get("initiative"))
            subject = f"product/{entry['product']}"
        elif scope == "company":
            canonical, subject = COMPANY_PATH, "company"
        elif scope in ("area", "reference"):
            prefix = "area" if scope == "area" else "topic"
            subject = subject_key(entry.get("subject"), (prefix,))
        if "subject" in entry and scope not in ("area", "reference"):
            raise ValueError("Use subject only for area or reference scope")
        section = None
        if "topic" in entry:
            topic = line(entry["topic"], "Topic")
            section = TOPICS.get(scope, {}).get(topic)
            if not section:
                raise ValueError(f"Use a supported brief topic for {scope} scope")
        requested_section = section
        destination, section, disposition = route_home(private, entry, scope, canonical, section, alternatives)
        if disposition == "ambiguous":
            section = requested_section
        validate_entry_shape(entry, section)
        affects = entry.get("affects", {})
        if not isinstance(affects, dict):
            raise ValueError("List affected subjects and their consequences as a JSON object")
        for affected, reason in affects.items():
            subject_key(affected, ("product", "area"))
            line(reason, "Consequence")
        attention, responsibilities = relevance(remit, subject, affects)

        if "question" in entry:
            if not section or entry.keys() & {"source", "location", "quote", "answers", "interpretation"}:
                raise ValueError("An open question needs a context section")
            line(entry["question"], "Open question")
        else:
            source = entry.get("source")
            if type(source) is not int or not 1 <= source <= len(sources):
                raise ValueError("Use the 1-based index of a supplied source")
            if sources[source - 1]["coverage"] == "unavailable":
                raise ValueError("An unavailable source cannot supply an excerpt")
            line(entry.get("location"), "Source location")
            line(entry.get("quote"), "Source excerpt")
            if "answers" in entry:
                if not section:
                    raise ValueError("An answer needs a context section")
                line(entry["answers"], "Answered question")
            if "interpretation" in entry:
                line(entry["interpretation"], "Interpretation")
        if disposition == "ambiguous":
            entry = dict(entry, candidates=alternatives[canonical])
        entries.append(dict(entry, destination=destination, section=section, disposition=disposition,
                            relevance=attention, responsibilities=responsibilities))
    verification = verify_excerpts(payload["sources"], entries, private)
    return {"sources": sources, "entries": entries, "source_checks": verification, "remit_configured": remit is not None}


def literal(value):
    # Preserve visible source text while keeping its Markdown from changing the record.
    return re.sub(r"[][{}\\*_~|\x60]", lambda match: f"&#{ord(match[0])};", escape(value, quote=False))


def edit_section(text, section_name, body):
    pattern = rf"(^## {re.escape(section_name)}[ \t]*\n).*?(?=^## |\Z)"
    if section_name == "Data boundaries":
        text = re.sub(pattern, "", text, count=1, flags=re.M | re.S)
        return re.sub(r"(?=^## )", lambda _: f"## {section_name}\n\n{body}\n\n", text, count=1, flags=re.M)
    if records.section(text, section_name) is None:
        return re.sub(r"(?=^## Context controls[ \t]*$)",
                      lambda _: f"## {section_name}\n\n{body}\n\n", text, count=1, flags=re.M)
    return re.sub(pattern, lambda match: match[1] + "\n" + body + "\n\n", text, count=1, flags=re.M | re.S)


def table_row(values):
    return "| " + " | ".join(values) + " |"


def section_body(text, heading):
    body = (records.section(text, heading) or "").strip()
    columns = records.CONTEXT_TABLES.get(heading)
    if not columns:
        return "" if records.PLACEHOLDER.fullmatch(body) else body
    if not body:
        return table_row(columns) + "\n" + table_row(["---"] * len(columns))
    return re.sub(r"^\| *(?:\{\{[^{}]+\}\} *\| *)+\n?", "", body, flags=re.M)


def render_entry(entry, identifier):
    cite = f"[{identifier}] ({literal(entry['location'])})"
    quote = literal(entry["quote"])
    if "term" in entry:
        term = entry["term"]
        return table_row([literal(term["name"]), f"{quote} {cite}", literal(term["owner"]), literal(term["avoid"])])
    if "decision" in entry:
        decision = entry["decision"]
        return table_row([
            literal(decision["question"]), literal(decision["scope"]), f"{literal(decision['person'])}, {decision['date']}",
            f"{quote} {cite}", literal(decision["next_step"]),
        ])
    if "rule" in entry:
        label, statement = "Rule", literal(entry["rule"])
    elif "interpretation" in entry:
        label, statement = "Interpretation", literal(entry["interpretation"])
    else:
        label = "Example" if entry.get("topic") == "examples" else "Fact"
        statement = "Source excerpt"
    return f"- {label}: {statement} {cite}\n  > {quote}"


def insert_entries(text, selected, sources, private, target):
    rows, errors = records.table(text, "Sources", records.SOURCE_COLUMNS)
    if errors:
        raise ValueError("; ".join(errors))
    known = {(ref, published, checked): identifier for identifier, ref, published, checked in rows
             if re.fullmatch(r"S[1-9]\d*", identifier)}
    source_section = records.section(text, "Sources").strip()
    source_changed = False
    updates = {}
    for entry in selected:
        heading = entry["section"]
        if heading not in updates:
            updates[heading] = section_body(text, heading)
        if "question" in entry:
            bullet = f"- Unknown: {literal(entry['question'])}"
        else:
            source = sources[entry["source"] - 1]
            reference = records.retarget_links(source["reference"], private / "README.md", target, private)
            key = (reference, source["date"], source["checked_on"])
            already_in_section = any(
                f"\n{render_entry(entry, previous_id)}\n" in f"\n{updates[heading]}\n"
                for (previous_ref, published, _), previous_id in known.items()
                if (previous_ref, published) == key[:2]
            )
            if already_in_section:
                continue
            identifier = known.get(key)
            if not identifier:
                number = max((int(item[1:]) for item in known.values()), default=0) + 1
                identifier = known[key] = f"S{number}"
                source_section += f"\n| {identifier} | {key[0]} | {key[1]} | {source['checked_on']} |"
                source_changed = True
            bullet = render_entry(entry, identifier)
        body = updates[heading]
        if f"\n{bullet}\n" not in f"\n{body}\n":
            updates[heading] = f"{body}\n{bullet}".strip()

    # If this batch both asks and answers a question, retain only the answer.
    for entry in selected:
        if "answers" in entry:
            heading = entry["section"]
            question = f"- Unknown: {literal(entry['answers'])}"
            # A question with continuation lines needs a separate review of the whole entry.
            pattern = rf"^{re.escape(question)}(?:\n(?!\n*  )|\Z)"
            updates[heading] = re.sub(pattern, "", updates[heading], flags=re.M).strip()
    for heading, body in updates.items():
        if body != (records.section(text, heading) or "").strip():
            text = edit_section(text, heading, body)
    if source_changed:
        source_section = "\n".join(value for value in source_section.splitlines() if "{{S1}}" not in value)
        text = edit_section(text, "Sources", source_section)
    return text


def apply(root, destination, plan, owner, lint):
    private = root / "workspace"
    target = record_path(private, destination)
    original = target.read_text(encoding="utf-8") if target.is_file() else None
    marker = records.MARKER.match(original or "")
    selected = [entry for entry in plan["entries"] if entry["destination"] == destination]
    if not selected:
        raise ValueError("Preview the proposed context record and select a destination from that preview")

    if original is None:
        kind = "context-note"
        if selected[0]["disposition"] == "new-brief":
            kind = f"{selected[0]['scope']}-context"
    else:
        kind = marker[1] if marker else None
    if kind not in records.CONTEXT_KINDS or records.context_location(kind, destination):
        raise ValueError("Use the existing record's workflow, or select a typed context section")
    topics = records.context_sections(kind)
    if any(entry["section"] not in topics for entry in selected):
        raise ValueError("Use the existing record's workflow, or select a typed context section")
    if original is None:
        text = records.draft_text(root, kind, target, owner=owner)
        if kind == "context-note":
            definitions = [entry["record"] for entry in selected]
            if any(value != definitions[0] for value in definitions):
                raise ValueError("Use one filing purpose and parent for this record")
            text = filing.add_contract(text, private, target, definitions[0])
        unused = topics - {entry["section"] for entry in selected}
        for heading in sorted(unused):
            text = re.sub(rf"^## {re.escape(heading)}[ \t]*\n.*?(?=^## |\Z)",
                          "", text, count=1, flags=re.M | re.S)
    else:
        text = original
    headings = re.findall(r"^## (.+)$", text, re.M)
    if len(set(headings)) != len(headings) or not records.CONTEXT_METADATA <= set(headings):
        raise ValueError("Use one section per heading and keep the context metadata before capture")
    candidate = insert_entries(text, selected, plan["sources"], private, target)
    if candidate == text:
        return False
    state = records.section(candidate, "Work state")
    def update_field(body, name, value):
        pattern = rf"(?m)^[ \t]*\|[ \t]*{name}[ \t]*\|[^\n]*$"
        return re.sub(pattern, lambda _: f"| {name} | {value} |", body, count=1)
    updated = state
    if records.work_state(text)[0].get("State") == "complete":
        updated = update_field(updated, "State", "draft")
    updated = update_field(updated, "Last checkpoint", f"{date.today().isoformat()}: Context captured. Review pending.")
    candidate = candidate.replace(state, updated, 1)
    problems = lint(root, target, candidate)
    if problems:
        raise ValueError("Context capture failed validation:\n" + "\n".join(problems))
    with storage.writer_lock(private):
        if original is None:
            filing.check_new(private, kind, destination, None)
        storage.replace_text(target, original, candidate)
    return True
