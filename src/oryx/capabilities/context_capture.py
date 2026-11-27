"""Route source excerpts and open questions, then write one selected context brief."""

from datetime import date
from html import escape
import pm_profile
from pathlib import Path
import re
import source_evidence

import layout
import ingestion_signals
import records
import filing
import storage
import upgrades
import task_context
import metric_checks
import evidence_reviews

COMPANY_PATH = layout.COMPANY
REMIT_PATH = pm_profile.PATH
TOPICS = dict(records.CONTEXT_TOPICS, pm=pm_profile.TOPICS)
DEFERRED = {"delivery", "detail", "unclear"}
SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
SUBJECT = re.compile(rf"(?:product/{SLUG.pattern}(?:/area/{SLUG.pattern})?|(?:area|topic)/{SLUG.pattern})")
REMIT_PROMPT = "Which products or product areas do you own or share? For each area, name its product."
DRAFT_REMIT_PROMPT = "Is your saved PM remit complete, or are there products or product areas to add?"


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
        fields(source, ("reference", "date", "coverage"), ("checked_on", "text", "ingestion"))
        reference = line(source["reference"], "Source reference")
        if not records.specific(reference) or "|" in reference or records.PLACEHOLDER.search(reference):
            raise ValueError("Use a source reference without table separators or placeholders")
        if records.uses_customization_source("README.md", reference):
            raise ValueError("Cite the underlying evidence. Studio customizations describe working methods.")
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
        result.append({key: value for key, value in source.items() if key not in ("text", "ingestion")})
    return result


COMMITMENT = re.compile(r"\b(?:will|shall|must|never|prohibited|forbidden|excluded|cannot|won['’]t)\b", re.I)


def verify_excerpts(inputs, entries, private, *, single_excerpt=False):
    """Check literal coverage in inspected text. Qualitative relevance still needs review."""
    reports = []
    for index, source in enumerate(inputs, 1):
        material, binding = source_evidence.capture_material(private, source)
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
                if single_excerpt:
                    if not any(left < end and right > start for left, right in spans):
                        continue  # Other findings are reviewed independently.
                elif not COMMITMENT.search(sentence):
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
                    if single_excerpt:
                        raise ValueError(f"Source {index}: retain the full reviewed sentence and its qualifications: {sentence}")
                    raise ValueError(f"Source {index}: route or explicitly defer the entire commitment: {sentence}")
        if single_excerpt:
            reports.append({"source": index, "verification": "reviewed excerpt matched inspected text"})
        else:
            reports.append({"source": index, "verification": "supplied text", "commitment_sentences": len(statements)})
        if binding is not None:
            reports[-1]["local_source"] = binding
    return reports


def product_path(slug):
    return layout.product(slug)


def brief_path(path):
    return layout.brief_kind(path) is not None


def record_path(private, value, *, markdown=True):
    relative = Path(line(value, "Record path"))
    parts = relative.parts
    if (relative.is_absolute() or relative.as_posix() != value or (markdown and relative.suffix != ".md")
            or len(parts) < 2 or any(part.startswith(".") or part == "secrets" for part in parts)):
        raise ValueError("Use a direct workspace-relative record path")
    if parts[0] not in {"context", "workspace"}:
        raise ValueError("Use context/ for reference or workspace/ for work")
    target = private / relative
    if target.resolve() != target or (target.exists() and not target.is_file()):
        raise ValueError("Select a regular workspace record")
    return target


def subject_key(value, prefixes=("product", "area", "topic")):
    key = line(value, "Subject")
    if not SUBJECT.fullmatch(key) or key.partition("/")[0] not in prefixes:
        raise ValueError(f"Use a subject such as {prefixes[0]}/example")
    return key


def subject_list(value):
    if not isinstance(value, list):
        raise ValueError("Expected a list of subjects")
    subjects = [subject_key(item) for item in value]
    if len(set(subjects)) != len(subjects):
        raise ValueError("List each subject once")
    return subjects


def validate_remit(private, remit, *, legacy=False):
    fields(remit, ("responsibilities", "follow"), ("status",))
    if "status" in remit and remit["status"] not in ("draft", "confirmed"):
        raise ValueError("Remit status must be draft or confirmed")
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
            pm_profile.checked_goal(private, goal, legacy=legacy)
    return remit


def remit_path(private):
    return pm_profile.safe_path(private, REMIT_PATH)


def read_remit(private):
    path = remit_path(private)
    legacy = pm_profile.safe_path(private, pm_profile.LEGACY)
    if legacy.exists():
        if path.exists():
            raise ValueError("Review the existing PM profile and legacy remit before choosing their contents")
        return validate_remit(private, pm_profile.legacy_data(legacy.read_bytes()), legacy=True)
    if path.is_file():
        remit = pm_profile.parse(path.read_text(encoding="utf-8"))
        if remit is not None:
            return validate_remit(private, remit)
    return None


def write_remit(private, remit):
    validate_remit(private, remit)
    with storage.writer_lock(private):
        storage.require_visible(private, pm_profile.PATH)
        if REMIT_PATH in upgrades.source_paths(private):
            raise ValueError("Preserve the original source at the PM profile path")
        if pm_profile.safe_path(private, pm_profile.LEGACY).exists():
            raise ValueError("Finish the legacy remit upgrade before editing the PM profile")
        target = remit_path(private)
        original = target.read_bytes().decode("utf-8") if target.is_file() else None
        if original:
            previous = pm_profile.parse(original)
            if previous is not None:
                validate_remit(private, previous)
        candidate = pm_profile.render(remit, original)
        if candidate != original:
            storage.replace_text(target, original, candidate)


def remit_status(remit):
    return "missing" if remit is None else pm_profile.effective_status(remit)


def inspect_remit(private):
    try:
        return read_remit(private), None
    except (OSError, ValueError) as exc:
        return None, str(exc)


def remit_prompt(private):
    remit, error = inspect_remit(private)
    if error:
        return "Review the existing PM remit with the PM before repairing it."
    status = remit_status(remit)
    if status == "confirmed":
        return None
    if remit and (remit["responsibilities"] or remit["follow"]):
        return DRAFT_REMIT_PROMPT
    return REMIT_PROMPT


def subject_family(subject):
    """An area's parent covers the area. Broader news alone has no confirmed area impact."""
    if not subject:
        return ()
    parent, separator, _ = subject.rpartition("/area/")
    return (subject, parent) if separator else (subject,)


