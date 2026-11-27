"""Prepare browser roadmap edits for PM review."""

from datetime import date
import re

from oryx.capabilities import customizations
from oryx.capabilities import filing
from oryx.capabilities import initiative_events
import initiative_store
from oryx.capabilities import initiative_views
import layout
from oryx.capabilities import opportunities
import records
import storage
import upgrades

HORIZONS = initiative_events.HORIZONS
SECTIONS = opportunities.REQUIRED_SECTIONS["prioritization"]


def snapshot(root, product):
    _, payload, register = initiative_store.read(root, layout.slug(product))
    if register.setup is None:
        raise ValueError("Set up the product initiative register first")
    errors = initiative_store.live_errors(root, register)
    if errors:
        raise ValueError("\n".join(errors))
    return initiative_store.digest(initiative_store.canonical(payload)), register


def board(root, product, view=None):
    revision, register = snapshot(root, product)
    rows = initiative_views.roadmap([(product, register)], private=storage.private_root(root))
    try:
        presentation = customizations.projection(root, rows, view, product=product)
    except (ValueError, OSError) as exc:
        presentation = customizations.projection(root, rows, "core")
        presentation["warning"] = f"Showing the core roadmap. Review workspace customization: {exc}"
    if presentation["page"]:
        try:
            presentation["page_revision"] = customizations.revision(customizations.page_template(root, presentation["page"]))
        except (OSError, ValueError):
            presentation["page_revision"] = ""  # Editing the roadmap still works while the page is unavailable.
    return {
        "presentation": presentation,
        "revision": revision,
        "today": date.today().isoformat(),
        "cycles": [
            {key: cycle[key] for key in ("cycle", "starts_on", "ends_on", "capacity", "unit", "options")}
            | {"path": cycle["references"]["path"],
               "reserved": sum(place["effort"] for place in cycle["placements"] if place["reserved"])}
            for cycle in sorted(register.cycles.values(), key=lambda cycle: (cycle["starts_on"], cycle["cycle"]))
        ],
        "rows": rows,
        "candidates": [
            {"id": item["id"], "title": item["title"], "outcome": item["description"]["outcome"],
             "eligible_cycles": [cycle["cycle"] for cycle in register.cycles.values()
                                 if item["id"] in cycle["options"]
                                 and register.approved_at[item["id"]] <= cycle["compared_at"]]}
            for item in sorted(register.items.values(), key=lambda item: (item["title"].casefold(), item["id"]))
            if item["phase"] == "candidate"
        ],
    }


def check_revision(current, expected):
    if current != expected:
        raise ValueError("The roadmap changed. Reload and review your edits against the current roadmap")


def decision(action, identifier, reason, source, **placement):
    return {
        "type": "decision", "action": action, "initiative": identifier,
        "on": date.today().isoformat(), "reason": reason, "source": source, **placement,
    }


def allocate_ranks(order, original, fixed, reserved):
    """Keep fixed cards and unchanged columns. Assign the tightest gaps first."""
    ranks = {identifier: original[identifier]["rank"] for identifier in fixed}
    spans = []
    for horizon in HORIZONS:
        sequence = order[horizon]
        previous = [identifier for identifier, place in sorted(original.items(), key=lambda pair: pair[1]["rank"])
                    if place["horizon"] == horizon]
        if sequence == previous:
            ranks.update((identifier, original[identifier]["rank"]) for identifier in sequence)
            continue
        lower = 0
        pending = []
        for identifier in sequence:
            if identifier in fixed:
                upper = ranks[identifier]
                if upper <= lower:
                    raise ValueError("Keep fixed cards in their approved order")
                spans.append((upper, lower, pending))
                lower, pending = upper, []
            else:
                pending.append(identifier)
        spans.append((None, lower, pending))
    for rank in ranks.values():
        reserved.add(rank)
    for upper, lower, pending in sorted(spans, key=lambda span: (span[0] is None, span[0])):
        for identifier in pending:
            rank = lower + 1
            while rank in reserved:
                rank += 1
            if upper is not None and rank >= upper:
                raise ValueError("There is no free rank before that fixed card. Move the card to another position")
            if upper is None and identifier in original:
                old_rank = original[identifier]["rank"]
                if old_rank >= rank and old_rank not in reserved:
                    rank = old_rank
            ranks[identifier] = lower = rank
            reserved.add(rank)
    return ranks


