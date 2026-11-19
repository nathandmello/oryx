"""Project backlog, roadmap, and trace views from verified initiative records."""

import csv
from datetime import date
from html import escape
from io import StringIO
import json

import experiment_drafts
import initiative_areas
import layout
import metric_registry
from initiative_events import HORIZONS, IN_DEFINITION, PHASES, iso_date

BACKLOG_FIELDS = {
    "product", "id", "title", "problem", "audience", "phase", "rank", "effort", "unit",
    "captured_on", "last_decision_on", "revisit", "sources", "areas",
}
ROADMAP_FIELDS = {
    "product", "cycle", "horizon", "rank", "id", "title", "outcome", "success_metrics", "phase",
    "effort", "unit", "period_start", "period_end", "trade_off", "planning_record", "delivery", "areas",
}


def view_template(root, view):
    expected = {"backlog": BACKLOG_FIELDS, "roadmap": ROADMAP_FIELDS}[view]
    path = root / "templates" / "views" / f"{view}.json"
    if path.resolve() != path or not path.is_file():
        raise ValueError(f"Use a regular {view} view template inside PM Hub")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Invalid {view} view template")
    columns = data.get("columns")
    sources = data.get("sources")
    if (not isinstance(columns, dict) or set(columns) != expected
            or not all(isinstance(label, str) and label.strip() for label in columns.values())
            or not isinstance(data.get("title"), str) or not data["title"].strip()
            or not isinstance(sources, list) or not sources
            or not all(isinstance(source, str) and source.startswith("https://") for source in sources)):
        raise ValueError(f"Invalid {view} view template")
    return data


def next_review(item, decision):
    if decision.get("action") == "review-outcomes":
        if decision["follow_up"]:
            return decision["follow_up"]["on"]
        triggers = item["review_trigger_measurements"]
        return item["measurements"][triggers[0]]["observed_on"] if triggers else None
    return decision.get("review_on") or decision.get("revisit")


def backlog(registrations, phase=None, due=False, all_phases=False, *, area=None):
    phases = IN_DEFINITION | {"candidate"}
    if phase is not None:
        phases = {phase}
    elif due or all_phases:
        phases = set(PHASES)
    rows = []
    for product, register in registrations:
        for item in register.items.values():
            if item["phase"] not in phases or (area is not None and area not in item["areas"]):
                continue
            decision = item["decisions"][-1] if item["decisions"] else {}
            revisit = next_review(item, decision)
            review_date = iso_date(revisit)
            if due and (not review_date or review_date > date.today()):
                continue
            description = item["description"] or {}
            placement = item["planning"] or {}
            cycle = register.cycles.get(placement.get("cycle"), {})
            rows.append({
                "product": product, "id": item["id"], "title": item["title"], "phase": item["phase"],
                "areas": item["areas"],
                "problem": description.get("problem"), "audience": description.get("audience"),
                "rank": placement.get("rank"), "effort": placement.get("effort"), "unit": cycle.get("unit"),
                "captured_on": item["signals"][0]["observed_on"],
                "last_decision_on": decision.get("on"), "revisit": revisit,
                "sources": [signal["source"] for signal in item["signals"]],
            })
    return sorted(rows, key=lambda row: (
        row["product"], PHASES.index(row["phase"]), row["rank"] or float("inf"), row["captured_on"], row["id"],
    ))