def relevance(remit, subject, affects):
    if remit is None:
        return ("company" if subject == "company" else "unknown"), []
    responsibilities = remit["responsibilities"]
    family = subject_family(subject)
    by_subject = {r["subject"]: r for r in responsibilities}

    def most_specific(keys):
        return next((key for key in keys if key in by_subject), None)

    direct = by_subject.get(most_specific(family))
    affected_keys = {most_specific(subject_family(named)) for named in affects}
    affected = [r for r in responsibilities if r["subject"] in affected_keys and r is not direct]
    if direct:
        return ("owned" if direct["role"] == "owner" else "shared"), [direct, *affected]
    if affected:
        return "affected", affected
    dependencies = [r for r in responsibilities if any(key in r["depends_on"] for key in family)]
    if dependencies:
        return "dependency", dependencies
    if subject == "company":
        return "company", []
    if any(key in remit["follow"] for key in family):
        return "following", []
    return ("fyi" if remit_status(remit) == "confirmed" else "unknown"), []


def target_section(text, entry, section):
    if "heading" in entry:
        return section
    if text.startswith("<!-- pm: product-area-context -->\n"):
        by_topic = {"ownership": "Area scope and ownership", "contribution": "Area outcomes"}
        return by_topic.get(entry.get("topic"), records.AREA_HEADINGS.get(section, section))
    if entry["scope"] == "product" and records.section(text, section) is None:
        legacy = records.LEGACY_PRODUCT_TOPICS.get(entry.get("topic"))
        if legacy and records.section(text, legacy) is not None:
            return legacy
    return section


def contains_capture(text, path, entry, section, sources, private):
    source_no = entry.get("source")
    if "quote" not in entry or type(source_no) is not int or not 1 <= source_no <= len(sources):
        return False
    validate_entry_shape(entry, section)
    line(entry["quote"], "Source excerpt")
    line(entry.get("location"), "Source location")
    if "interpretation" in entry:
        line(entry["interpretation"], "Interpretation")
    source = sources[source_no - 1]
    ref = records.retarget_links(source["reference"], private / "README.md", path, private)
    body = "\n" + (records.section(text, target_section(text, entry, section)) or "").strip() + "\n"
    rows, _ = records.table(text, "Sources", records.SOURCE_COLUMNS)
    return any("\n" + render_entry(entry, ident) + "\n" in body for ident, previous, published, _ in rows
               if (previous, published) == (ref, source["date"]))


def checked_area_text(private, area):
    path = record_path(private, area)
    if not path.is_file():
        return None
    if area in upgrades.source_paths(private):
        raise ValueError(f"Preserve the original source at {area}")
    text = path.read_text(encoding="utf-8")
    if not text.startswith("<!-- pm: product-area-context -->\n"):
        raise ValueError(f"Review the existing file at {area} before using it as area context")
    filing.verify_note(private, area, text)
    return text


def standing_area_home(private, entry, product, section, sources):
    """Resolve questions in their original home and leave existing evidence there on replay."""
    group = entry.get("area_group")
    area = records.area_brief_path(entry["product"], entry["product_area"], private=private, group=group)
    area_text = checked_area_text(private, area)
    parent_name = layout.product(entry["product"])
    parent_path = record_path(private, parent_name)
    if parent_path.is_file() and parent_name not in upgrades.source_paths(private):
        overview = task_context.read_document(Path(parent_name), parent_path)
        shared = [subject for subject in task_context.shared_area_links(overview, date.today())
                  if subject.endswith("/area/" + entry["product_area"])]
        if shared and not (area_text and group):
            raise ValueError("This name also refers to a shared area. Confirm the existing local brief and group "
                             "or use its canonical subject: " + ", ".join(sorted(shared)))
    if area_text is None:
        parent = record_path(private, product)
        if parent.is_file() and product not in upgrades.source_paths(private):
            text = parent.read_text(encoding="utf-8")
            tag = f"<!-- product-area:{entry['product_area']} -->"
            established = any(tag in line and line.startswith(("- ", "| ")) for line in text.splitlines())
            if established:
                question = entry.get("answers", entry.get("question"))
                body = records.section(text, target_section(text, entry, section)) or ""
                if (group is None or isinstance(question, str) and
                        f"- Unknown: {scoped_text(entry, literal(question))}" in body.splitlines()
                        or contains_capture(text, parent, entry, section, sources, private)):
                    return product
        if group is None:
            raise ValueError("Confirm how the team groups this product scope, then supply area_group for its own brief")
        return area
    product = filing.area_parent(private, area)
    parent = record_path(private, product)
    parent_text = parent.read_text(encoding="utf-8")
    local_entry = {k: v for k, v in entry.items() if k != "product_area"}
    if "record" in entry:
        record = entry["record"]
        if not isinstance(record, dict):
            raise ValueError("Choose a record with its path and reason")
        if record.get("path") not in (product, area):
            return area
    question = entry.get("answers", entry.get("question"))
    if isinstance(question, str):
        homes = []
        for name, text, scoped in ((product, parent_text, entry), (area, area_text, local_entry)):
            body = records.section(text, target_section(text, entry, section)) or ""
            if f"- Unknown: {scoped_text(scoped, literal(question))}" in body.splitlines():
                homes.append(name)
        if len(homes) == 2:
            selected = entry.get("record", {}).get("path")
            if selected not in homes:
                raise ValueError(f"Question exists in both {product} and {area}. Select its owning record explicitly")
            return selected
        if homes:
            return homes[0]
    if contains_capture(parent_text, parent, entry, section, sources, private):
        if not contains_capture(area_text, private / area, local_entry, section, sources, private):
            return product
    return area


