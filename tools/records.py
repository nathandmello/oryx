"""Create typed drafts and check their resumable work state. No workflow runner."""

from datetime import date
from os.path import relpath
from pathlib import Path
from posixpath import normpath
import re
from urllib.parse import unquote, urlsplit, urlunsplit
from uuid import uuid4

KINDS = ("company-context", "product-context", "goal", "problem", "strategy", "experiment", "roadmap")
FIELDS = ("ID", "State", "Mode", "Last checkpoint", "Next action", "Waiting on", "Resume when")
STATES = {"draft", "active", "waiting", "complete"}
MODES = {"thought-partner", "quiet"}
MARKER = re.compile(r"\A<!-- pm: ([a-z-]+) -->\n")
PLACEHOLDER = re.compile(r"\{\{[^{}]+\}\}")
CONTEXT_FIELDS = ("Parent context", "Maintainer", "Last reviewed", "Review by", "Review triggers")
SOURCE_COLUMNS = ("ID", "Source", "Source date", "Checked on")


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


def section(text, name):
    matches = re.findall(r"^## " + re.escape(name) + r"\s*\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    return matches[0] if len(matches) == 1 else None


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


def context_location(kind, path):
    parts = Path(path).parts
    if kind == "company-context" and parts[:1] != ("context",):
        return "company context belongs under context/"
    if kind == "product-context" and (parts[:1] != ("products",) or len(parts) < 3):
        return "product context belongs under products/<product>/"
    return None


def context_errors(path, text, kind, texts, content_sections, template=False):
    errors, parent = [], None
    draft = work_state(text)[0].get("State") == "draft"
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
    due = day(controls.get("Review by", ""), "Review by")
    if reviewed and due and due < reviewed:
        errors.append("Review by cannot precede Last reviewed")
    if not draft and due and due < date.today():
        errors.append("context review is overdue; review the record and its sources")

    value = controls.get("Parent context", "")
    if value == "none" and kind == "company-context":
        pass
    elif draft and PLACEHOLDER.fullmatch(value):
        pass
    else:
        link = re.fullmatch(r"\[[^\]\n]+\]\(([^\s)]+)\)", value)
        parsed = urlsplit(link[1]) if link else None
        if not parsed or parsed.scheme or parsed.netloc or not parsed.path:
            errors.append("Parent context needs one local Markdown link to company context")
        else:
            parent = normpath((Path(path).parent / unquote(parsed.path)).as_posix())
            marker = MARKER.match(texts.get(parent, ""))
            if not parent.startswith("context/") or not marker or marker[1] != "company-context":
                errors.append("Parent context must link to a company-context record inside PM Hub")

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
        published = None
        if source_date not in {"unknown", "undated"}:
            published = day(source_date, f"{identifier} Source date", past=True)
        checked_on = day(checked, f"{identifier} Checked on", past=True)
        if not specific(checked):
            errors.append(f"{identifier}: Checked on must record an actual source check")
        if published and checked_on and published > checked_on:
            errors.append(f"{identifier}: Source date cannot follow Checked on")

    for reference in set(re.findall(r"\[(S[1-9]\d*)\]", text)) - sources:
        errors.append(f"unknown source reference: {reference}")
    for name in sorted(content_sections):
        body = section(text, name)
        if body is None:
            errors.append(f"use exactly one {name} section")
            continue
        if not body.strip() and not draft:
            errors.append(f"{name} needs an entry or an explicit Unknown")
        entries, current = [], None
        for line in body.splitlines():
            if not line.strip() or PLACEHOLDER.fullmatch(line.strip()):
                continue
            entry = re.fullmatch(r"- (Fact|Interpretation|Assumption|Unknown): (.+)", line)
            if entry:
                current = [entry[1], entry[2]]
                entries.append(current)
            elif line.startswith("  ") and current:
                current[1] += " " + line.strip()
            else:
                errors.append(f"{name}: use labelled Fact, Interpretation, Assumption, or Unknown bullets")
        for label, claim in entries:
            if label == "Fact" and not PLACEHOLDER.fullmatch(claim) and not re.search(r"\[S[1-9]\d*\]", claim):
                errors.append(f"{name}: Fact entries need a source reference such as [S1]")
    return errors, parent


def validate(texts):
    errors, contracts, ids, parents = [], {}, {}, {}
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
        contracts[kind] = set(re.findall(r"^## (.+)$", text, re.M))
        if kind in {"company-context", "product-context"}:
            content = contracts[kind] - {"Context controls", "Sources", "Work state"}
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
        sections = set(re.findall(r"^## (.+)$", text, re.M))
        for missing in sorted(contracts[kind] - sections):
            errors.append(f"{path}: missing section: {missing}")
        identifier, problems = state_errors(text)
        if kind in {"company-context", "product-context"}:
            content = contracts[kind] - {"Context controls", "Sources", "Work state"}
            extra, parent = context_errors(path, text, kind, texts, content)
            problems.extend(extra)
            if parent:
                parents[path] = parent
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
    return errors


def retarget_links(text, source, target, root, copies=None):
    """Keep links to shared rules valid after a template enters the workspace."""
    def retarget(match):
        label, link = match.groups()
        parsed = urlsplit(link)
        if parsed.scheme or parsed.netloc or not parsed.path:
            return match[0]
        linked = (source.parent / unquote(parsed.path)).resolve()
        linked = (copies or {}).get(linked, linked)
        if root not in linked.parents and linked != root:
            raise ValueError("Template link leaves PM Hub")
        relative_link = Path(relpath(linked, target.parent)).as_posix()
        return f"[{label}]({urlunsplit(('', '', relative_link, parsed.query, parsed.fragment))})"
    return re.sub(r"\[([^\]\n]+)\]\(([^\s)]+)\)", retarget, text)


def create(root, kind, destination, title=None, owner=""):
    root = root.resolve()
    relative = Path(destination)
    if relative.is_absolute() or relative.parts[:1] not in (("context",), ("products",)):
        raise ValueError("Create PM artifacts under context/ or products/ with a relative path")
    workspace = root / "workspace"
    if workspace.is_symlink() or not (workspace / ".git").is_dir() or (workspace / ".git").is_symlink():
        raise ValueError("Initialise workspace/ as a separate Git repository before PM work")
    target = workspace / relative
    if target.resolve() != target or target.suffix != ".md":
        raise ValueError("Use a direct Markdown path inside PM Hub")
    if kind not in KINDS:
        raise ValueError(f"Unknown template: {kind}")
    if context_location(kind, relative):
        raise ValueError(context_location(kind, relative))
    source = root / "templates" / f"{kind}.md"
    if source.resolve() != source:
        raise ValueError("Templates must be regular files inside PM Hub")
    text = source.read_text(encoding="utf-8")
    marker = MARKER.match(text)
    if not marker or marker[1] != kind or work_state(text)[1]:
        raise ValueError("Repair the source template before creating a draft")
    title = title or target.stem.replace("-", " ").capitalize()
    if "\n" in title or "\r" in title:
        raise ValueError("Use a single line for the title")
    text = text.replace("{{title}}", title)
    if owner:
        text = text.replace("{{owner}}", owner)
    text = text.replace("{{id}}", f"{kind}-{uuid4().hex[:12]}")
    text = text.replace("{{date and result}}", f"{date.today().isoformat()}: Draft created.")
    text = retarget_links(text, source, target, root)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8", newline="\n") as output:
        output.write(text)
    return target
