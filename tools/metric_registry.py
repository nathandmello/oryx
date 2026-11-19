"""Read SaaS defaults and approved, dated private metric definitions."""

from datetime import date
from hashlib import sha256
import json
import re

import layout
import storage


DEFAULTS = "playbook/saas-metrics.json"
PRIVATE = "context/metrics.json"
FIELDS = {"name", "aliases", "unit", "definition", "formula", "population", "period", "denominator", "notes", "source"}
OPTIONAL_FIELDS = {"calculation", "reporting_window"}
CALCULATIONS = {"proportion", "cohort_ratio"}
WINDOW_DAYS = {"day": 1, "week": 7, "rolling 30 days": 30, "snapshot": 1}
WINDOW_MONTHS = {"calendar month": 1, "calendar quarter": 3, "calendar year": 12}
REPORTING_WINDOWS = (*WINDOW_DAYS, *WINDOW_MONTHS)
LEGACY_WINDOWS = {
    "one closed calendar month": "calendar month",
    "closed 30-day reporting window": "rolling 30 days",
}
APPROVAL = {"approved_by", "effective_on", "definition"}
REFERENCE = "Metric registry "
REFERENCE_PATTERN = re.compile(re.escape(REFERENCE) + r"([a-z0-9]+(?:-[a-z0-9]+)*)@[a-f0-9]{16}")


def specific(value):
    return (isinstance(value, str) and bool(value.strip()) and value == value.strip()
            and len(value) <= 1600 and len(value.splitlines()) == 1
            and value.casefold() not in {"unknown", "tbd", "n/a"})


def day(value):
    try:
        result = date.fromisoformat(value)
        if result.isoformat() == value:
            return result
    except (ValueError, TypeError):
        pass
    raise ValueError("Use a YYYY-MM-DD effective or observation date")


def legacy_window_basis(period):
    if not isinstance(period, str):
        return None
    basis = period.casefold().removesuffix(".")
    return basis if basis in REPORTING_WINDOWS else LEGACY_WINDOWS.get(basis)


def window_basis(definition):
    if not definition:
        return None
    return definition.get("reporting_window") or legacy_window_basis(definition.get("period"))


def valid_definition(metric, definition):
    layout.slug(metric)
    if not isinstance(definition, dict) or not FIELDS <= definition.keys() <= FIELDS | OPTIONAL_FIELDS:
        raise ValueError(f"{metric}: supply each metric definition field")
    aliases = definition["aliases"]
    if (not isinstance(aliases, list) or not aliases or not all(specific(alias) for alias in aliases)
            or len({alias.casefold() for alias in aliases}) != len(aliases)):
        raise ValueError(f"{metric}: give distinct metric aliases")
    if not all(specific(definition[field]) for field in FIELDS - {"aliases"}):
        raise ValueError(f"{metric}: use specific metric values and a source reference")
    if "calculation" in definition and (definition["unit"] != "percent" or
            not isinstance(definition["calculation"], str) or definition["calculation"] not in CALCULATIONS):
        raise ValueError(f"{metric}: use a supported calculation for a percent metric")
    if "reporting_window" in definition:
        window = definition["reporting_window"]
        if window not in REPORTING_WINDOWS:
            raise ValueError(f"{metric}: choose reporting_window from {', '.join(REPORTING_WINDOWS)}")
        described = legacy_window_basis(definition["period"])
        if described and window != described:
            raise ValueError(f"{metric}: reporting_window differs from its stated period")


def defaults(root):
    path = root / DEFAULTS
    if path.resolve() != path or not path.is_file():
        raise ValueError(f"Expected the bundled definitions at {DEFAULTS}")
    definitions = storage.json_input(path.read_text(encoding="utf-8"))
    if not isinstance(definitions, dict) or not definitions:
        raise ValueError("The bundled metric registry needs a nonempty set of SaaS defaults")
    for name, definition in definitions.items():
        valid_definition(name, definition)
    return definitions


def history(private):
    path = private / PRIVATE
    if path.resolve() != path or (path.exists() and not path.is_file()):
        raise ValueError(f"Use a regular metric registry at {PRIVATE}")
    original = path.read_text(encoding="utf-8") if path.is_file() else None
    data = storage.json_input(original) if original is not None else {"version": 1, "revisions": []}
    if (not isinstance(data, dict) or data.keys() != {"version", "revisions"}
            or type(data["version"]) is not int or data["version"] != 1 or not isinstance(data["revisions"], list)):
        raise ValueError("Invalid private metric registry")
    seen = set()
    for entry in data["revisions"]:
        if not isinstance(entry, dict) or entry.keys() != APPROVAL | {"metric", "product"}:
            raise ValueError("Invalid approved metric revision")
        valid_definition(entry["metric"], entry["definition"])
        if entry["product"] is not None:
            layout.slug(entry["product"])
        if not specific(entry["approved_by"]):
            raise ValueError("Name the owner who approved this definition")
        day(entry["effective_on"])
        key = (entry["metric"], entry["product"], entry["effective_on"])
        if key in seen:
            raise ValueError(f"{entry['metric']}: a definition already exists for this scope and date")
        seen.add(key)
    return original, data


