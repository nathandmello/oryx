"""File new work under its owner and reserve extra records for independent use."""

from pathlib import Path
from os.path import relpath
import re
from urllib.parse import quote, unquote

import records
import storage
import upgrades

BASES = ("event-history", "maintained-reference", "independent-deliverable")
SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


def home(name):
    parts = Path(name).parts
    if parts[:1] == ("context",):
        return Path("context")
    if len(parts) >= 3 and parts[0] == "products" and SLUG.fullmatch(parts[1]):
        if parts[2] == "initiatives" or (parts[2] == "areas" and len(parts) >= 5):
            if len(parts) >= 5 and SLUG.fullmatch(parts[3]):
                return Path(*parts[:4])
            raise ValueError("Choose a named initiative or product area")
        return Path(*parts[:2])
    raise ValueError("Choose a company, product, area, or initiative home")


def area_parent(private, name):
    parts = Path(name).parts
    if not records.is_area_path(name) or records.area_brief_path(parts[1], parts[3]) != name:
        raise ValueError("Choose the standard product area context path")
    options = records.product_briefs(private, parts[1])
    if len(options) != 1:
        raise ValueError("Establish one owning product brief before creating product area context. Candidates: "
                         + (", ".join(options) or "none"))
    return options[0]


def area_contract(private, name, parent, basis, reason, trigger):
    owning = area_parent(private, name)
    if (parent and parent != owning) or (basis and basis != "maintained-reference"):
        raise ValueError("Product area context is a maintained reference under its owning product brief")
    check_purpose(reason, trigger)
    return {"parent": owning, "basis": "maintained-reference", "reason": reason, "trigger": trigger}


def check_purpose(reason, trigger):
    if not all(isinstance(v, str) and records.specific(v.strip()) and len(v.splitlines()) == 1
               and "|" not in v for v in (reason, trigger)):
        raise ValueError("Give the reader's independent need and a concrete review or completion trigger")


def note_contract(private, name, parent, basis, reason, trigger):
    target = Path(name)
    root = home(name)
    if not isinstance(parent, str) or not parent:
        raise ValueError("A separate record needs its existing parent path")
    parent_path = private / parent
    if (Path(parent).is_absolute() or parent in upgrades.source_paths(private) or home(parent) != root or parent_path.resolve() != parent_path
            or not parent_path.is_file() or parent_path.suffix != ".md"
            or any(part.startswith(".") or part in {"sources", "secrets"} for part in Path(parent).parts)):
        raise ValueError("Choose a regular parent record under the same owner")
    with parent_path.open(encoding="utf-8") as stream:
        marker = records.MARKER.match(stream.readline())
    if not marker or marker[1] not in records.KINDS or marker[1] == "context-note":
        raise ValueError("Choose the owning brief or work artifact as the parent")
    if basis not in BASES:
        raise ValueError("Choose a separate record basis: " + ", ".join(BASES))
    check_purpose(reason, trigger)
    folder = root / "records"
    if marker[1] not in records.CONTEXT_KINDS:
        folder /= Path(parent).stem
    if (target.parent != folder or not SLUG.fullmatch(target.stem) or target.suffix != ".md"
            or re.search(r"-(?:copy|final|v\d+)$", target.stem)):
        raise ValueError(f"Use {folder}/<specific-subject>.md for a qualified record")
    return {"parent": parent, "basis": basis, "reason": reason, "trigger": trigger}


def add_contract(text, private, target, contract):
    link = quote(Path(relpath(private / contract["parent"], target.parent)).as_posix())
    rows = ("## Filing\n\n| Field | Value |\n| --- | --- |\n"
            f"| Owning record | [Parent]({link}) |\n| Basis | {contract['basis']} |\n"
            f"| Reader need | {contract['reason']} |\n| Review trigger | {contract['trigger']} |\n\n")
    return text.replace("## Context controls\n", rows + "## Context controls\n", 1)


