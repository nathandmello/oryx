"""Check strategy evidence and select the next review step from saved records."""

from datetime import date
import re

import brief_review
import records

CONTRACT = "<!-- pm-contract: strategy-v2 -->"
PREVIOUS_CONTRACT = "<!-- pm-contract: strategy-v1 -->"
SECTIONS = {
    "Why": ("Business need", "Agreed goal"),
    "Who": ("Customer", "Customer problem"),
    "What": ("Priority rationale", "Alternatives", "Supporting evidence", "Contrary evidence"),
    "How": ("Solution hypothesis", "Expected effect", "Measure"),
}
SOURCED_FIELDS = {"Business need", "Agreed goal", "Customer", "Customer problem",
                  "Supporting evidence", "Contrary evidence", "Value test result"}
GAP_FIELDS = {"Agreed goal", "Contrary evidence", "Value test", "Value test result"}
RISK_LEADS = {
    "Value": "Product",
    "Usability": "Design",
    "Feasibility": "Engineering",
    "Viability": "Product",
}
RISK_COLUMNS = ("Risk", "Lead", "Status", "Evidence or question")
DECISION_COLUMNS = ("Status", "Choice", "Date", "Scope", "Rationale", "Source")
SOURCE_ID = re.compile(r"\[(S[1-9]\d*)\]")
ENTRY = re.compile(r"^- ([^:\n]+): (.+(?:\n  [^\n]+)*)$", re.M)


def uses_contract(text):
    return CONTRACT in text.splitlines()[1:2]


def checked_day(value, label, errors, past=False):
    try:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError
        day = date.fromisoformat(value)
    except ValueError:
        errors.append(f"{label} needs a valid YYYY-MM-DD date")
        return None
    if past and day > date.today():
        errors.append(f"{label} cannot be in the future")
    return day


def known_sources(text):
    rows, _ = records.table(text, "Sources", records.SOURCE_COLUMNS)
    return {row[0] for row in rows if re.fullmatch(r"S[1-9]\d*", row[0])}


def cited(value, sources):
    references = set(SOURCE_ID.findall(value))
    return bool(references) and references <= sources


def section_errors(text, heading, fields, sources):
    body = records.section(text, heading)
    if body is None:
        return [f"use exactly one {heading} section"]
    entries = ENTRY.findall(body)
    errors = []
    for field in fields:
        values = [value for label, value in entries if label == field]
        if len(values) != 1 or not brief_review.has_answer(values[0]):
            errors.append(f"{field} needs one concrete entry")
            continue
        value = values[0]
        if value.startswith("Gap:"):
            if field not in GAP_FIELDS or not records.specific(value.split(":", 1)[1].strip()):
                errors.append(f"{field} needs a substantive entry before review")
        elif field in SOURCED_FIELDS and not cited(value, sources):
            errors.append(f"{field} needs a valid source ID")
    return errors


def risk_errors(text, sources):
    leads = RISK_LEADS if uses_contract(text) else {**RISK_LEADS, "Viability": "Product and business owners"}
    rows, errors = records.table(text, "Risks and tradeoffs", RISK_COLUMNS)
    if not errors:
        if sorted(row[0] for row in rows) != sorted(leads):
            errors.append("record Value, Usability, Feasibility, and Viability once each")
        for risk, lead, status, entry in rows:
            if risk in leads and lead != leads[risk]:
                errors.append(f"{risk} lead must be {leads[risk]}")
            if status not in {"open", "assessed"} or not records.specific(entry):
                errors.append(f"{risk} needs an open question or an owner assessment")
            elif status == "assessed" and not cited(entry, sources):
                errors.append(f"{risk} assessment needs a valid source ID")
    body = records.section(text, "Risks and tradeoffs") or ""
    blockers = re.findall(r"^- Blockers: (.+)$", body, re.M)
    if len(blockers) != 1 or not (blockers[0] == "none" or records.specific(blockers[0])):
        errors.append("record blockers separately or write none")
    return errors


