"""Create typed drafts and check their resumable work state. No workflow runner."""

from datetime import date
from os.path import relpath
from pathlib import Path
from posixpath import normpath
import re

import layout
import storage
import upgrades
from urllib.parse import quote, unquote, urlsplit, urlunsplit
from uuid import uuid4

CONTEXT_KINDS = ("company-context", "product-context", "product-area-context", "initiative-context", "context-note")
OPPORTUNITY_KINDS = ("discovery-brief", "initiative-brief", "prioritization")
KINDS = (*CONTEXT_KINDS, "goal", "problem", "strategy", "experiment", "roadmap", *OPPORTUNITY_KINDS)
FIELDS = ("ID", "State", "Mode", "Last checkpoint", "Next action", "Waiting on", "Resume when")
STATES = {"draft", "active", "waiting", "complete"}
MODES = {"thought-partner", "quiet"}
MARKER = re.compile(r"\A<!-- pm: ([a-z-]+) -->\n")
PLACEHOLDER = re.compile(r"\{\{[^{}]+\}\}")
CONTEXT_FIELDS = ("Parent context", "Maintainer", "Last reviewed", "Review by", "Review triggers")
SOURCE_COLUMNS = ("ID", "Source", "Source date", "Checked on")
SOURCE_COVERAGE = re.compile(r"(?m)^<!-- source-coverage:(S[1-9]\d*):(partial|read):(\d{4}-\d{2}-\d{2}) -->$")
CONTEXT_METADATA = {"Context controls", "Sources", "Work state"}
CONTEXT_RESERVED_SECTIONS = CONTEXT_METADATA | {"Filing", "Evidence review history"}
SHARED_TOPICS = {
    "vocabulary": "Vocabulary",
    "decisions": "Decisions already closed",
    "examples": "What good output looks like",
    "data-boundaries": "Data boundaries",
    "reviews": "Review and approvals",
}
CONTEXT_TOPICS = {
    "company": {
        "organisation": "Organisation and scope", "markets": "Customers and markets",
        "business-model": "Business model", "direction": "Direction and goals",
        "operations": "How the business operates", "constraints": "Constraints and open questions",
        **SHARED_TOPICS,
    },
    "product": {
        "offer": "The product", "contribution": "The product",
        "purpose": "The vision", "vision": "The vision", "customers": "The users",
        "ownership": "Constraints", "constraints": "Constraints", "goals": "Goals, performance, and gaps",
        **SHARED_TOPICS,
    },
    "initiative": {
        "outcome": "Outcome and scope", "workflow": "Users and workflow",
        "constraints": "Dependencies and constraints", **SHARED_TOPICS,
    },
}
AREA_HEADINGS = {"The product": "Area scope and ownership", "The vision": "Area outcomes", "The users": "Area users and workflow"}
LEGACY_PRODUCT_TOPICS = {
    "purpose": "Purpose and boundaries", "vision": "Purpose and boundaries", "customers": "Customers and their work",
    "offer": "Current offer", "contribution": "Business contribution and market",
    "ownership": "Ownership and constraints", "constraints": "Ownership and constraints",
}
CONTEXT_TABLES = {
    "Vocabulary": ("Term", "Meaning", "Owner", "Avoid"),
    "Decisions already closed": ("Question", "Scope", "Person and date", "Evidence", "Next step"),
}
CONTEXT_LEAD = "<!-- pm: context-lead -->"
CONTEXT_LEADS = {
    "Context": "Consult when checking the evidence for the subject named in this note.",
    "Data boundaries": "Consult before selecting, sharing, or retaining data for PM work.",
    "Organisation and scope": "Consult when identifying the company, business unit, or product responsible for a decision.",
    "Customers and markets": "Consult when identifying buyers, users, partners, or markets for a product decision.",
    "Business model": "Consult when assessing how an opportunity affects customer value, revenue, or costs.",
    "Direction and goals": "Consult when checking whether proposed work supports company priorities.",
    "How the business operates": "Consult when finding decision owners, operating dependencies, or the teams involved in PM work.",
    "Constraints and open questions": "Consult before making commitments that depend on company limits or unresolved questions.",
    "The product": "Consult when checking the current offer, product scope, or business contribution.",
    "The vision": "Consult when assessing a proposal against the product's intended direction.",
    "The users": "Consult when identifying users and the work the product supports.",
    "Constraints": "Consult before committing work that depends on product ownership, obligations, or limits.",
    "Goals, performance, and gaps": "Consult when assessing progress or choosing the next product priority.",
    "Area scope and ownership": "Consult when deciding whether work belongs to this area or depends on its owners.",
    "Area outcomes": "Consult when assessing work against the outcomes for this product area.",
    "Area users and workflow": "Consult when checking which users and workflows are affected by area work.",
    "Outcome and scope": "Consult when checking which outcomes and commitments apply to this initiative.",
    "Users and workflow": "Consult when assessing who the initiative affects and how their work changes.",
    "Dependencies and constraints": "Consult before making commitments that depend on initiative handoffs or limits.",
    "Vocabulary": "Consult when choosing terms for plans, decisions, and communications.",
    "Decisions already closed": "Consult before revisiting a decision or acting on its approved scope.",
    "What good output looks like": "Consult when preparing a deliverable that has an approved example or standard.",
    "Review and approvals": "Consult when deciding who must review or approve the work.",
    "Purpose and boundaries": "Consult when assessing whether proposed work fits the product's direction and boundaries.",
    "Customers and their work": "Consult when identifying customers and the work the product supports.",
    "Current offer": "Consult when checking what the product currently offers.",
    "Business contribution and market": "Consult when assessing the product's market or contribution to the business.",
    "Ownership and constraints": "Consult before making commitments that depend on product ownership or limits.",
}
SOURCE_REFERENCE = re.compile(r"\[S[1-9]\d*\]")
CONTEXT_ENTRY = re.compile(r"- (Fact|Rule|Example|Interpretation|Reported metric|Assumption|Unknown): (.+)")
WORKING_SECTIONS = ("Scope", "Evidence", "Next action")
HTML_BLOCK_TAGS = (
    "address|article|aside|base|basefont|blockquote|body|caption|center|col|colgroup|dd|details|dialog|dir|div|dl|dt|"
    "fieldset|figcaption|figure|footer|form|frame|frameset|h[1-6]|head|header|hr|html|iframe|legend|li|link|main|menu|"
    "menuitem|nav|noframes|noscript|ol|optgroup|option|p|param|search|section|summary|table|tbody|td|tfoot|th|thead|"
    "title|tr|track|ul"
)
HTML_TAG_ATTRIBUTE = r'''[a-z_:][a-z0-9_.:-]*(?:[ \t]*=[ \t]*(?:[^\s"'=<>`]+|"[^"\n]*"|'[^'\n]*'))?'''
HTML_STANDALONE_TAG = rf"(?:<[a-z][a-z0-9-]*(?:[ \t]+{HTML_TAG_ATTRIBUTE})*[ \t]*/?>|</[a-z][a-z0-9-]*[ \t]*>)"
HTML_TO_BLANK_LINE = r"(?:\n(?![ \t]*(?:\n|\Z))[^\n]*)*"
HIDDEN_SECTION_MARKUP = re.compile(
    # Match a whole fence first so literal comments or tags inside it stay local to the example.
    r"^ {0,3}(?P<fence>(?P<mark>[`~])(?P=mark){2,})(?!(?P=mark))[^\n]*(?:\n|\Z)"
    r".*?(?:^ {0,3}(?P=fence)(?P=mark)*[ \t]*(?=\n|\Z)|\Z)"
    r"|<!--.*?(?:-->|\Z)"
    r"|^ {0,3}<(?P<tag>pre|script|style|textarea)(?=[\s>/]).*?(?:</(?P=tag)\s*>|\Z)"
    # CommonMark declarations and processing instructions close with their own delimiters.
    r"|^ {0,3}(?:<\?.*?(?:\?>|\Z)|<!\[CDATA\[.*?(?:\]\]>|\Z)|<![a-z].*?(?:>|\Z))"
    # Ordinary block tags end at a blank line. Treat a standalone custom tag the same
    # way if there is a heading immediately after it that could be parsed as HTML.
    rf"|^ {{0,3}}</?(?:{HTML_BLOCK_TAGS})(?=[\s>/])[^\n]*{HTML_TO_BLANK_LINE}"
    rf"|^ {{0,3}}{HTML_STANDALONE_TAG}[ \t]*(?=\n|\Z){HTML_TO_BLANK_LINE}",
    re.I | re.M | re.S,
)