def area_context(private, product, area):
    """Locate the dedicated brief and area entries without changing or copying any record."""
    inherited = task_context.resolve(private, explicit={"product": product, "area": area})
    if inherited["status"] == "ambiguous":
        raise ValueError(" ".join(inherited["warnings"] + inherited["choices"]))
    shared = inherited.get("shared_area")
    if shared:
        return {"subject": shared["subject"], "area_brief": shared["area_brief"],
                "shared_area": shared, "product_briefs": records.product_briefs(private, product),
                "inline_entries": [], "inherited_company": [row for row in inherited["entries"] if row["record"] == layout.COMPANY]}
    area_name = records.area_brief_path(product, area, private=private)
    area_path = private / area_name
    exists = checked_area_text(private, area_name) is not None
    parents = records.product_briefs(private, product)
    matches = []
    originals = upgrades.source_paths(private)
    marker = f"<!-- product-area:{area} -->"
    initiatives = {}
    for path in storage.inventory(private):
        rel = path.relative_to(private)
        if (rel.parts[:3] != ("context", "products", product) and rel.parts[:2] != ("context", "initiatives")):
            continue
        if (rel.as_posix() in originals or path == area_path or path.suffix != ".md"
                or any(p.startswith(".") or p in {"sources", "secrets"} for p in rel.parts)
                or path.resolve() != path or not path.is_file()):
            continue
        if rel.parts[:2] == ("context", "initiatives"):
            if len(rel.parts) < 4 or not layout.SLUG.fullmatch(rel.parts[2]):
                continue
            owning = layout.initiative(rel.parts[2])
            if owning not in initiatives:
                candidate = record_path(private, owning)
                initiatives[owning] = (candidate.is_file() and owning not in originals and
                                       records.parent_reference(owning, candidate.read_text(encoding="utf-8")) in parents)
            if not initiatives[owning]:
                continue
        with path.open("rb") as stream:
            kind = records.MARKER.match(stream.readline(128).decode("utf-8", errors="replace"))
            if not kind or kind[1] not in {"product-context", "initiative-context", "context-note"}:
                continue
            lines = stream.read().decode("utf-8").splitlines()
        entries = []
        section = None
        for i, line_text in enumerate(lines):
            if line_text.startswith("## "):
                section = line_text[3:]
            if marker not in line_text or not line_text.startswith(("- ", "| ")):
                continue
            end = i + 1
            while end < len(lines) and lines[end].startswith("  "):
                end += 1
            entries.append({"section": section, "line": i + 2, "text": "\n".join(lines[i:end])})
        if entries:
            claims = "\n".join(item["text"] for item in entries)
            ids = set(re.findall(r"\[(S[1-9]\d*)\]", claims))
            rows, errors = records.table("\n".join(lines), "Sources", records.SOURCE_COLUMNS)
            matches.append({"record": rel.as_posix(), "entries": entries,
                            "sources": [dict(zip(records.SOURCE_COLUMNS, row)) for row in rows if row[0] in ids],
                            "source_errors": errors})
    return {"subject": f"product/{product}/area/{area}", "area_brief": area_name if exists else None,
            "product_briefs": parents, "inline_entries": matches,
            "inherited_company": [row for row in inherited["entries"] if row["record"] == layout.COMPANY]}


def route_home(private, entry, scope, canonical, section):
    if scope == "pm":
        if "record" in entry:
            record = entry["record"]
            fields(record, ("path", "reason"))
            if record["path"] != REMIT_PATH or not section or not records.specific(line(record["reason"], "Record reason")):
                raise ValueError("PM background belongs in the PM profile with a supported topic")
        if not section:
            return None, None, "source"
        if pm_profile.safe_path(private, pm_profile.LEGACY).exists():
            raise ValueError("Finish the legacy remit upgrade before writing to the PM profile")
        target = remit_path(private)
        if target.is_file():
            text = target.read_text(encoding="utf-8")
            pm_profile.parse(text)
            pm_profile.capture_block(text)
            return REMIT_PATH, section, "existing"
        return REMIT_PATH, section, "new-brief"
    if scope == "initiative":
        overview = record_path(private, canonical)
        if overview.exists():
            text = overview.read_text(encoding="utf-8")
            if (not text.startswith("<!-- pm: initiative-context -->\n") or
                    records.parent_reference(canonical, text) != product_path(entry["product"])):
                raise ValueError("This initiative already has another or unresolved owning product")
    if "record" not in entry:
        if not section:
            return None, None, "deferred" if scope in DEFERRED else "source"
        path = record_path(private, canonical)
        if not path.is_file():
            return canonical, section, "new-brief"
        text = path.read_text(encoding="utf-8")
        marker = records.MARKER.match(text)
        if not marker or marker[1] != layout.brief_kind(canonical):
            raise ValueError(f"Identify the owning brief before capturing into {canonical}")
        return canonical, target_section(text, entry, section), "existing"
    if scope in DEFERRED:
        raise ValueError("Delivery, detail, and unclear entries stay with their source or await review")
    record = entry["record"]
    fields(record, ("path", "reason"), ("parent", "basis", "trigger", "topic_question", "topic_peer"))
    if not records.specific(line(record["reason"], "Record reason")):
        raise ValueError("Give a concrete reason to use this record")
    target = record_path(private, record["path"])
    if target.relative_to(private).parts[0] == "workspace":
        if not target.is_file() or not layout.valid_work(record["path"]):
            raise ValueError("Use the existing workspace artifact's workflow")
        return record["path"], None, "existing"
    owner = layout.entity(record["path"])
    if scope in TOPICS:
        homes = {layout.entity(canonical)}
        if scope == "product" and "product_area" in entry:
            homes.add(Path(records.area_brief_path(entry["product"], entry["product_area"], private=private,
                                                   group=entry.get("area_group"))).parent)
        if owner not in homes:
            raise ValueError("Choose a record belonging to the declared context entity")
    if brief_path(record["path"]) and (record["path"] != canonical or not section):
        raise ValueError("Select a topic and scope matching the standard context path")
    if target.is_file():
        text = target.read_text(encoding="utf-8")
        marker = records.MARKER.match(text)
        kind = marker[1] if marker else None
        if kind == "context-note":
            filing.verify_note(private, record["path"], text)
            return record["path"], entry.get("heading", "Context"), "existing"
        if brief_path(record["path"]) and kind == layout.brief_kind(record["path"]):
            return canonical, target_section(text, entry, section), "existing"
        raise ValueError("Select a typed reference at its owning context path")
    if brief_path(record["path"]):
        return canonical, section, "new-brief"
    note_filing(private, record)
    filing.check_new(private, "context-note", record["path"], None)
    return record["path"], entry.get("heading", "Context"), "new-note"


def note_filing(private, record):
    return filing.note_contract(private, record["path"], record.get("parent"), record.get("basis"),
                                record["reason"], record.get("trigger"), record.get("topic_question"),
                                record.get("topic_peer"))