def placement_changes(root, product, body):
    revision, register = snapshot(root, product)
    check_revision(revision, body.get("revision"))
    cycle_id = body["cycle"]
    cycle = register.cycles.get(cycle_id)
    if cycle is None or cycle["ends_on"] < date.today().isoformat():
        raise ValueError("Choose an open planning cycle")
    order = body["order"]
    if not isinstance(order, dict) or set(order) != set(HORIZONS):
        raise ValueError("Supply the full cycle board")
    for column in order.values():
        if not isinstance(column, list):
            raise ValueError("Supply a list of initiative IDs in each horizon")
        for identifier in column:
            if not initiative_events.VALIDATORS["initiative ID"](identifier):
                raise ValueError("Use registered initiative IDs")
    horizons = {identifier: horizon for horizon, column in order.items() for identifier in column}
    if len(horizons) != sum(map(len, order.values())):
        raise ValueError("Place each initiative once")
    current = {item["id"]: item["planning"] for item in register.items.values()
               if item["planning"] and item["planning"]["cycle"] == cycle_id}
    fixed = {identifier for identifier in current if register.items[identifier]["phase"] != "planned"}
    if any(horizons.get(identifier) != current[identifier]["horizon"] for identifier in fixed):
        raise ValueError("Keep fixed cards in their approved horizons")
    released = set(current) - set(horizons)
    added = set(horizons) - set(current)
    if not added <= set(register.items) or not all(register.items[identifier]["phase"] == "candidate" for identifier in added):
        raise ValueError("Only approved candidates can be added")
    if not added <= set(cycle["options"]):
        raise ValueError("Compare new candidates in a new planning cycle before selecting them")
    effort = body.get("effort", {})
    if not isinstance(effort, dict) or set(effort) != added:
        raise ValueError("Supply effort for each new selection")
    # Some historic reservations no longer appear on the current board.
    movable = {id(place) for identifier, place in current.items() if identifier not in fixed}
    reserved = {place["rank"] for place in cycle["placements"] if place["reserved"] and id(place) not in movable}
    ranks = allocate_ranks(order, current, fixed, reserved)
    moved = {identifier for identifier in set(current) & set(horizons) if
             (ranks[identifier], horizons[identifier]) != (current[identifier]["rank"], current[identifier]["horizon"])}
    removed = sorted(released | moved)
    reason, source = body["reason"], body["source"]
    changes = [decision("unplan", identifier, reason, source) for identifier in removed]
    for identifier in sorted(added | moved, key=ranks.__getitem__):
        changes.append(decision("plan", identifier, reason, source, cycle=cycle_id, rank=ranks[identifier],
                                effort=effort[identifier] if identifier in added else current[identifier]["effort"],
                                horizon=horizons[identifier]))
    if not changes:
        raise ValueError("Move, add, or return a card before reviewing changes")
    return changes


def read_comparison(root, product, cycle):
    private = storage.private_root(root)
    relative = layout.prioritization(product, cycle)
    target = private / relative
    if target.resolve() != target or (target.exists() and not target.is_file()):
        raise ValueError("Use the canonical planning comparison file")
    if not target.exists():
        return target, None
    storage.require_visible(private, relative)
    _, _, contents = initiative_store.local_markdown(root, relative, "prioritization")
    return target, contents.decode("utf-8")


def comparison_sections(text):
    sections = {}
    for name, _, start, end in records.section_blocks(text):
        if name in sections:
            raise ValueError(f"Planning comparison has duplicate sections named {name}. Give each a distinct heading before editing")
        sections[name] = text[start:end].strip()
    sections.pop("Work state", None)
    return sections


def comparison_template(root, product):
    target = storage.private_root(root) / layout.prioritization(product, "preview")
    source = (root / "templates/prioritization.md").read_text(encoding="utf-8")
    notices = []
    sections = comparison_sections(customizations.draft_template(root, "prioritization", target, source, notices=notices))
    inputs = list(sections.items())
    if notices:
        inputs.append(("studio-notices", notices))
    return {"sections": sections, "order": list(sections), "notices": notices,
            "revision": initiative_store.digest(initiative_store.canonical(inputs))}


def comparison(root, product, cycle):
    _, register = snapshot(root, product)
    target, original = read_comparison(root, product, cycle)
    sections = comparison_sections(original) if original else {}
    return {"revision": initiative_store.digest(original.encode("utf-8")) if original is not None else "absent",
            "approved": cycle in register.cycles, "text": original,
            "sections": sections, "order": list(sections),
            "path": target.relative_to(storage.private_root(root)).as_posix()}