def describe(metric, definition, *, product=None, approved_by=None, effective_on=None):
    values = {"metric": metric, **definition, "product": product, "approved_by": approved_by,
              "effective_on": effective_on, "authority": "product" if product else "company" if approved_by else "industry default"}
    digest = sha256(json.dumps(values, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]
    return dict(values, reference=f"{metric}@{digest}")


def effective(root, private, product=None, through=None):
    through = through or date.today().isoformat()
    day(through)
    if product is not None:
        layout.slug(product)
    current = {metric: describe(metric, definition) for metric, definition in defaults(root).items()}
    entries = history(private)[1]["revisions"]
    for entry in sorted(entries, key=lambda row: (row["product"] is not None, row["effective_on"])):
        if entry["product"] not in (None, product) or entry["effective_on"] > through:
            continue
        current[entry["metric"]] = describe(entry["metric"], entry["definition"], product=entry["product"],
                                           approved_by=entry["approved_by"], effective_on=entry["effective_on"])
    return current


def matching(definitions, query):
    hits = []
    for row in definitions.values():
        names = [row["name"], row["metric"], *row["aliases"]]
        if any(re.search(r"(?<!\w)" + re.escape(name) + r"(?!\w)", query, re.I) for name in names):
            hits.append(row)
    return hits


def named_definitions(definitions, name):
    return [row for row in definitions.values() if name.casefold() in
            {label.casefold() for label in (row["name"], *row["aliases"])}]


def set_definition(root, private, metric, product, request, write):
    if (not isinstance(request, dict) or request.keys() != {"changes", "approved_by", "effective_on", "source"}
            or not isinstance(request["changes"], dict) or not request["changes"]
            or not request["changes"].keys() <= (FIELDS - {"source"}) | OPTIONAL_FIELDS
            or not specific(request["approved_by"]) or not specific(request["source"])):
        raise ValueError("Supply changes, the approving owner, an effective date, and the decision source")
    effective_on = day(request["effective_on"]).isoformat()
    if product:
        parent = private / layout.product(product)
        if parent.resolve() != parent or not parent.is_file():
            raise ValueError("Create the approved product context before adding a product-specific definition")

    def apply():
        original, data = history(private)
        old = effective(root, private, product, effective_on).get(metric, {})
        changes = request["changes"]
        definition = {field: old[field] for field in FIELDS | OPTIONAL_FIELDS if field in old}
        if {"formula", "unit"} & changes.keys():
            definition.pop("calculation", None)
        if "reporting_window" in old and "period" in changes and "reporting_window" not in changes:
            raise ValueError(f"{metric}: confirm reporting_window when changing the period")
        definition.update(changes, source=request["source"])
        if "reporting_window" in changes and changes["reporting_window"] is None:
            definition.pop("reporting_window")
        valid_definition(metric, definition)
        entry = {"metric": metric, "product": product, "definition": definition,
                 "approved_by": request["approved_by"], "effective_on": effective_on}
        for row in data["revisions"]:
            if (row["metric"], row["product"], row["effective_on"]) == (metric, product, effective_on):
                if row != entry:
                    raise ValueError("That scope already has a different revision on this effective date")
                return {"previous": old, "proposed": old, "written": False}
        proposed = describe(metric, definition, product=product, approved_by=entry["approved_by"], effective_on=effective_on)
        if write:
            storage.require_visible(private, PRIVATE)
            data["revisions"].append(entry)
            storage.replace_text(private / PRIVATE, original, json.dumps(data, ensure_ascii=False, indent=2) + "\n")
        return {"previous": old, "proposed": proposed, "written": write}

    if write:
        with storage.writer_lock(private):
            return apply()
    return apply()


def snapshot(root, private, product, event):
    """Bind a new initiative metric to the current revision. Existing signatures replay as written."""
    available = effective(root, private, product)
    selection = event.get("registry_metric", event.get("metric"))
    row = available.get(selection) if isinstance(selection, str) else None
    if row is None and "registry_metric" not in event and isinstance(event.get("name"), str):
        matches = named_definitions(available, event["name"])
        if len(matches) == 1:
            row = matches[0]
            selection = row["metric"]
        elif matches:
            raise ValueError("Several registry definitions match this name. Specify registry_metric.")
    if row is None:
        if "registry_metric" in event or reference_metric(event):
            raise ValueError("Choose a metric ID from pm.py metric list")
        return event
    proposal = {key: value for key, value in event.items() if key != "registry_metric"}
    expected = {"name": row["name"], "unit": row["unit"],
                "definition": f"{row['definition']} Formula: {row['formula']} Population: {row['population']} "
                              f"Period: {row['period']} Denominator: {row['denominator']}",
                "source": REFERENCE + row["reference"]}
    for key, value in expected.items():
        if key in proposal and proposal[key] != value:
            raise ValueError(f"{selection}: use the effective definition from pm.py metric show")
    return {**proposal, **expected}


def current_for_snapshot(definitions, event):
    reference = reference_metric(event)
    if reference:
        return definitions.get(reference)
    if event["metric"] in definitions:
        return definitions[event["metric"]]
    matches = named_definitions(definitions, event["name"])
    return matches[0] if len(matches) == 1 else None


def reference_metric(event):
    match = REFERENCE_PATTERN.fullmatch(str(event.get("source", "")))
    return match[1] if match else None