def validate_entry_shape(entry, section):
    if "record_decision" in entry and "decision" not in entry:
        raise ValueError("Use decision confirmation only to record an explicitly reviewed decision")
    if "uncertainty" in entry:
        if not section or entry.keys() & {"decision", "rule", "term", "question", "answers"}:
            raise ValueError("Attach an unresolved question to a sourced statement or interpretation")
        if not records.specific(line(entry["uncertainty"], "Unresolved question")):
            raise ValueError("Describe the specific uncertainty that remains")
    if "supersedes" in entry:
        prior = entry["supersedes"]
        fields(prior, ("source", "entry"))
        line(prior["entry"], "Previous rule or decision")
        if (not re.fullmatch(r"S[1-9]\d*", line(prior["source"], "Prior source ID"))
                or not entry.keys() & {"rule", "decision"} or "answers" in entry):
            raise ValueError("Use a rule or accepted decision to supersede one named entry from a local source ID")
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


def section_leads(text, entries):
    pattern = r"(?m)^## (.+)$"
    raw = re.findall(pattern, text)
    # Keep comment padding so removing an inline comment cannot fabricate a matching heading.
    visible = records.visible_section_markup(text)
    if raw != re.findall(pattern, visible):
        raise ValueError("Ambiguous context section boundary. Indent level-two headings inside examples, HTML, or comments")
    headings = {heading.strip().casefold(): heading.rstrip() for heading in raw}
    marker = records.MARKER.match(text)
    standard = records.context_sections(marker[1]) if marker and marker[1] in records.CONTEXT_KINDS else set()
    groups = {}
    for entry in entries:
        heading = entry["section"]
        if headings.setdefault(heading.casefold(), heading) != heading:
            raise ValueError(f"Use the existing spelling for the section {headings[heading.casefold()]}")
        groups.setdefault(heading, []).append(entry)
    leads = {}
    for heading, group in groups.items():
        proposed = {entry["lead"] for entry in group if "lead" in entry}
        if len(proposed) > 1:
            raise ValueError(f"Give {heading} one lead for this capture")
        existing, body = records.split_context_lead(records.section(text, heading) or "")
        if existing is None and body and heading not in standard:
            if heading in records.CONTEXT_TABLES:
                draft = records.work_state(text)[0].get("State") == "draft"
                errors = records.context_table_errors(text, heading, draft)
                if errors:
                    raise ValueError(f"{heading}: review the existing table before adding a lead. {'. '.join(errors)}")
            else:
                previous, unlabelled = records.context_entries(body)
                if unlabelled or any(label in {"Fact", "Rule", "Example", "Reported metric"}
                                     and not records.SOURCE_REFERENCE.search(claim)
                                     for label, claim in previous):
                    raise ValueError(f"{heading}: verify and label legacy claims with citations before adding a lead")
        lead = next(iter(proposed), existing)
        if lead is None:
            lead = records.CONTEXT_LEADS.get(heading)
        if lead is None or not records.valid_context_lead(lead):
            raise ValueError(f"Give {heading} a short lead that explains when to consult the section")
        leads[heading] = lead
    return leads


def decision_review(entry, destination, source):
    """Bind recording consent to the destination, decision, evidence and replacement."""
    from decision_authority import fingerprint

    reviewed = {"destination": destination, "decision": entry["decision"], "source": source,
                "quote": entry["quote"], "location": entry["location"],
                "product_area": entry.get("product_area"), "supersedes": entry.get("supersedes")}
    return fingerprint(reviewed)


def validate_decision_approval(entry, revision, checked_on):
    if "record_decision" not in entry:
        return
    approval = entry["record_decision"]
    fields(approval, ("revision", "pm", "date", "reference", "reply"))
    if approval["revision"] != revision:
        raise ValueError("Decision or evidence changed. Show the new decision preview to the PM")
    reply = line(approval["reply"], "PM reply")
    if reply.strip().rstrip(".").casefold() != "record this decision":
        raise ValueError('For this decision preview, ask the PM to choose "Record this decision" explicitly')
    iso_day(approval["date"], "Recording confirmation date")
    if approval["date"] < max(entry["decision"]["date"], checked_on):
        raise ValueError("Recording confirmation cannot predate the decision or the reviewed evidence")
    for key in ("pm", "reference"):
        if not records.specific(line(approval[key], key)):
            raise ValueError("Supply the PM, discussion reference and exact confirmation reply")


def ingestion_reviews(private, sources, entries, single_excerpt):
    """Dispatch only authorized original material, preserving isolated byte ranges."""
    results = []
    for index, source in enumerate(sources, 1):
        if source["coverage"] == "unavailable":
            continue
        meta = source.get("ingestion", {})
        reference = source["reference"]
        allowed = {"kind", "scope", "retention", "observations", "purposes", "source_id", "revision",
                   "event_id", "subject", "offset"}
        if not isinstance(meta, dict) or meta.keys() - allowed:
            results.append({"source": index, "status": "invalid-ingestion-options"})
            continue
        info = {"kind": "document", "scope": reference, "retention": "chat-only",
                **{k: v for k, v in meta.items() if k != "observations"},
                "reference": reference, "coverage": source["coverage"], "authorized": True}
        original = source.get("text")
        reads = [info if original is None else {**info, "text": original}]
        if single_excerpt:
            # Never manufacture an attributed original by concatenating prepared quotations.
            reads = []
            for quote in dict.fromkeys(row["quote"] for row in entries if row.get("source") == index and row.get("quote")):
                if not original or original.count(quote) != 1:
                    continue
                start = original.index(quote)
                if start and original[start - 1] != "\n" or start + len(quote) < len(original) and original[start + len(quote)] != "\n":
                    continue
                if type(info.get("offset", 0)) is not int:
                    continue
                # Include the inspected line separators so the range proves where the utterance begins.
                left = start - 1 if start else start
                right = min(start + len(quote) + 1, len(original))
                reads.append({**info, "coverage": "partial", "text": original[left:right],
                              "offset": info.get("offset", 0) + len(original[:left].encode())})
        for part in reads:
            envelope = {"source": part, "moment": "busy"}
            if "observations" in meta:
                envelope["observations"] = meta["observations"]
            results.append({"source": index, **ingestion_signals.for_task(private, envelope)})
    return results