def roadmap(registrations, cycle_filter=None, *, area=None):
    rows = []
    matched = False
    for product, register in registrations:
        matched = matched or cycle_filter in register.cycles
        for item in register.items.values():
            placement = item["planning"]
            if placement is None or (cycle_filter is not None and placement["cycle"] != cycle_filter):
                continue
            if area is not None and area not in item["areas"]:
                continue
            cycle = register.cycles[placement["cycle"]]
            rows.append({
                "product": product, "id": item["id"], "title": item["title"], "phase": item["phase"],
                "areas": item["areas"],
                "outcome": item["description"]["outcome"], "success_metrics": sorted(item["targets"]),
                "cycle": placement["cycle"], "rank": placement["rank"], "horizon": placement["horizon"],
                "effort": placement["effort"], "unit": cycle["unit"], "trade_off": placement["reason"],
                "period_start": cycle["starts_on"], "period_end": cycle["ends_on"],
                "planning_record": cycle["references"]["path"], "delivery": item["delivery"],
            })
    if cycle_filter is not None and not matched:
        raise ValueError(f"Unknown planning cycle: {cycle_filter}")
    return sorted(rows, key=lambda row: (
        row["product"], row["period_start"], row["cycle"], HORIZONS.index(row["horizon"]), row["rank"],
    ))


def trace(product, register, identifier=None, *, private):
    context = {
        "company": {"id": register.setup["references"]["company_id"], "path": register.setup["company"]},
        "product": {"id": register.setup["references"]["product_id"], "path": register.setup["product_context"]},
    }
    files = {"register": layout.initiative_register(product)}
    definitions = metric_registry.effective(private.parent, private, product)
    current = {key: row for key, event in register.metrics.items()
               if (row := metric_registry.current_for_snapshot(definitions, event))}
    if identifier is None:
        files["planning_comparisons"] = {cycle: data["references"]["path"] for cycle, data in register.cycles.items()}
        return {"product": product, "context": context, "files": files, "limits": register.limits,
                "metrics": register.metrics, "cycles": sorted(register.cycles), "current_metric_registry": current}
    item = register.items.get(identifier)
    if not item:
        raise ValueError(f"Unknown initiative in this product: {identifier}")
    for kind in layout.INITIATIVE_BRIEFS:
        relative = layout.initiative_brief(product, identifier.split("/")[1], kind)
        path = private / relative
        files[kind] = {"path": relative, "present": path.resolve() == path and path.is_file()}
    if item["planning"]:
        files["planning_comparison"] = register.cycles[item["planning"]["cycle"]]["references"]["path"]
    context["initiative"] = initiative_areas.initiative_context(private, product, identifier)
    context["areas"] = initiative_areas.current_links(private, product, item["areas"])
    drafts = experiment_drafts.view(private, product, register, item)
    metric_ids = sorted(set(drafts) | set(item["targets"]) | {test["metric"] for test in item["experiments"].values()})
    initiative = {**item, "experiment_drafts": drafts}
    if item["phase"] == "shipped":
        decision = item["decisions"][-1]
        next_date = next_review(item, decision)
        initiative["outcome_review"] = {
            "status": "open" if next_date else "closed", "next_review_on": next_date,
            "reviewed_on": decision["on"] if decision["action"] == "review-outcomes" else None,
        }
    return {"product": product, "context": context, "files": files, "initiative": initiative,
            "metric_definitions": {key: register.metrics[key] for key in metric_ids},
            "current_metric_registry": {key: current[key] for key in metric_ids if key in current}}


def cell(value):
    if value is None:
        return ""
    return ", ".join(value) if isinstance(value, list) else str(value)


def csv_cell(value):
    value = cell(value)
    return "'" + value if value.lstrip().startswith(("=", "+", "-", "@")) else value


def render(template, rows, style):
    fields = template["columns"]
    if style == "json":
        return json.dumps([{key: row[key] for key in fields} for row in rows], ensure_ascii=False, indent=2)
    if style == "csv":
        output = StringIO()
        writer = csv.writer(output, lineterminator="\n")
        writer.writerow(fields)
        writer.writerows([csv_cell(row[key]) for key in fields] for row in rows)
        return output.getvalue().rstrip("\n")
    headers = tuple(fields.values())
    lines = [f"# {template['title']}", "", "| " + " | ".join(headers) + " |",
             "| " + " | ".join("---" for _ in headers) + " |"]
    for row in rows:
        values = [escape(cell(row[key])).replace("|", "&#124;") for key in fields]
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines)