def work_state(text):
    count = len(re.findall(r"^## Work state\s*$", text, re.M))
    if count != 1:
        return {}, ["use exactly one Work state section"]
    section = re.search(r"^## Work state\s*\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    if not section:
        return {}, ["missing Work state section"]
    values, errors = {}, []
    for line in section[1].splitlines():
        if not line.strip().startswith("|"):
            continue
        row = line.strip().strip("|").split("|", 1)
        if len(row) != 2:
            continue
        name, value = (part.strip() for part in row)
        if name == "Field" or set(name) <= {"-", ":", " "}:
            continue
        if name in values:
            errors.append(f"duplicate work-state field: {name}")
        if name not in FIELDS:
            errors.append(f"unknown work-state field: {name}")
        values[name] = value
    for field in FIELDS:
        if not values.get(field):
            errors.append(f"missing work-state field: {field}")
    return values, errors


def specific(value):
    return bool(value and not PLACEHOLDER.search(value)
                and value.casefold() not in {"none", "unknown", "pending", "tbd"})


def state_errors(text):
    values, errors = work_state(text)
    state = values.get("State")
    if state not in STATES:
        errors.append("State must be draft, active, waiting, or complete")
    if values.get("Mode") not in MODES:
        errors.append("Mode must be thought-partner or quiet")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{2,79}", values.get("ID", "")):
        errors.append("set a stable ID; use the new command for a fresh draft")
    if state in {"active", "waiting", "complete"}:
        checkpoint = values.get("Last checkpoint", "")
        try:
            date.fromisoformat(checkpoint[:10])
            if not specific(checkpoint) or not checkpoint[10:].strip(" :.-"):
                raise ValueError()
        except ValueError:
            errors.append("Last checkpoint needs a valid ISO date and a result")
    if state in {"active", "waiting"} and not specific(values.get("Next action")):
        errors.append("Next action must name a concrete step")
    if state == "waiting":
        for field in ("Waiting on", "Resume when"):
            if not specific(values.get(field)):
                errors.append(f"{field} must name a dependency or trigger")
    if state == "complete":
        if PLACEHOLDER.search(text):
            errors.append("resolve placeholders before declaring the artifact complete")
        if values.get("Waiting on", "").casefold() != "none":
            errors.append("complete work cannot retain a waiting dependency")
    return values.get("ID"), errors


def visible_section_markup(text):
    return HIDDEN_SECTION_MARKUP.sub(lambda match: re.sub(r"[^\r\n]", " ", match[0]), text)


def section_blocks(text):
    """Find visible Markdown headings while keeping original section offsets."""
    positions = [(match[1].strip(), match.start(), match.end())
                 for match in re.finditer(r"(?m)^## ([^\r\n]+)(?:\r?\n|$)", visible_section_markup(text))]
    return [(name, start, body, end) for (name, start, body), end in
            zip(positions, [item[1] for item in positions[1:]] + [len(text)])]

def section(text, name):
    matches = [(body, end) for heading, _, body, end in section_blocks(text) if heading == name]
    return re.sub(r"^(?:[ \t]*\r?\n)+", "", text[slice(*matches[0])]) if len(matches) == 1 else None


def heading_order(kind, template):
    order = [name for name, *_ in section_blocks(template)]
    if kind in ("context-note", "product-area-context") and "Context controls" in order:
        order.insert(order.index("Context controls"), "Filing")
    if kind in CONTEXT_KINDS and "Context controls" in order:
        order.insert(order.index("Context controls"), "Evidence review history")
    if kind == "product-context":
        for topic, old in LEGACY_PRODUCT_TOPICS.items():
            current = CONTEXT_TOPICS["product"][topic]
            if old not in order and current in order:
                order.insert(order.index(current) + 1, old)
    return order


def record_order(text, order):
    # A released template may acquire a heading that an older personalized
    # draft already placed elsewhere. Preserve that draft's placement while
    # enforcing core order for all its other standard sections.
    preamble = text.split("\n## ", 1)[0]
    match = re.search(r"(?m)^<!-- studio:positioned ([^\n ]+) -->$", preamble)
    if not match:
        return order
    positioned = {unquote(name) for name in match[1].split(",")} - CONTEXT_RESERVED_SECTIONS - {"Parent initiative"}
    return [name for name in order if name not in positioned]


def ordered_sections(text, order):
    blocks = section_blocks(text)
    positions = {name: index for index, name in enumerate(record_order(text, order))}
    standard = iter(sorted((block for block in blocks if block[0] in positions), key=lambda item: positions[item[0]]))
    sorted_blocks = [next(standard) if block[0] in positions else block for block in blocks]
    if sorted_blocks == blocks:
        return text
    return text[:blocks[0][1]] + "".join(
        text[start:end].rstrip("\r\n") + "\n\n" for _, start, _, end in sorted_blocks
    ).rstrip("\n") + "\n"


def working_errors(text):
    errors = []
    sections = [name for name, *_ in section_blocks(text) if name in WORKING_SECTIONS]
    if sections != list(WORKING_SECTIONS):
        errors.append("Use Scope, Evidence, and Next action sections in that order for working Markdown")
    for name in WORKING_SECTIONS:
        if name in sections and not (section(text, name) or "").strip():
            errors.append(f"Give {name} a concrete entry or state the current gap")
    return errors


def structure_errors(kind, text, order):
    headings = [name for name, *_ in section_blocks(text)]
    sections = set(headings)
    errors = []
    positions = record_order(text, order)
    if [name for name in headings if name in positions] != [name for name in positions if name in sections]:
        errors.append(f"use the section order from the {kind} template")
    if kind in CONTEXT_KINDS:
        errors.extend(f"unknown context section: {name}. Use a supported heading or a sourced section with a lead"
                      for name in sorted(sections - set(order) - context_content(kind, text)))
    return errors


def table(text, name, columns):
    body = section(text, name)
    if body is None:
        return [], [f"use exactly one {name} section"]
    rows = []
    for line in body.splitlines():
        if line.strip().startswith("|"):
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if all(re.fullmatch(r":?-+:?", cell) for cell in cells):
                continue
            rows.append(cells)
    if not rows or tuple(rows[0]) != columns:
        return [], [f"{name} table columns must be: {', '.join(columns)}"]
    if any(len(row) != len(columns) for row in rows[1:]):
        return [], [f"{name} table rows need {len(columns)} cells"]
    return rows[1:], []


def area_brief_path(product, area):
    return layout.area(product, area)


def is_area_path(path):
    return layout.brief_kind(path) == "product-area-context"


def context_location(kind, path):
    if kind in OPPORTUNITY_KINDS:
        import opportunities
        return opportunities.location_error(kind, path)
    if kind == "context-note":
        try:
            owner = layout.entity(path)
            relative = Path(path).relative_to(owner)
        except ValueError:
            return "File a context note under its context entity"
        if (owner == Path("context/pm") or len(relative.parts) not in (1, 2)
                or relative.suffix != ".md" or not layout.SLUG.fullmatch(relative.stem)
                or relative.name in {"overview.md", "context.md"} or
                (len(relative.parts) == 2 and not layout.SLUG.fullmatch(relative.parts[0]))):
            return "Use an entity subject or one topic directory for a context note"
    elif kind in CONTEXT_KINDS and layout.brief_kind(path) != kind:
        return f"Use the canonical entity overview path for {kind}"
    elif kind in layout.WORK_FOLDERS and not layout.valid_work(path, kind):
        return f"File {kind} work under workspace/{layout.WORK_FOLDERS[kind]}/"
    return None


def existing_briefs(private, canonical, scope):
    """Only the typed overview can be the active authority after layout alignment."""
    canonical = str(canonical)
    path = private / canonical
    if path.resolve() != path or not path.is_file() or canonical in upgrades.source_paths(private):
        return []
    with path.open("rb") as stream:
        marker = MARKER.match(stream.readline(128).decode("utf-8", errors="replace").replace("\r\n", "\n"))
    return [canonical] if marker and marker[1] == f"{scope}-context" else []


def product_briefs(private, product):
    return existing_briefs(private, layout.product(product), "product")


def initiative_home(private, product, initiative):
    qualified = layout.initiative(initiative, product)
    legacy = layout.initiative(initiative)
    if (private / qualified).exists() or not existing_briefs(private, legacy, "initiative"):
        return qualified
    text = (private / legacy).read_text(encoding="utf-8")
    return legacy if parent_reference(legacy, text) == layout.product(product) else qualified


def parent_reference(path, text):
    controls, _ = table(text, "Context controls", ("Field", "Value"))
    value = dict(controls).get("Parent context", "")
    match = re.fullmatch(r"\[[^\]]+\]\(([^\s)]+)\)", value)
    if not match:
        return None
    parsed = urlsplit(match[1])
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
        return None
    return normpath((Path(path).parent / unquote(parsed.path)).as_posix())


def context_sections(kind):
    if kind == "context-note":
        return {"Context"}
    scope = kind.removesuffix("-context")
    sections = set(CONTEXT_TOPICS["product" if scope == "product-area" else scope].values())
    if scope == "product-area":
        sections = {AREA_HEADINGS.get(name, name) for name in sections}
    if scope == "product":
        sections.update(LEGACY_PRODUCT_TOPICS.values())
    return sections


def context_content(kind, text):
    standard = context_sections(kind) | CONTEXT_TABLES.keys()
    return {name for name, _, start, end in section_blocks(text)
            if name in standard
            or (name not in CONTEXT_RESERVED_SECTIONS and split_context_lead(text[start:end])[0] is not None)}


def split_context_lead(body):
    """Return a marked navigation lead and the substantive content beneath it."""
    body = body.strip()
    first, _, rest = body.partition("\n")
    if first != CONTEXT_LEAD:
        return None, body
    lead, _, body = rest.partition("\n")
    return lead, body.strip()


def valid_context_lead(lead):
    return (specific(lead) and lead == lead.strip() and lead.splitlines() == [lead]
            and re.match(r"\w", lead) is not None and "<" not in lead and ">" not in lead)


def context_entries(body):
    entries, unlabelled = [], False
    current = None
    for line in body.splitlines():
        if not line.strip() or PLACEHOLDER.fullmatch(line.strip()):
            continue
        entry = CONTEXT_ENTRY.fullmatch(line)
        if entry:
            current = [entry[1], entry[2]]
            entries.append(current)
        elif line.startswith("  ") and current:
            current[1] += " " + line.strip()
        else:
            current = None
            unlabelled = True
    return entries, unlabelled


def context_table_errors(text, name, draft):
    columns = CONTEXT_TABLES[name]
    rows, errors = table(text, name, columns)
    _, body = split_context_lead(section(text, name) or "")
    if any(line.strip() and not line.strip().startswith("|") for line in body.splitlines()):
        errors.append(f"{name} needs a Markdown table")
    for row in rows:
        if draft and all(PLACEHOLDER.fullmatch(cell) for cell in row):
            continue
        if any(not cell or PLACEHOLDER.search(cell) for cell in row):
            errors.append(f"{name} rows need every field")
            continue
        if name == "Vocabulary" and not SOURCE_REFERENCE.search(row[1]):
            errors.append("Vocabulary needs a source reference in Meaning")
        if name == "Decisions already closed":
            person, separator, decided_on = row[2].rpartition(", ")
            try:
                decided = date.fromisoformat(decided_on)
                if not separator or not specific(person) or decided.isoformat() != decided_on or decided > date.today():
                    raise ValueError()
            except ValueError:
                errors.append("Closed decisions need a named person and a YYYY-MM-DD decision date")
            if not SOURCE_REFERENCE.search(row[3]):
                errors.append("Closed decisions need a source reference in Evidence")
    return errors


def local_source_links(reference):
    for name in re.findall(r"\[[^\]\n]+\]\((<[^>\n]+>|[^\s)]+)\)", reference):
        target = name.strip("<>")
        if re.match(r"(?:[a-z][a-z0-9+.-]*:|//)", target, re.I):
            continue
        parsed = urlsplit(target)
        if not parsed.scheme and not parsed.netloc and parsed.path:
            yield Path(unquote(parsed.path))


def uses_customization_source(record, reference):
    # A bibliography can name a Studio-relative file directly or link from its record.
    name = Path(reference)
    if layout.is_customization(name) or (len(name.parts) >= 2 and name.parts[0] in storage.PRIVATE_ROOTS
                                         and layout.is_customization(Path(*name.parts[1:]))):
        return True
    return any(layout.is_customization(normpath((Path(record).parent / link).as_posix()))
               for link in local_source_links(reference))


def context_errors(path, text, kind, texts, content_sections, template=False):
    errors, parent = [], None
    state = work_state(text)[0].get("State")
    draft = state == "draft"
    if not template and context_location(kind, path):
        errors.append(context_location(kind, path))
    rows, problems = table(text, "Context controls", ("Field", "Value"))
    errors.extend(problems)
    controls = {}
    for name, value in rows:
        if name in controls:
            errors.append(f"duplicate context control: {name}")
        if name not in CONTEXT_FIELDS:
            errors.append(f"unknown context control: {name}")
        controls[name] = value
    for name in CONTEXT_FIELDS:
        if not controls.get(name):
            errors.append(f"missing context control: {name}")
    for name in ("Maintainer", "Review triggers"):
        if not draft and not specific(controls.get(name)):
            errors.append(f"{name} needs a concrete value before context leaves draft")

    def day(value, label, past=False, unreviewed=False):
        if draft and (PLACEHOLDER.fullmatch(value) or (unreviewed and value == "not reviewed")):
            return None
        try:
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                raise ValueError()
            result = date.fromisoformat(value)
        except ValueError:
            errors.append(f"{label} needs a valid YYYY-MM-DD date")
            return None
        if past and result > date.today():
            errors.append(f"{label} cannot be in the future")
        return result

    reviewed = day(controls.get("Last reviewed", ""), "Last reviewed", past=True, unreviewed=True)
    review_by = controls.get("Review by", "")
    due = None if review_by == "event-driven" else day(review_by, "Review by")
    if reviewed and due and due < reviewed:
        errors.append("Review by cannot precede Last reviewed")
    if not draft and due and due < date.today():
        errors.append("context review is overdue; review the record and its sources")

    value = controls.get("Parent context", "")
    if value == "none" and kind in {"company-context", "context-note"}:
        pass
    elif draft and PLACEHOLDER.fullmatch(value):
        pass
    else:
        link = re.fullmatch(r"\[[^\]\n]+\]\(([^\s)]+)\)", value)
        parsed = urlsplit(link[1]) if link else None
        if not parsed or parsed.scheme or parsed.netloc or not parsed.path:
            errors.append("Parent context needs one local Markdown link")
        else:
            parent = normpath((Path(path).parent / unquote(parsed.path)).as_posix())
            marker = MARKER.match(texts.get(parent, ""))
            if kind in {"initiative-context", "product-area-context"}:
                product_path = layout.brief_kind(parent) == "product-context"
                same_product = (Path(path).parts[:2] == ("context", "initiatives")
                                or Path(path).parts[:3] == Path(parent).parts[:3])
                if not product_path or not same_product or not marker or marker[1] != "product-context":
                    errors.append("Parent context must link to the same product's product-context record")
            elif not parent.startswith("context/") or not marker or marker[1] != "company-context":
                errors.append("Parent context must link to a company-context record inside oryx")

    rows, problems = table(text, "Sources", SOURCE_COLUMNS)
    errors.extend(problems)
    sources = set()
    for identifier, reference, source_date, checked in rows:
        if all(PLACEHOLDER.fullmatch(cell) for cell in (identifier, reference, source_date, checked)):
            continue
        if not re.fullmatch(r"S[1-9]\d*", identifier):
            errors.append("source IDs must use S1, S2, and so on")
        if identifier in sources:
            errors.append(f"duplicate source ID: {identifier}")
        sources.add(identifier)
        if not specific(reference):
            errors.append(f"{identifier}: Source needs a link or a named person and discussion reference")
        if uses_customization_source(path, reference):
            errors.append(f"{identifier}: Cite the underlying decision evidence. Studio customizations describe working methods.")
        published = None
        if source_date not in {"unknown", "undated"}:
            published = day(source_date, f"{identifier} Source date", past=True)
        checked_on = day(checked, f"{identifier} Checked on", past=True)
        if not specific(checked):
            errors.append(f"{identifier}: Checked on must record an actual source check")
        if published and checked_on and published > checked_on:
            errors.append(f"{identifier}: Source date cannot follow Checked on")

    claims = re.sub(r"(?ms)^## Sources[ \t]*$.*?(?=^## |\Z)", "", text)
    for reference in set(re.findall(r"\[(S[1-9]\d*)\]", claims)) - sources:
        errors.append(f"unknown source reference: {reference}")
    substantive = False
    for name in sorted(content_sections):
        body = section(text, name)
        if body is None:
            errors.append(f"use exactly one {name} section")
            continue
        lead, body = split_context_lead(body)
        if lead is not None and not valid_context_lead(lead):
            errors.append(f"{name}: give the section a short prose lead")
        if name in CONTEXT_TABLES:
            errors.extend(context_table_errors(text, name, draft))
            substantive = substantive or bool(table(text, name, CONTEXT_TABLES[name])[0])
            continue
        if not body and not draft:
            errors.append(f"{name} needs an entry or an explicit Unknown")
        entries, unlabelled = context_entries(body)
        if unlabelled:
            errors.append(f"{name}: use labelled context bullets")
        for label, claim in entries:
            substantive = substantive or label in {"Fact", "Rule", "Example", "Reported metric"}
            if label in {"Fact", "Rule", "Example", "Reported metric"} and not PLACEHOLDER.fullmatch(claim) and not SOURCE_REFERENCE.search(claim):
                errors.append(f"{name}: {label} entries need a source reference such as [S1]")
    if state == "complete" and not substantive:
        errors.append("complete context needs a sourced fact, rule, example, or structured entry")
    return errors, parent


def validate(texts, *, legacy_structure=()):
    errors, contracts, orders, ids, parents = [], {}, {}, {}, {}
    for path in texts:
        if path.startswith("templates/") and path.endswith(".md") and path != "templates/README.md":
            if Path(path).relative_to("templates").as_posix() not in {f"{kind}.md" for kind in KINDS}:
                errors.append(f"{path}: unregistered template; add only requested artifact types")
    for kind in KINDS:
        path = f"templates/{kind}.md"
        text = texts.get(path, "")
        marker = MARKER.match(text)
        values, problems = work_state(text)
        if not marker or marker[1] != kind:
            problems.append("template marker must match its filename")
        if values.get("State") != "draft":
            problems.append("templates must start as drafts")
        if values.get("Mode") != "thought-partner":
            problems.append("templates must start in thought-partner mode")
        contracts[kind] = {name for name, *_ in section_blocks(text)}
        if "Context controls" in contracts[kind] or kind not in CONTEXT_KINDS:
            orders[kind] = heading_order(kind, text)
        if kind in CONTEXT_KINDS:
            content = contracts[kind] - CONTEXT_METADATA
            if content - context_sections(kind):
                problems.append("template contains an unknown context section")
            extra, _ = context_errors(path, text, kind, texts, content, template=True)
            problems.extend(extra)
        errors.extend(f"{path}: {problem}" for problem in problems)
    for path, text in texts.items():
        if not path.endswith(".md") or path.startswith("templates/"):
            continue
        marker = MARKER.match(text)
        if not marker:
            if text.startswith("<!-- pm:"):
                errors.append(f"{path}: malformed artifact marker")
            continue
        kind = marker[1]
        if kind not in contracts:
            errors.append(f"{path}: unknown artifact type: {kind}")
            continue
        headings = [name for name, *_ in section_blocks(text)]
        sections = set(headings)
        if path not in legacy_structure:
            errors.extend(f"{path}: {error}" for error in structure_errors(kind, text, orders.get(kind, [])))
        required = CONTEXT_METADATA if kind in CONTEXT_KINDS else contracts[kind]
        if kind == "strategy":
            required = required - {"When"}  # Earlier strategy records predate this prompt.
        for missing in sorted(required - sections):
            errors.append(f"{path}: missing section: {missing}")
        identifier, problems = state_errors(text)
        if kind in CONTEXT_KINDS:
            if "Evidence review history" in sections:
                import evidence_reviews
                try:
                    evidence_reviews.history(text)
                except (TypeError, ValueError) as exc:
                    problems.append(f"Invalid evidence review history: {exc}")
            # Older versions allowed custom prose outside the standard sections.
            # Apply the entry contract when a custom section adopts a lead.
            extra, parent = context_errors(path, text, kind, texts, context_content(kind, text))
            problems.extend(extra)
            if parent:
                parents[path] = parent
        elif context_location(kind, path):
            problems.append(context_location(kind, path))
        if identifier and identifier in ids:
            errors.append(f"{path}: duplicate ID also used by {ids[identifier]}")
        if identifier:
            ids[identifier] = path
        errors.extend(f"{path}: {problem}" for problem in problems)
    for path in parents:
        seen, current = set(), path
        while current in parents:
            if current in seen:
                errors.append(f"{path}: parent context forms a cycle")
                break
            seen.add(current)
            current = parents[current]
    import opportunities
    return errors + opportunities.validate(texts)


def retarget_links(text, source, target, root, copies=None):
    """Keep links to shared rules valid after a template enters the workspace."""
    def retarget(match):
        label, link = match.groups()
        parsed = urlsplit(link.strip("<>"))
        if parsed.scheme or parsed.netloc or not parsed.path:
            return match[0]
        linked = (source.parent / unquote(parsed.path)).resolve()
        linked = (copies or {}).get(linked, linked)
        if root not in linked.parents and linked != root:
            raise ValueError("Template link leaves oryx")
        relative_link = quote(Path(relpath(linked, target.parent)).as_posix())
        return f"[{label}]({urlunsplit(('', '', relative_link, parsed.query, parsed.fragment))})"
    return re.sub(r"\[([^\]\n]+)\]\((<[^>\n]+>|[^\s)]+)\)", retarget, text)


def create(root, kind, destination, title=None, owner="", filing_contract=None, product_parent=None, initiative_id=None):
    root = root.resolve()
    relative = Path(destination)
    if relative.is_absolute() or relative.parts[:1] not in (("context",), ("workspace",)):
        raise ValueError("Create PM artifacts under context/ or workspace/ with a private-relative path")
    workspace = storage.private_root(root)
    if workspace.is_symlink() or not (workspace / ".git").is_dir() or (workspace / ".git").is_symlink():
        raise ValueError("Initialise the private repository before PM work")
    target = workspace / relative
    if target.resolve() != target or target.suffix != ".md":
        raise ValueError("Use a direct Markdown path inside oryx")
    storage.require_visible(workspace, relative.as_posix())
    if kind not in KINDS:
        raise ValueError(f"Unknown template: {kind}")
    if context_location(kind, relative):
        raise ValueError(context_location(kind, relative))
    text = draft_text(root, kind, target, title, owner, product_parent=product_parent, initiative_id=initiative_id)
    if filing_contract:
        if kind == "product-area-context":
            text = text.replace("{{Area release, closed decision, new evidence, or changed product rules.}}", filing_contract["trigger"])
        import filing
        text = filing.add_contract(text, workspace, target, filing_contract)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8", newline="\n") as output:
        output.write(text)
    return target


def draft_text(root, kind, target, title=None, owner="", product_parent=None, initiative_id=None):
    source = root / "templates" / f"{kind}.md"
    if source.resolve() != source:
        raise ValueError("Templates must be regular files inside oryx")
    text = source.read_text(encoding="utf-8")
    import customizations
    text = customizations.draft_template(root, kind, target, text)
    marker = MARKER.match(text)
    if not marker or marker[1] != kind or work_state(text)[1]:
        raise ValueError("Repair the source template before creating a draft")
    if kind in layout.INITIATIVE_BRIEFS:
        if not initiative_id or (section(text, "Parent initiative") or "").strip() != "{{initiative_id}}":
            raise ValueError("Use the registered initiative ID and the brief template's Parent initiative section")
        text = text.replace("{{initiative_id}}", initiative_id)
    if kind == "product-area-context" and title is None:
        title = target.parent.name.replace("-", " ").capitalize() + " context"
    title = title or target.stem.replace("-", " ").capitalize()
    if "\n" in title or "\r" in title:
        raise ValueError("Use a single line for the title")
    text = text.replace("{{title}}", title)
    if owner:
        text = text.replace("{{owner}}", owner)
    text = text.replace("{{id}}", f"{kind}-{uuid4().hex[:12]}")
    text = text.replace("{{date and result}}", f"{date.today().isoformat()}: Draft created.")
    text = retarget_links(text, source, target, root)
    if kind in {"product-context", "initiative-context", "product-area-context"}:
        private = storage.private_root(root)
        if kind == "product-context":
            canonical = layout.COMPANY
            expected, label = "company-context", "Company context"
            placeholder = "{{Local Markdown link to the relevant company-context record.}}"
        else:
            if kind == "product-area-context":
                canonical = layout.product(target.relative_to(private).parts[2])
            else:
                canonical = product_parent
                if not canonical or layout.brief_kind(canonical) != "product-context":
                    raise ValueError("Give the initiative's owning product overview as its parent")
            expected, label = "product-context", "Product context"
            placeholder = "{{Local Markdown link to the same product's product-context record.}}"
        if existing_briefs(private, canonical, expected.removesuffix("-context")):
            link = quote(Path(relpath(private / canonical, target.parent)).as_posix())
            text = text.replace(placeholder, f"[{label}]({link})")
        elif kind in {"initiative-context", "product-area-context"}:
            raise ValueError("Establish the owning product overview before filing this context")
    return text