def route(payload, private, remit=None, *, single_excerpt=False, descriptive_intake=False):
    """Plan destinations and PM relevance independently from prepared excerpts."""
    fields(payload, ("sources", "entries"), ("responses",))
    responses = payload.get("responses", [])
    evidence_reviews.validate_responses(responses)
    sources = source_rows(payload["sources"])
    if not isinstance(payload["entries"], list):
        raise ValueError("entries must be a list")

    import layout_upgrade
    blocked = {}
    initiative_products = {}
    entries = []
    for entry in payload["entries"]:
        fields(entry, ("scope",), ("shared_area", "topic", "heading", "lead", "product", "product_area", "area_group", "initiative", "subject",
                                    "record", "affects", "source", "location", "quote", "question", "answers",
                                    "interpretation", "uncertainty", "rule", "term", "decision", "record_decision", "supersedes", "risk"))
        scope = line(entry["scope"], "Scope")
        if scope not in TOPICS and scope not in DEFERRED | {"area", "reference"}:
            raise ValueError(f"Unknown context scope: {scope}")
        if scope not in ("product", "initiative") and "product" in entry:
            raise ValueError("Use product for product or initiative scope")
        if scope != "initiative" and "initiative" in entry:
            raise ValueError("Use initiative only for initiative scope")
        if "area_group" in entry:
            if scope != "product" or "product_area" not in entry:
                raise ValueError("Choose a product and its confirmed area before naming an area group")
            layout.area(entry.get("product"), entry["product_area"], entry["area_group"])
        deferred_initiative = None
        if scope == "initiative" and entry.get("product") is None:
            deferred_initiative = layout.slug(entry.get("initiative"))
            allowed = {"scope", "product", "initiative", "topic", "source", "location", "quote", "interpretation", "affects"}
            if entry.keys() - allowed:
                raise ValueError("Confirm the owning product before proposing changes to this initiative.")
            if "topic" in entry and line(entry["topic"], "Topic") not in TOPICS["initiative"]:
                raise ValueError("Use a supported brief topic for initiative scope")
            # Until the owning product is known, the passage can be reviewed at its source.
            # Use the same source and commitment checks as an explicitly deferred excerpt.
            scope = "unclear"
            entry = {k: v for k, v in entry.items() if k not in {"product", "initiative", "topic"}}
            entry["scope"] = scope
        canonical, subject = None, None
        if scope == "product":
            canonical = product_path(entry.get("product"))
            subject = f"product/{entry['product']}"
        elif scope == "initiative":
            canonical = records.initiative_home(private, entry.get("product"), entry.get("initiative"))
            if initiative_products.setdefault(canonical, entry["product"]) != entry["product"]:
                raise ValueError("Use one accountable product for an initiative in this capture")
            subject = f"product/{entry['product']}"
        elif scope == "company":
            canonical, subject = COMPANY_PATH, "company"
        elif scope == "stakeholder":
            canonical, subject = layout.STAKEHOLDERS, "stakeholders"
        elif scope == "pm":
            canonical, subject = REMIT_PATH, "pm"
        elif scope in ("area", "reference"):
            prefix = "area" if scope == "area" else "topic"
            subject = subject_key(entry.get("subject"), (prefix,))
        if "product_area" in entry:
            area = entry["product_area"]
            if scope not in ("product", "initiative") or not isinstance(area, str) or not SLUG.fullmatch(area):
                raise ValueError("Use a product_area slug with a named product or initiative")
            subject = f"{subject}/area/{area}"
        if "subject" in entry and scope not in ("area", "reference"):
            raise ValueError("Use subject only for area or reference scope")
        section = None
        if "topic" in entry:
            topic = line(entry["topic"], "Topic")
            section = TOPICS.get(scope, {}).get(topic)
            if not section:
                raise ValueError(f"Use a supported brief topic for {scope} scope")
        if "heading" in entry:
            if section or scope in DEFERRED | {"pm"} or (canonical is None and "record" not in entry):
                raise ValueError("Use a topic or a heading for a typed context record")
            section = line(entry["heading"], "Section heading")
            reserved = {name.casefold() for name in records.CONTEXT_RESERVED_SECTIONS}
            if (not records.specific(section) or section != section.strip() or any(c in section for c in "#<>[]")
                    or section.casefold() in reserved):
                raise ValueError("Use a descriptive section heading outside the reserved context metadata")
        if scope == "product" and "product_area" in entry and section:
            canonical = standing_area_home(private, entry, canonical, section, sources)
        intended = entry["record"].get("path") if isinstance(entry.get("record"), dict) else canonical
        if intended is not None and not isinstance(intended, str):
            raise ValueError("Choose a record path as text")
        if intended and private.is_dir() and intended not in blocked:
            blocked[intended] = layout_upgrade.blocked(private, intended)
        if blocked.get(intended):
            destination, disposition = None, "ambiguous"
            entry = dict(entry, candidates=blocked[intended])
        else:
            destination, section, disposition = route_home(private, entry, scope, canonical, section)
            if disposition == "new-brief" and layout.brief_kind(destination) == "product-area-context":
                section = target_section("<!-- pm: product-area-context -->\n", entry, section)
        if "lead" in entry and (scope == "pm" or not section
                                or not records.valid_context_lead(line(entry["lead"], "Section lead"))):
            raise ValueError("Use a short prose lead for a typed context section")
        validate_entry_shape(entry, section)
        if "risk" in entry:
            evidence_reviews.check_risk(entry["risk"], sources)
            if "source" in entry and entry["risk"].get("source", entry["source"]) != entry["source"]:
                raise ValueError("Use the same source for the supplied claim and its risk")
        affects = entry.get("affects", {})
        if not isinstance(affects, dict):
            raise ValueError("List affected subjects and their consequences as a JSON object")
        for affected, reason in affects.items():
            subject_key(affected, ("product", "area"))
            line(reason, "Consequence")
        attention, responsibilities = relevance(remit, subject, affects)
        if scope in {"pm", "stakeholder"} and not responsibilities:
            attention = scope

        if "shared_area" in entry:
            shared = subject_key(entry["shared_area"], ("product",))
            if (scope != "product" or "/area/" not in shared or destination != product_path(entry["product"])
                    or shared.split("/")[1] == entry["product"] or not section
                    or entry.get("topic") == "examples" or metric_checks.is_claim(str(entry.get("quote", "")))
                    or section in records.CONTEXT_TABLES or entry.keys() & {
                        "question", "product_area", "rule", "term", "decision", "risk", "uncertainty", "interpretation"}):
                raise ValueError("Link a verified area in another product from a sourced fact in this product overview")
            _, home_product, _, home_area = shared.split("/")
            home = records.area_brief_path(home_product, home_area, private=private)
            if checked_area_text(private, home) is None:
                raise ValueError("Confirm the existing canonical area brief before linking it from another product")
        if "question" in entry:
            if not section or entry.keys() & {"source", "location", "quote", "answers", "interpretation"}:
                raise ValueError("An open question needs a context section")
            line(entry["question"], "Open question")
        else:
            source = entry.get("source")
            if type(source) is not int or not 1 <= source <= len(sources):
                raise ValueError("Use the 1-based index of a supplied source")
            if disposition == "new-note" and entry["record"].get("topic_peer"):
                category = Path(entry["record"]["path"]).parent.name
                filing.check_source_label(category, [sources[source - 1]["reference"]])
            if sources[source - 1]["coverage"] == "unavailable":
                raise ValueError("An unavailable source cannot supply an excerpt")
            if "supersedes" in entry and (scope == "pm" or sources[source - 1]["date"] in {"unknown", "undated"}):
                raise ValueError("Use a dated source when replacing a rule or decision in a context brief")
            line(entry.get("location"), "Source location")
            line(entry.get("quote"), "Source excerpt")
            if "answers" in entry:
                if not section:
                    raise ValueError("An answer needs a context section")
                line(entry["answers"], "Answered question")
            if "interpretation" in entry:
                line(entry["interpretation"], "Interpretation")
        if "decision" in entry:
            evidence = sources[entry["source"] - 1]
            revision = decision_review(entry, destination, evidence)
            validate_decision_approval(entry, revision, evidence["checked_on"])
            entry = dict(entry, decision_revision=revision)
        if deferred_initiative is not None:
            entry = dict(entry, pending_initiative=deferred_initiative,
                         follow_up="Confirm which product owns this initiative before filing the excerpt.")
        entries.append(dict(entry, destination=destination, section=section, disposition=disposition,
                            relevance=attention, responsibilities=responsibilities))
    originals = upgrades.source_paths(private)
    if any(row["destination"] and (row["destination"] in originals or "sources" in Path(row["destination"]).parts)
           for row in entries):
        raise ValueError("Original source files cannot be context capture destinations")
    targets = {}
    for entry in entries:
        destination = entry["destination"]
        if destination and destination != REMIT_PATH and entry["section"]:
            targets.setdefault(destination, []).append(entry)
    destination_docs = {} if descriptive_intake and any("decision" in entry for entry in entries) else None
    for destination, group in targets.items():
        target = record_path(private, destination)
        text = target.read_text(encoding="utf-8") if target.is_file() else ""
        if destination_docs is not None and text:
            doc = task_context.read_document(Path(destination), target, text=text)
            if doc:
                destination_docs[destination] = doc
        leads = section_leads(text, group)
        for entry in group:
            heading = entry["section"]
            entry["section_lead"] = leads[heading]
            entry["section_action"] = "reuse" if records.section(text, heading) is not None else "create"
    verification = verify_excerpts(payload["sources"], entries, private, single_excerpt=single_excerpt)
    plan = {"sources": sources, "entries": entries, "source_checks": verification, "remit_configured": remit is not None,
            "remit_status": remit_status(remit)}
    if not descriptive_intake or destination_docs is not None:
        risk_preview = evidence_reviews.preview(private, entries, sources, destination_docs=destination_docs)
        if risk_preview:
            plan["risk_preview"] = risk_preview
    if responses:
        plan["responses"] = responses
    plan["ingestion_reviews"] = ingestion_reviews(private, payload["sources"], entries, single_excerpt)
    return plan


