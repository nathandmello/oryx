"""Resolve explicit initiative area subjects against current private context."""

import context_capture
from initiative_events import AREA_SUBJECT
import layout
import pm_profile
import records


def resolve(private, product, subject):
    match = AREA_SUBJECT.fullmatch(subject)
    if not match or match[1] != product:
        raise ValueError(f"Use a product area subject scoped to product/{product}")
    current = context_capture.area_context(private, product, match[2])
    inline = [{"path": record["record"], "section": entry["section"], "line": entry["line"]}
              for record in current["inline_entries"] for entry in record["entries"]]
    remit, error = context_capture.inspect_remit(private)
    remit_ref = None
    if context_capture.remit_status(remit) == "confirmed":
        entries = []
        if any(row["subject"] == subject for row in remit["responsibilities"]):
            entries.append("responsibilities")
        if subject in remit["follow"]:
            entries.append("follow")
        if any(subject in row["depends_on"] for row in remit["responsibilities"]):
            entries.append("depends_on")
        if entries:
            path = pm_profile.LEGACY if (private / pm_profile.LEGACY).is_file() else pm_profile.PATH
            remit_ref = {"path": path, "entries": entries}
    result = {"area_brief": current["area_brief"], "inline": inline, "remit": remit_ref}
    if not (current["area_brief"] or inline or remit_ref):
        result["issue"] = error or f"Unknown product area: {subject}"
    return result


def check_change(private, product, register, event):
    kind = event["type"]
    if kind in {"capture", "set-areas"}:
        subjects = event.get("areas", [])
    elif kind == "cycle":
        subjects = {area for identifier in event["options"] for area in register.items.get(identifier, {}).get("areas", [])}
    elif kind == "decision" and event["action"] in {"start-discovery", "prepare-brief", "approve-initiative", "plan", "start-delivery"}:
        subjects = register.items.get(event["initiative"], {}).get("areas", [])
    else:
        return
    for subject in sorted(subjects):
        info = resolve(private, product, subject)
        if "issue" in info:
            raise ValueError(info["issue"])


def current_links(private, product, subjects):
    links = {}
    for subject in subjects:
        try:
            links[subject] = resolve(private, product, subject)
        except (ValueError, OSError) as exc:
            links[subject] = {"issue": str(exc)}
    return links


def initiative_context(private, product, identifier):
    name = records.initiative_home(private, product, identifier.split("/")[1])
    if not records.existing_briefs(private, name, "initiative"):
        return None
    text = (private / name).read_text(encoding="utf-8")
    if records.parent_reference(name, text) != layout.product(product):
        return None
    return {"path": name, "id": records.work_state(text)[0].get("ID")}


def filter_subject(product, area):
    if area is None:
        return product, None
    if product and layout.SLUG.fullmatch(area):
        area = f"product/{product}/area/{area}"
    match = AREA_SUBJECT.fullmatch(area)
    if not match or (product and match[1] != product):
        raise ValueError("Use a full product area subject, or provide --product and its --area slug")
    return match[1], area
