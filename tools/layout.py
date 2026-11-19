"""Canonical locations inside the private repository."""

from pathlib import Path
import re

SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
COMPANY = "context/company/overview.md"
PROFILE = "context/pm/context.md"
WORK_FOLDERS = {"goal": "goals", "problem": "problems", "strategy": "strategies",
                "roadmap": "roadmaps", "experiment": "experiments"}
MAX_TOPICS = 6


def slug(value):
    if not isinstance(value, str) or not SLUG.fullmatch(value):
        raise ValueError("Choose a named entity with a lowercase, hyphen-separated slug")
    return value


def product(name):
    return f"context/products/{slug(name)}/overview.md"


def area(product_name, area_name):
    return f"context/products/{slug(product_name)}/areas/{slug(area_name)}/overview.md"


def initiative(name):
    return f"context/initiatives/{slug(name)}/overview.md"


def entity(name):
    """Return the context entity directory, independent of any topic below it."""
    parts = Path(name).parts
    if parts[:2] in (("context", "company"), ("context", "pm")) and len(parts) >= 3:
        return Path(*parts[:2])
    if len(parts) >= 4 and parts[:2] in (("context", "products"), ("context", "initiatives")):
        slug(parts[2])
        if parts[1] == "products" and parts[3] == "areas":
            if len(parts) < 6:
                raise ValueError("Choose a named product area")
            slug(parts[4])
            return Path(*parts[:5])
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
        return "product-area-context" if len(owner.parts) == 5 else "product-context"
    return None


def valid_work(name, kind=None):
    path = Path(name)
    parts = path.parts
    if len(parts) < 3 or parts[0] != "workspace" or path.suffix != ".md" or not SLUG.fullmatch(path.stem):
        return False
    if kind:
        return len(parts) == 3 and WORK_FOLDERS.get(kind) == parts[1]
    if parts[1] == "initiatives":
        return len(parts) == 4 and bool(SLUG.fullmatch(parts[2]))
    return len(parts) == 3 and parts[1] in {*WORK_FOLDERS.values(), "backlogs"}