def literal(value):
    # Preserve visible source text while keeping its Markdown from changing the record.
    return re.sub(r"[][{}\\*_~|\x60]", lambda match: f"&#{ord(match[0])};", escape(value, quote=False))


def edit_section(text, section_name, body):
    blocks = {name: (start, body_start, end) for name, start, body_start, end in records.section_blocks(text)}
    if section_name in blocks:
        _, body_start, end = blocks[section_name]
        return text[:body_start] + "\n" + body + "\n\n" + text[end:]
    start = blocks["Context controls"][0]
    return text[:start] + f"## {section_name}\n\n{body}\n\n" + text[start:]


def table_row(values):
    return "| " + " | ".join(values) + " |"


def section_body(body, heading):
    columns = records.CONTEXT_TABLES.get(heading)
    if not columns:
        return "" if records.PLACEHOLDER.fullmatch(body) else body
    if not body:
        return table_row(columns) + "\n" + table_row(["---"] * len(columns))
    return re.sub(r"^\| *(?:\{\{[^{}]+\}\} *\| *)+\n?", "", body, flags=re.M)


def scoped_text(entry, value):
    # User text is escaped. The marker distinguishes scoped entries from identical visible wording.
    if "product_area" in entry:
        area = entry["product_area"]
        return f"Product area {area} — {value} <!-- product-area:{area} -->"
    return value


def pm_topic_marker(entry):
    topic = entry.get("topic")
    if entry.get("scope") == "pm" and topic in pm_profile.WALKTHROUGH_TOPICS:
        return f" <!-- pm-topic:{topic} -->"
    return ""


def render_entry(entry, identifier):
    cite = f"[{identifier}] ({literal(entry['location'])}){pm_topic_marker(entry)}"
    quote = literal(entry["quote"])
    if "term" in entry:
        term = entry["term"]
        return table_row([literal(term["name"]), f"{scoped_text(entry, quote)} {cite}", literal(term["owner"]), literal(term["avoid"])])
    if "decision" in entry:
        decision = entry["decision"]
        evidence = f"{quote} {cite}"
        if "record_decision" in entry:
            approval = entry["record_decision"]
            evidence += (f". Confirmed for recording by {literal(approval['pm'])} on {approval['date']} "
                         f"({literal(approval['reference'])}): {literal(approval['reply'])}")
        return table_row([
            literal(decision["question"]), scoped_text(entry, literal(decision["scope"])), f"{literal(decision['person'])}, {decision['date']}",
            evidence, literal(decision["next_step"]),
        ])
    if "rule" in entry:
        label, statement = "Rule", literal(entry["rule"])
    elif "interpretation" in entry:
        label, statement = "Interpretation", literal(entry["interpretation"])
    else:
        label = ("Example" if entry.get("topic") == "examples" else
                 "Reported metric" if metric_checks.is_claim(entry["quote"]) else "Fact")
        statement = "Source excerpt"
    if label == "Reported metric":
        result = f"- {label}: {scoped_text(entry, quote)} {cite}"
    else:
        result = f"- {label}: {scoped_text(entry, statement)} {cite}\n  > {quote}"
    if "shared_area" in entry:
        result += f"\n  Shared area: {entry['shared_area']}"
    if "uncertainty" in entry:
        result += f"\n  Open question at capture: {scoped_text(entry, literal(entry['uncertainty']))}"
    if "answers" in entry:
        result += f"\n  Answers: {scoped_text(entry, literal(entry['answers']))}"
    return result