def check_new(private, kind, name, title, retiring=()):
    path = Path(name)
    owner = home(name)
    if any(part.startswith(".") or part in {"secrets", "sources"} for part in path.parts):
        raise ValueError("Choose an active record home")
    if re.search(r"-(?:copy|final|v\d+)$", path.stem):
        raise ValueError("Update the owning record or use a specific independent subject")
    expected = {"company-context": Path("context/company.md"), "product-context": owner / "context.md",
                "initiative-context": owner / "context.md", "product-area-context": owner / "context.md"}
    if records.is_area_path(path) and kind != "product-area-context":
        raise ValueError("The standard area context path is reserved for a product area brief")
    if kind in expected:
        scope_ok = {"company-context": owner == Path("context"), "product-context": len(owner.parts) == 2,
                    "initiative-context": len(owner.parts) == 4 and owner.parts[2] == "initiatives",
                    "product-area-context": records.is_area_path(path)}[kind]
        if not scope_ok or path != expected[kind]:
            raise ValueError("Use the standard brief path for this entity")
        previous = records.existing_briefs(private, name, kind.removesuffix("-context"))
        previous = [item for item in previous if item not in retiring]
        if previous:
            raise ValueError("Reuse the existing brief: " + ", ".join(previous))
    elif kind != "context-note" and path.parent != owner:
        raise ValueError("Use the entity home for working artifacts; records/ holds supporting records")

    # A different filename or directory cannot create a second copy of the same typed subject.
    label = (title or path.stem.replace("-", " ")).strip().casefold()
    for other in storage.inventory(private):
        rel = other.relative_to(private)
        if rel.as_posix() in retiring:
            continue
        if (other.suffix != ".md" or other.resolve() != other or not other.is_file() or other == private / name
                or owner not in rel.parents or any(p.startswith(".") or p in {"sources", "secrets"} for p in rel.parts)):
            continue
        try:
            other_owner = home(rel)
        except ValueError:
            continue
        if other_owner != owner or (kind == "context-note" and rel.parent != path.parent):
            continue
        with other.open(encoding="utf-8") as stream:
            marker = records.MARKER.match(stream.readline())
            if marker and marker[1] == kind:
                existing = stream.readline().removeprefix("# ").strip().casefold()
                if rel.stem == path.stem or existing == label:
                    raise ValueError(f"Reuse the existing {kind}: {rel}")


def verify_note(private, name, text):
    """Verify the durable filing fields at the same paths used by the creation gate."""
    try:
        relative = Path(name).relative_to(home(name))
    except ValueError:
        return
    marker = records.MARKER.match(text)
    area = marker and marker[1] == "product-area-context"
    owner = home(name)
    if not area and len(owner.parts) == 4 and owner.parts[2] == "areas" and not marker:
        return  # Older workspaces could keep untyped references under areas/.
    if not area and (not relative.parts or relative.parts[0] != "records"):
        return
    if not area and (not marker or marker[1] != "context-note"):
        raise ValueError(f"Use a supporting record with a filing decision at {name}")
    rows, problems = records.table(text, "Filing", ("Field", "Value"))
    if problems or len(rows) != 4 or len(dict(rows)) != 4:
        raise ValueError(f"Invalid filing decision in {name}")
    data = dict(rows)
    parent = re.fullmatch(r"\[Parent\]\(([^)]+)\)", data.get("Owning record", ""))
    if problems or not parent:
        raise ValueError(f"Identify the owning parent and filing decision in {name}")
    owner = (private / name).parent / unquote(parent[1])
    resolved = owner.resolve().relative_to(private).as_posix()
    if area:
        if data.get("Basis") != "maintained-reference":
            raise ValueError("Use the maintained-reference basis for product area context")
        expected = area_contract(private, name, resolved, data["Basis"], data.get("Reader need"), data.get("Review trigger"))
        controls, _ = records.table(text, "Context controls", ("Field", "Value"))
        parent_link = dict(controls).get("Parent context", "")
        match = re.fullmatch(r"\[[^\]]+\]\(([^)]+)\)", parent_link)
        if not match or (private / name).parent.joinpath(unquote(match[1])).resolve() != private / expected["parent"]:
            raise ValueError("The product area must inherit its owning product context")
    else:
        note_contract(private, name, resolved, data.get("Basis"), data.get("Reader need"), data.get("Review trigger"))