def value_errors(text, sources, for_review=False):
    body = records.section(text, "Risks and tradeoffs") or ""
    validation = [value for label, value in ENTRY.findall(body) if label == "Value validation"]
    if validation == ["open"] or (not for_review and "validated" not in validation):
        return []
    if validation != ["validated"]:
        return ["Value validation must be open or validated"]

    errors = []
    risks, _ = records.table(text, "Risks and tradeoffs", RISK_COLUMNS)
    if not any(risk == "Value" and lead == RISK_LEADS["Value"] and status == "assessed" and cited(entry, sources)
               for risk, lead, status, entry in risks):
        errors.append("validated value needs Product's sourced value assessment")
    how = ENTRY.findall(records.section(text, "How") or "")
    tests = [value for label, value in how if label == "Value test"]
    if len(tests) != 1 or tests[0].startswith("Gap:") or not records.specific(tests[0]):
        errors.append("validated value needs its hypothesis and experiment")
    results = [value for label, value in how if label == "Value test result"]
    if len(results) != 1 or results[0].startswith("Gap:") or not cited(results[0], sources):
        errors.append("validated value needs a sourced test result")
    if not for_review:
        errors.extend(source_errors(text))
    return errors


def decision_errors(text, sources, for_review=False):
    rows, errors = records.table(text, "Decisions", DECISION_COLUMNS)
    if errors:
        return errors
    filled = [row for row in rows if not all(records.PLACEHOLDER.fullmatch(cell) for cell in row)]
    if for_review and not filled:
        errors.append("record a proposal or a PM decision")
    for status, choice, decided, scope, rationale, source in filled:
        if for_review and status not in {"proposed", "accepted"}:
            errors.append("decision status must be proposed or accepted")
        if (for_review or status == "accepted") and not all(map(records.specific, (choice, scope, rationale))):
            errors.append("each decision needs a choice, scope, and rationale")
        if status == "accepted":
            checked_day(decided, "Accepted decision date", errors, past=True)
            if not cited(source, sources):
                errors.append("an accepted decision needs a valid PM decision source ID")
    return errors


def source_errors(text):
    date_errors = []
    records_errors = records.source_errors(
        text, lambda value, label, past=False: checked_day(value, label, date_errors, past)
    )
    return records_errors + date_errors


def review_errors(text):
    sources = known_sources(text)
    current = uses_contract(text)
    stages = {"Sources": source_errors(text)}
    for heading, fields in SECTIONS.items():
        if heading == "How" and current:
            if not brief_review.has_answer(records.section(text, "When")):
                stages["When"] = ["state the decision horizon, the cost of waiting, and the review trigger"]
            fields += ("Value test", "Value test result")
        stages[heading] = section_errors(text, heading, fields, sources)
    stages["Risks and tradeoffs"] = risk_errors(text, sources)
    if current:
        stages["Risks and tradeoffs"].extend(value_errors(text, sources, for_review=True))
    stages["Decisions"] = decision_errors(text, sources, for_review=True)
    return stages


def check(text):
    marker = records.MARKER.match(text)
    if not marker or marker[1] != "strategy":
        return []
    values, _ = records.work_state(text)
    if not uses_contract(text) and PREVIOUS_CONTRACT not in text.splitlines()[1:2]:
        return []
    if values.get("State") == "complete":
        return [f"{heading}: {error}" for heading, errors in review_errors(text).items() for error in errors]
    sources = known_sources(text)
    errors = [f"Decisions: {error}" for error in decision_errors(text, sources)]
    if uses_contract(text):
        errors.extend(f"Risks and tradeoffs: {error}" for error in value_errors(text, sources))
    rows, _ = records.table(text, "Decisions", DECISION_COLUMNS)
    if any(row[0] == "accepted" for row in rows):
        errors.extend(f"Sources: {error}" for error in source_errors(text))
    return errors


def next_step(text):
    values, _ = records.work_state(text)
    _, issues = records.state_errors(text)
    result = {
        "record_id": values.get("ID"),
        "state": values.get("State"),
        "mode": values.get("Mode"),
        "last_checkpoint": values.get("Last checkpoint"),
        "next_action": values.get("Next action"),
        "waiting_on": values.get("Waiting on"),
        "resume_when": values.get("Resume when"),
        "step": None,
        "issues": issues,
    }
    if issues:
        result["step"] = "repair-work-state"
    elif values["State"] == "waiting" or records.specific(values["Waiting on"]):
        result["step"] = "waiting"
    elif not uses_contract(text):
        result["step"] = "legacy-record"
    else:
        result["step"] = "ready-for-pm-review" if values["State"] != "complete" else "complete"
        for heading, errors in review_errors(text).items():
            if errors:
                result.update(step=heading, issues=errors)
                break
    return result