def mark_superseded(body, entry, replacement, known, date):
    previous = entry["supersedes"]
    prior_id = previous["source"]
    date_by_id = {ident: published for (_, published, _), ident in known.items()}
    if (prior_id == replacement or prior_id not in date_by_id
            or date_by_id[prior_id] not in {"undated", "unknown"} and date_by_id[prior_id] > date):
        raise ValueError("Use a dated replacement source for an earlier local entry")
    lines = body.splitlines()
    matches = []
    for index, row in enumerate(lines):
        if f"[{prior_id}]" not in row or task_context.SUPERSEDED.search(row):
            continue
        if "decision" in entry:
            columns = row.strip().strip("|").split("|")
            if len(columns) == 5 and [item.strip() for item in columns[:2]] == [
                literal(previous["entry"]), scoped_text(entry, literal(entry["decision"]["scope"]))
            ]:
                matches.append(index)
        else:
            old_rule = scoped_text(entry, literal(previous["entry"]))
            if row.startswith(f"- Rule: {old_rule} [{prior_id}] "):
                matches.append(index)
    if len(matches) != 1:
        raise ValueError("Identify exactly one active previous entry in the same section and scope")
    index = matches[0]
    status = f" *(Superseded by [{replacement}])*"
    if "decision" in entry:
        columns = lines[index].split("|")
        columns[4] = columns[4].rstrip() + status + " "
        lines[index] = "|".join(columns)
    else:
        lines[index] += status
    return "\n".join(lines)


def insert_entries(text, selected, sources, private, target, leads=None):
    leads = leads or {}
    if text.startswith("<!-- pm: product-area-context -->\n"):
        # The whole brief already identifies the area, including manually authored questions.
        selected = [{k: v for k, v in row.items() if k != "product_area"} for row in selected]
    rows, errors = records.table(text, "Sources", records.SOURCE_COLUMNS)
    if errors:
        raise ValueError("; ".join(errors))
    known = {(ref, published, checked): identifier for identifier, ref, published, checked in rows
             if re.fullmatch(r"S[1-9]\d*", identifier)}
    source_section = records.section(text, "Sources").strip()
    coverage = {key: (state, checked) for key, state, checked in records.SOURCE_COVERAGE.findall(source_section)}
    source_changed = False
    updates, originals = {}, {}
    for entry in selected:
        heading = entry["section"]
        if heading not in updates:
            originals[heading] = records.split_context_lead(records.section(text, heading) or "")
            updates[heading] = section_body(originals[heading][1], heading)
        if "question" in entry:
            bullet = f"- Unknown: {scoped_text(entry, literal(entry['question']))}{pm_topic_marker(entry)}"
        else:
            source = sources[entry["source"] - 1]
            reference = records.retarget_links(source["reference"], private / "README.md", target, private)
            key = (reference, source["date"], source["checked_on"])
            existing_id = next((old_id for (old_ref, published, _), old_id in known.items()
                                if (old_ref, published) == key[:2]
                                and f"\n{render_entry(entry, old_id)}\n" in f"\n{updates[heading]}\n"), None)
            identifier = existing_id or known.get(key)
            if not identifier:
                number = max((int(item[1:]) for item in known.values()), default=0) + 1
                identifier = known[key] = f"S{number}"
                source_section += f"\n| {identifier} | {key[0]} | {key[1]} | {source['checked_on']} |"
                source_changed = True
            state, checked = coverage.get(identifier, (None, ""))
            if source["coverage"] != state and source["checked_on"] >= checked:
                coverage[identifier] = source["coverage"], source["checked_on"]
                source_section += f"\n<!-- source-coverage:{identifier}:{source['coverage']}:{source['checked_on']} -->"
                source_changed = True
            if existing_id:
                continue
            if "supersedes" in entry:
                updates[heading] = mark_superseded(updates[heading], entry, identifier, known, source["date"])
            bullet = render_entry(entry, identifier)
        body = updates[heading]
        if f"\n{bullet}\n" not in f"\n{body}\n":
            updates[heading] = f"{body}\n{bullet}".strip()

    # If this batch both asks and answers a question, retain only the answer.
    for entry in selected:
        if "answers" in entry:
            heading = entry["section"]
            question = f"- Unknown: {scoped_text(entry, literal(entry['answers']))}{pm_topic_marker(entry)}"
            # A question with continuation lines needs a separate review of the whole entry.
            pattern = rf"^{re.escape(question)}(?:\n(?!\n*  )|\Z)"
            updates[heading] = re.sub(pattern, "", updates[heading], flags=re.M).strip()
    revised_leads = {entry["section"] for entry in selected if "lead" in entry}
    for heading, body in updates.items():
        previous, previous_body = originals[heading]
        lead = leads.get(heading, previous)
        if body == previous_body and (heading not in revised_leads or lead == previous):
            continue
        if lead is not None:
            body = f"{records.CONTEXT_LEAD}\n{lead}\n\n{body}"
        text = edit_section(text, heading, body)
    if source_changed:
        source_section = "\n".join(value for value in source_section.splitlines() if "{{S1}}" not in value)
        text = edit_section(text, "Sources", source_section)
    return text