def prepare_comparison(root, product, cycle, options, sections, expected, register_revision, starter_revision=None):
    if not isinstance(sections, dict) or not set(SECTIONS) <= sections.keys():
        raise ValueError("Fill the planning comparison sections")
    for value in sections.values():
        if not isinstance(value, str) or not records.specific(value.strip()) or re.search(r"(?m)^#(?: |# )", value):
            raise ValueError("Fill each section and use level-three headings for subsections")
    private = storage.private_root(root)
    with storage.writer_lock(private):
        revision, register = snapshot(root, product)
        check_revision(revision, register_revision)
        if cycle in register.cycles:
            raise ValueError("This cycle has PM approval. Create a new cycle for a new comparison")
        for identifier in options:
            if identifier not in register.items or register.items[identifier]["phase"] != "candidate":
                raise ValueError("Compare approved candidates for this product")
        target, original = read_comparison(root, product, cycle)
        actual = initiative_store.digest(original.encode("utf-8")) if original is not None else "absent"
        if expected != actual:
            raise ValueError("The comparison changed. Reload its current contents before saving")
        relative = target.relative_to(private).as_posix()
        if relative in upgrades.source_paths(private):
            raise ValueError("The comparison is preserved as original evidence")
        storage.require_visible(private, relative)
        title = cycle.replace("-", " ").capitalize()
        if original is None:
            filing.check_new(private, "prioritization", relative, title)
            if starter_revision is not None and starter_revision != comparison_template(root, product)["revision"]:
                raise ValueError("The planning template changed. Reopen the cycle form to review the new sections")
        draft = original if original is not None else records.draft_text(root, "prioritization", target, title)
        if sections.keys() - comparison_sections(draft).keys():
            raise ValueError("Use editable sections from this planning comparison")
        content = dict(sections)
        state, _ = records.work_state(draft)
        state.update({"State": "complete", "Last checkpoint": f"{date.today().isoformat()}: Comparison prepared for review.",
                      "Next action": "Review the cycle and selection proposal.", "Waiting on": "none", "Resume when": "none"})
        content["Work state"] = "\n".join(["| Field | Value |", "| --- | --- |",
                                          *(f"| {field} | {state[field]} |" for field in records.FIELDS)])
        for name, _, start, end in reversed(records.section_blocks(draft)):
            if name in content:
                draft = draft[:start] + "\n" + content[name].strip() + "\n\n" + draft[end:]
        if missing := opportunities.missing(draft, SECTIONS):
            raise ValueError("Complete: " + ", ".join(missing))
        opportunities.check_comparison(draft, options)
        _, errors = records.state_errors(draft)
        if errors:
            raise ValueError("\n".join(errors))
        return target, original, draft


def new_cycle_changes(body):
    cycle = {
        "type": "cycle", "cycle": body["cycle"], "options": body["options"], "starts_on": body["starts_on"],
        "ends_on": body["ends_on"], "capacity": body["capacity"], "unit": body["unit"],
    }
    initiative_events.validate_event(cycle)
    if cycle["ends_on"] < cycle["starts_on"] or cycle["ends_on"] < date.today().isoformat():
        raise ValueError("Choose a valid planning period that ends today or later")
    placements = body["placements"]
    if not isinstance(placements, list):
        raise ValueError("Submit a list of selections")
    chosen = []
    for placement in placements:
        if not isinstance(placement, dict) or set(placement) != {"initiative", "horizon", "rank", "effort"}:
            raise ValueError("Each selection needs an initiative, horizon, rank, and effort")
        event = decision("plan", placement["initiative"], body["reason"], body["source"], cycle=cycle["cycle"],
                         horizon=placement["horizon"], rank=placement["rank"], effort=placement["effort"])
        initiative_events.validate_event(event)
        chosen.append(event)
    if (len({event["initiative"] for event in chosen}) != len(chosen)
            or len({event["rank"] for event in chosen}) != len(chosen)
            or {event["initiative"] for event in chosen} - set(cycle["options"])):
        raise ValueError("Select each compared candidate once and use unique ranks")
    if sum(event["effort"] for event in chosen) > cycle["capacity"]:
        raise ValueError("Planning cycle capacity exceeded")
    return [cycle, *chosen]
