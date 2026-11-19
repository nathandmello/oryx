"""Narrative records used by the structured initiative workflow."""

from pathlib import PurePosixPath
import re

import layout
import records

BRIEFS = {kind: f"{kind}.md" for kind in layout.INITIATIVE_BRIEFS}
SLUG = layout.SLUG
path_kind = layout.governed_kind
COMPARISON_COLUMNS = ("Initiative ID", "Assessment")
DISCOVERY_PLAN = (
    "Known, assumed, and unknown", "Learning goals and exit criteria",
    "Approach and timebox", "Capacity and review",
)
REQUIRED_SECTIONS = {
    "discovery-brief": (*DISCOVERY_PLAN, "Findings and recommendation", "Sources"),
    "initiative-brief": (
        "Proposal", "Value and alignment", "Approach and scope", "Delivery and launch",
        "Assumptions and risks", "Sources",
    ),
    "prioritization": ("Objectives and obligations", "Capacity constraints", "Comparison", "Sources"),
}


def location_error(kind, name):
    if path_kind(name) == kind:
        return None
    if kind in BRIEFS:
        return f"use workspace/initiatives/<product>/<initiative>/{BRIEFS[kind]}"
    if kind == "prioritization":
        return "use workspace/roadmaps/<product>/<planning-cycle>.md"


def brief_parent_error(name, text, expected):
    if (records.section(text, "Parent initiative") or "").strip() != expected:
        return f"{name}: set the '## Parent initiative' section to the registered ID {expected}"


def missing(text, headings):
    return [
        heading for heading in headings
        if not records.specific((records.section(text, heading) or "").strip())
    ]


def check_comparison(text, options):
    rows, errors = records.table(text, "Comparison", COMPARISON_COLUMNS)
    if errors:
        raise ValueError("; ".join(errors))
    identifiers = [identifier for identifier, _ in rows]
    if sorted(identifiers) != sorted(options):
        raise ValueError("List each cycle option exactly once in the Comparison table using its permanent initiative ID")
    for identifier, assessment in rows:
        if not records.specific(assessment) or not re.search(r"\w", assessment):
            raise ValueError(f"Add an assessment for {identifier} in the Comparison table")


def validate(texts):
    errors = []
    for name, text in texts.items():
        marker = records.MARKER.match(text)
        if not marker or (kind := marker[1]) not in REQUIRED_SECTIONS:
            continue
        if name == f"templates/{kind}.md":
            problems = [f"use exactly one {h} section" for h in REQUIRED_SECTIONS[kind] if records.section(text, h) is None]
            if kind in BRIEFS:
                parent_error = brief_parent_error(name, text, "{{initiative_id}}")
                if parent_error:
                    problems.append(parent_error)
            if kind == "prioritization":
                problems.extend(records.table(text, "Comparison", COMPARISON_COLUMNS)[1])
        elif any(part in {"sources", "secrets"} or part.startswith(".") for part in PurePosixPath(name).parts):
            continue
        else:
            location = location_error(kind, name)
            problems = [location] if location else []
            if records.work_state(text)[0].get("State") == "complete":
                problems.extend(f"complete {kind} needs content in {h}" for h in missing(text, REQUIRED_SECTIONS[kind]))
        errors.extend(f"{name}: {problem}" for problem in problems)
    return errors
