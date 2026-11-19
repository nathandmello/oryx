"""Canonical locations inside the private repository."""

from pathlib import Path
import re

SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
COMPANY = "context/company/overview.md"
PROFILE = "context/pm/context.md"
WORK_FOLDERS = {"goal": "goals", "problem": "problems", "strategy": "strategies",
                "roadmap": "roadmaps", "experiment": "experiments"}
INITIATIVE_BRIEFS = ("discovery-brief", "initiative-brief")
MAX_TOPICS = 6


def slug(value):
    if not isinstance(value, str) or not SLUG.fullmatch(value):
        raise ValueError("Choose a named entity with a lowercase, hyphen-separated slug")
    return value


def product(name):
    return f"context/products/{slug(name)}/overview.md"


def area(product_name, area_name):
    return f"context/products/{slug(product_name)}/areas/{slug(area_name)}/overview.md"


def initiative(name, product_name=None):
    if product_name is None:
        return f"context/initiatives/{slug(name)}/overview.md"
    return f"context/products/{slug(product_name)}/initiatives/{slug(name)}/overview.md"


def initiative_register(product_name):
    return f"workspace/backlogs/{slug(product_name)}/initiatives.json"


def initiative_brief(product_name, initiative_slug, kind):
    if kind not in INITIATIVE_BRIEFS:
        raise ValueError("Choose a Discovery Brief or Initiative Brief")
    return f"workspace/initiatives/{slug(product_name)}/{slug(initiative_slug)}/{kind}.md"


def prioritization(product_name, cycle):
    return f"workspace/roadmaps/{slug(product_name)}/{slug(cycle)}.md"


def experiment_draft_home(product_name, initiative_slug):
    return f"workspace/experiments/{slug(product_name)}/{slug(initiative_slug)}"


def governed_kind(name):
    """Identify product-qualified records. Format-2 standalone files keep their original routes."""
    path = Path(name)
    parts = path.parts
    if (len(parts) not in (4, 5) or parts[0] != "workspace" or not SLUG.fullmatch(parts[2])
            or (isinstance(name, str) and path.as_posix() != name)):
        return None
    if len(parts) == 4:
        if parts[1] == "backlogs" and path.name == "initiatives.json":
            return "register"
        if parts[1] == "roadmaps" and path.suffix == ".md" and SLUG.fullmatch(path.stem):
            return "prioritization"
    elif SLUG.fullmatch(parts[3]):
        if parts[1] == "initiatives" and path.suffix == ".md" and path.stem in INITIATIVE_BRIEFS:
            return path.stem
        if parts[1] == "experiments" and re.fullmatch(rf"experiment\.({SLUG.pattern})\.draft\.json", path.name):
            return "experiment-draft"
    return None


def entity(name):
    """Return the context entity directory, independent of any topic below it."""
    parts = Path(name).parts
    if parts[:2] in (("context", "company"), ("context", "pm")) and len(parts) >= 3:
        return Path(*parts[:2])
    if len(parts) >= 4 and parts[:2] in (("context", "products"), ("context", "initiatives")):
        slug(parts[2])
        if parts[1] == "products" and parts[3] in {"areas", "initiatives"} and len(parts) >= 6:
            slug(parts[4])
            return Path(*parts[:5])
        if parts[1] == "products" and parts[3] == "areas":
            raise ValueError("Choose a named product area")
        return Path(*parts[:3])
    raise ValueError("Choose a company, product, product area, or initiative context entity")


def brief_kind(name):
    path = Path(name)
    if path.name != "overview.md":
        return None
    try:
        owner = entity(path)
    except ValueError:
        return None
    if path.parent != owner:
        return None
    if owner == Path("context/company"):
        return "company-context"
    if owner.parts[:2] == ("context", "initiatives"):
        return "initiative-context"
    if owner.parts[:2] == ("context", "products"):
        return {"areas": "product-area-context", "initiatives": "initiative-context"}.get(
            owner.parts[3] if len(owner.parts) == 5 else "", "product-context"
        )
    return None


def valid_work(name, kind=None):
    path = Path(name)
    parts = path.parts
    if len(parts) < 3 or parts[0] != "workspace" or path.suffix != ".md" or not SLUG.fullmatch(path.stem):
        return False
    governed = governed_kind(name)
    if governed:
        return kind is None or kind == governed
    if kind:
        return len(parts) == 3 and WORK_FOLDERS.get(kind) == parts[1]
    if parts[1] == "initiatives":
        return len(parts) == 4 and bool(SLUG.fullmatch(parts[2]))
    return len(parts) == 3 and parts[1] in {*WORK_FOLDERS.values(), "backlogs"}