def apply_profile(root, private, target, selected, sources, lint, publish):
    if any(row["scope"] != "pm" or row["section"] not in pm_profile.TOPICS.values() for row in selected):
        raise ValueError("Choose a PM topic before writing to the PM profile")
    original = target.read_bytes().decode("utf-8") if target.exists() else None
    text = "# PM context\n" if original is None else original
    previous_remit = pm_profile.parse(text)
    prefix, old_block, suffix = pm_profile.capture_block(text)
    newline = "\r\n" if "\r\n" in text else "\n"
    block = (old_block or "").replace("\r\n", "\n")
    headings = re.findall(r"^## (.+)$", block, re.M)
    if len(headings) != len(set(headings)) or any(h not in {*pm_profile.TOPICS.values(), "Sources"} for h in headings):
        raise ValueError("Repair duplicate or unexpected headings in the PM capture block")
    if old_block is None:
        columns = records.SOURCE_COLUMNS
        block = "## Sources\n\n" + table_row(columns) + "\n" + table_row(["---"] * len(columns)) + "\n"
    for heading in dict.fromkeys(row["section"] for row in selected):
        if heading not in headings:
            block = block.replace("## Sources\n", f"## {heading}\n\n## Sources\n", 1)
    candidate = insert_entries(block, selected, sources, private, target)
    if candidate == (old_block or "").replace("\r\n", "\n"):
        return False
    if old_block is None and prefix:
        prefix += "" if prefix.endswith(newline * 2) else newline if prefix.endswith(newline) else newline * 2
    after_end = newline if old_block is None or suffix or text.endswith(("\r", "\n")) else ""
    block = candidate.rstrip("\n").replace("\n", newline) + newline
    candidate = prefix + pm_profile.CAPTURE_START + newline + block + pm_profile.CAPTURE_END + after_end + suffix
    if pm_profile.capture_block(candidate) != (prefix, block, suffix) or pm_profile.parse(candidate) != previous_remit:
        raise ValueError("Cannot recover PM evidence and remit from Markdown. Check open fences before capture")
    errors = lint(root, target, candidate)
    if errors:
        raise ValueError("PM context capture failed validation:\n" + "\n".join(errors))
    with storage.writer_lock(private):
        storage.require_visible(private, pm_profile.PATH)
        if pm_profile.safe_path(private, pm_profile.LEGACY).exists() or REMIT_PATH in upgrades.source_paths(private):
            raise ValueError("Preserve the original or legacy PM profile before capturing")
        publish(target, original, candidate)
    return True


def apply(root, destination, plan, owner, lint, *, descriptive_intake=False, title=None, publish=None):
    if publish is None:
        publish = storage.replace_text
    private = storage.private_root(root)
    target = record_path(private, destination)
    original = target.read_text(encoding="utf-8") if target.is_file() else None
    marker = records.MARKER.match(original or "")
    selected = [entry for entry in plan["entries"] if entry["destination"] == destination]
    for entry in selected:
        if "decision" in entry:
            if "record_decision" not in entry:
                raise ValueError("Ask the PM to confirm recording the specific previewed decision. Supply record_decision.")
            evidence = plan["sources"][entry["source"] - 1]
            revision = decision_review(entry, destination, evidence)
            validate_decision_approval(entry, revision, evidence["checked_on"])
    responses = [r for r in plan.get("responses", []) if r["record"] == destination]
    if not selected and not (responses and original is not None):
        raise ValueError("Preview the proposed context record and select a destination from that preview")
    if destination == REMIT_PATH:
        if responses or any("risk" in entry for entry in selected):
            raise ValueError("Select a typed context record for this risk and its review history")
        return apply_profile(root, private, target, selected, plan["sources"], lint, publish)

    if original is None:
        kind = "context-note"
        if selected[0]["disposition"] == "new-brief":
            kind = layout.brief_kind(destination)
    else:
        kind = marker[1] if marker else None
    if kind not in records.CONTEXT_KINDS or records.context_location(kind, destination):
        raise ValueError("Use the existing record's workflow, or select a typed context section")
    template = (root / "templates" / f"{kind}.md").read_text(encoding="utf-8")
    order = records.heading_order(kind, template)
    if original is not None and records.structure_errors(kind, original, order):
        raise ValueError(f"{destination} needs a format change before this capture. Review and approve a conversion first.")
    topics = records.context_sections(kind)
    if any(entry["section"] not in topics and "heading" not in entry for entry in selected):
        raise ValueError("Use the existing record's workflow, or select a typed context section")
    if original is None:
        parent = product_path(selected[0]["product"]) if kind == "initiative-context" else None
        text = records.draft_text(root, kind, target, title=title, owner=owner, product_parent=parent)
        if kind == "product-area-context":
            reason = selected[0].get("record", {}).get("reason") or "Maintain the confirmed scope's current product context."
            trigger = "Review when the scope, its users, or supporting evidence changes."
            contract = filing.area_contract(private, destination, None, "maintained-reference", reason, trigger)
            text = text.replace("{{Area release, closed decision, new evidence, or changed product rules.}}", trigger)
            text = filing.add_contract(text, private, target, contract)
        if kind == "context-note":
            definitions = [entry["record"] for entry in selected]
            if any(value != definitions[0] for value in definitions):
                raise ValueError("Use one filing purpose and parent for this record")
            contract = note_filing(private, definitions[0])
            text = filing.add_contract(text, private, target, contract)
        unused = topics - {entry["section"] for entry in selected}
        for heading in sorted(unused):
            text = re.sub(rf"^## {re.escape(heading)}[ \t]*\n.*?(?=^## |\Z)",
                          "", text, count=1, flags=re.M | re.S)
    else:
        text = original
    headings = [heading for heading, *_ in records.section_blocks(text)]
    if len(set(headings)) != len(headings) or not records.CONTEXT_METADATA <= set(headings):
        raise ValueError("Use one section per heading and keep the context metadata before capture")
    candidate = insert_entries(text, selected, plan["sources"], private, target, section_leads(text, selected))
    candidate = records.ordered_sections(candidate, order)
    with storage.writer_lock(private):
        if not descriptive_intake or any("decision" in entry for entry in selected):
            if descriptive_intake:
                documents = {destination: task_context.read_document(Path(destination), target, text=candidate)}
            else:
                documents = task_context.context_documents(private, override=(destination, candidate))
            events = evidence_reviews.capture_events(private, documents, destination, selected, plan["sources"], responses,
                                                    check_initiatives=not descriptive_intake)
            if events:
                plan["risk_events"] = events
                candidate = evidence_reviews.append(candidate, events)
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
        storage.require_visible(private, destination)
        if "sources" in Path(destination).parts or destination in upgrades.source_paths(private):
            raise ValueError("Original source files cannot be context capture destinations")
        if original is None:
            filing.check_new(private, kind, destination, None)
            if kind == "context-note" and note_filing(private, selected[0]["record"]) != contract:
                raise ValueError("Topic or parent changed during capture. Preview the current filing decision")
        if kind in {"context-note", "product-area-context"}:
            filing.verify_note(private, destination, candidate)
        publish(target, original, candidate)
    return True
