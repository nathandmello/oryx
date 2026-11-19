"""Project release evidence and guardrail history from signed initiative transactions."""

from decimal import Decimal, localcontext
import operator

import brief_review
import metric_checks
import metric_registry


BOUNDS = {"lt": operator.lt, "lte": operator.le, "gt": operator.gt, "gte": operator.ge}
SYMBOLS = {"lt": "<", "lte": "≤", "gt": ">", "gte": "≥"}
READINGS = {"measurement", "guardrail-reading"}


def number(value):
    issues = []
    result = metric_checks.amount(value, "reading or threshold", issues)
    if issues:
        raise ValueError(issues[0])
    return result


def guardrail_at(revisions, cutoff):
    return next((row for row in reversed(revisions) if row["effective_on"] <= cutoff), None)


def trigger(item, event, identifier):
    if item["phase"] == "shipped":
        item["evidence_changes"].append({"type": event["type"], "id": identifier, "on": event["recorded_on"]})


def add_rule(item, event, metric):
    if not metric:
        raise ValueError("Register the guardrail metric before proposing its bound")
    if item["phase"] in {"declined", "deferred"}:
        raise ValueError("Reopen this initiative before defining a guardrail")
    number(event["threshold"])
    if not metric_checks.matches_unit(event["unit"], metric["unit"]):
        raise ValueError("Use the signed metric unit for the guardrail")
    contract = event.get("contract")
    if contract:
        basis = metric_registry.window_basis(contract)
        if basis and event["basis"] != basis:
            raise ValueError("The guardrail basis differs from the approved reporting window")
        if event["population"] != contract["population"]:
            raise ValueError("Use the approved guardrail population")
    revisions = item["guardrails"].setdefault(event["guardrail"], [])
    if revisions and revisions[-1]["metric"] != event["metric"]:
        raise ValueError("A guardrail revision must retain its metric; choose a new guardrail ID")
    cutoff = event["effective_on"]
    if revisions and cutoff <= revisions[-1]["effective_on"]:
        raise ValueError("A revised bound must take effect after its preceding revision")
    if revisions and any(row.get("guardrail") == event["guardrail"] and
                         measurement_cutoff(row) >= cutoff for row in item["measurements"].values()):
        raise ValueError("The revised bound would change an existing reading")
    adoption = event.get("adopted_from")
    if cutoff < event["recorded_on"] and not adoption:
        raise ValueError("For a historical guardrail supply dated prior evidence in adopted_from")
    if adoption:
        if (revisions or not isinstance(adoption, dict) or set(adoption) != {"target", "on", "source"}
                or not isinstance(adoption["target"], str) or adoption["target"] not in item["targets"]
                or not metric_registry.specific(adoption["source"]) or metric_registry.day(adoption["on"]).isoformat() > cutoff):
            raise ValueError("Adopt the original target's bound using its target ID, prior date and source")
    if revisions and (event["basis"], event["unit"], event["population"]) != (
            revisions[-1]["basis"], revisions[-1]["unit"], revisions[-1]["population"]):
        raise ValueError("Choose a new guardrail ID for a different measurement basis")
    revisions.append(event)
    trigger(item, event, event["guardrail"])


def measurement_cutoff(row):
    obs = row.get("observation")
    return metric_checks.observation_day(obs, row["observed_on"])


def role_key(row):
    return (row["metric"], row.get("guardrail"))


def basis_key(row):
    return tuple(row.get("observation", {}).get(key) for key in
                 ("start", "end", "basis", "timezone", "population", "unit", "definition"))


def check_reading(item, event, metric):
    obs = event.get("observation")
    rule = None
    if event["type"] == "guardrail-reading":
        revisions = item["guardrails"].get(event["guardrail"], [])
        rule = guardrail_at(revisions, measurement_cutoff(event))
        if not rule or rule["metric"] != event["metric"]:
            raise ValueError("Use the guardrail and metric effective at this reading's cutoff")
    if event["metric"] not in item["targets"] and not rule:
        raise ValueError(f"Unknown success measure in this initiative: {event['metric']}")
    if item["phase"] != "shipped" or event["observed_on"] < item["released_on"]:
        raise ValueError("Outcome measurements must follow the verified release")
    if obs is None:
        checked_target = metric_registry.reference_metric(metric) or any(
            row["metric"] == event["metric"] and row.get("observation") and not row.get("guardrail")
            for row in item["measurements"].values())
        if rule or ("recorded_on" in event and checked_target):
            raise ValueError("Supply an observation with the signed definition and reporting window")
        return
    if not metric or not isinstance(obs, dict):
        raise ValueError("Use a registered initiative metric and a structured observation")
    if obs.get("basis") not in metric_registry.REPORTING_WINDOWS:
        raise ValueError("Choose a supported reporting window for a signed observation")
    contract = event.get("contract") or (rule or {}).get("contract") or metric.get("contract")
    if contract is None:
        if metric_registry.reference_metric(metric):
            raise ValueError("Recover the signed metric definition before checking this observation")
        contract = {"reference": metric["metric"], "unit": metric["unit"],
                    "population": (rule or {}).get("population", obs.get("population")),
                    "period": "", "reporting_window": (rule or {}).get("basis", obs.get("basis"))}
    issues = metric_checks.reading_issues(obs, contract, event["observed_on"])
    if obs.get("source") != event["source"]:
        issues.append("Use the same source in the reading and observation.")
    if rule and isinstance(obs.get("start"), str) and obs["start"] < rule["effective_on"]:
        issues.append("The bound changed during this window; use a complete window under one signed threshold.")
    if rule and (obs.get("basis"), obs.get("unit"), obs.get("population")) != (
            rule["basis"], rule["unit"], rule["population"]):
        issues.append("Use the guardrail's approved window, unit and population.")
    if issues:
        raise ValueError("Ineligible observation: " + " ".join(issues))
    if measurement_cutoff(event) < item["released_on"] or obs["start"] < item["released_on"]:
        raise ValueError("The observation window must follow the verified release")
    value = number(event["value"])
    if "value" in obs and metric_checks.reading_value(obs) != value:
        raise ValueError("The observation value differs from the signed reading")
    calculation = contract.get("calculation")
    if calculation:
        with localcontext() as context:
            context.prec = 40
            computed = metric_checks.ratio({"current": obs}, calculation, issues)
            if obs.get("denominator_basis") != contract["denominator"]:
                issues.append("The eligible denominator differs from the signed definition.")
            if issues:
                raise ValueError("Ineligible observation: " + " ".join(issues))
            # Use the unrounded ratio for guardrails. A display value can be rounded at its stated precision.
            if abs(value - computed) > Decimal(5).scaleb(-min(12, max(0, -value.as_tuple().exponent)) - 1):
                raise ValueError("The reading differs from the recalculated value at its stated precision")


def breached(row, rule):
    obs = row["observation"]
    contract = row.get("contract") or rule.get("contract") or {}
    threshold = number(rule["threshold"])
    if contract.get("calculation"):
        # Compare the ratio without rounding or division, including values exactly at the threshold.
        numerator, denominator = number(obs["numerator"]), number(obs["denominator"])
        with localcontext() as context:
            context.prec = sum(len(n.as_tuple().digits) for n in (numerator, denominator, threshold)) + 4
            return not BOUNDS[rule["operator"]](numerator * 100, threshold * denominator)
    return not BOUNDS[rule["operator"]](number(row["value"]), threshold)


def add_reading(item, event, metric):
    identifier = event["measurement"]
    if identifier in item["measurements"]:
        raise ValueError(f"Duplicate measurement in this initiative: {identifier}")
    check_reading(item, event, metric)
    if "observation" in event and any(
            role_key(row) == role_key(event) and basis_key(row) == basis_key(event)
            and row["source"] == event["source"] and row["value"] == event["value"]
            and row.get("observation") == event["observation"] and key not in item["corrections"]
            for key, row in item["measurements"].items()):
        raise ValueError("This observation is already recorded; reuse its measurement ID")
    item["measurements"][identifier] = event
    decision = item["decisions"][-1]
    if decision["action"] == "review-outcomes" and decision["follow_up"] is None and event["type"] == "measurement":
        item["review_trigger_measurements"].append(identifier)
    if "recorded_on" not in event:
        return
    if event["type"] == "guardrail-reading":
        rule = guardrail_at(item["guardrails"][event["guardrail"]], measurement_cutoff(event))
        if breached(event, rule) or decision["action"] == "review-outcomes":
            trigger(item, event, identifier)
    elif decision["action"] == "review-outcomes":
        cited = decision["outcomes"][event["metric"]]["measurements"]
        if event.get("observation") or not cited or any(item["measurements"][ref]["value"] != event["value"] for ref in cited):
            trigger(item, event, identifier)


def correct(item, event):
    original = item["measurements"].get(event["measurement"])
    if not original or event["measurement"] in item["corrections"]:
        raise ValueError("Correct an active measurement in this initiative")
    if event["recorded_on"] < original["observed_on"]:
        raise ValueError("A correction cannot predate its reading")
    replacement = event.get("replacement")
    if replacement:
        new = item["measurements"].get(replacement)
        if (not new or replacement == event["measurement"] or replacement in item["corrections"]
                or any(c.get("replacement") == replacement for c in item["corrections"].values())
                or role_key(new) != role_key(original) or new["observed_on"] > event["recorded_on"]):
            raise ValueError("Choose a distinct active replacement for the same target or guardrail")
        if original.get("observation"):
            if basis_key(new) != basis_key(original):
                raise ValueError("The replacement must cover the original observation's window and basis")
        elif new["observed_on"] != original["observed_on"]:
            raise ValueError("Confirm the same observation date when replacing a legacy reading")
    item["corrections"][event["measurement"]] = event
    trigger(item, event, event["measurement"])


def usable(item, identifier, metrics, *, checked=True):
    row = item["measurements"][identifier]
    return (identifier not in item["corrections"] and
            (not checked or row.get("observation") is not None or
             not metric_registry.reference_metric(metrics[row["metric"]])))


def guardrail_summary(item, through):
    summaries = {}
    latest_target = max((measurement_cutoff(row) for ref, row in item["measurements"].items()
                         if "guardrail" not in row and ref not in item["corrections"]
                         and row["observed_on"] <= through), default=None)
    for key, revisions in item["guardrails"].items():
        current = guardrail_at(revisions, through)
        if current is None:
            continue
        readings = []
        for identifier, row in item["measurements"].items():
            if row.get("guardrail") != key or row["observed_on"] > through:
                continue
            bound = guardrail_at(revisions, measurement_cutoff(row))
            evaluated = "breached" if breached(row, bound) else "within"
            state = evaluated
            if identifier in item["corrections"]:
                state = "superseded" if item["corrections"][identifier].get("replacement") else "invalid"
            readings.append({"measurement": identifier, "value": row["value"], "source": row["source"],
                             "status": state, "assessed_as": evaluated, "cutoff": measurement_cutoff(row),
                             "bound_effective_on": bound["effective_on"]})
        statuses = {reading["status"] for reading in readings if reading["bound_effective_on"] == current["effective_on"]
                    and (not latest_target or reading["cutoff"] >= latest_target)}
        state = "within" if "within" in statuses else "unavailable"
        if any(reading["status"] == "breached" for reading in readings):
            state = "breached"
        summaries[key] = {"status": state, "bound": current, "readings": readings,
                          "target_cutoff": latest_target, "missing_current_reading": not bool(statuses & {"within", "breached"})}
    return summaries


def conflicting_readings(item):
    """Group contradictory source values for the same active target observation."""
    groups = {}
    for identifier, row in item["measurements"].items():
        if "observation" in row and "guardrail" not in row and identifier not in item["corrections"]:
            groups.setdefault((row["metric"], basis_key(row)), []).append((identifier, number(row["value"])))
    return [[ref for ref, _ in values] for values in groups.values() if len({value for _, value in values}) > 1]


def review_snapshot(item, event, metrics):
    through = event["on"]
    recent = item["evidence_changes"]
    if any(change["on"] > through for change in recent):
        raise ValueError("The review cannot predate a recorded correction, guardrail or material reading")
    guards = guardrail_summary(item, through)
    dispositions = event.get("guardrail_dispositions", {})
    if not isinstance(dispositions, dict) or dispositions.keys() - guards.keys():
        raise ValueError("Name only applicable guardrails in guardrail_dispositions")
    for name, guard in guards.items():
        if name in dispositions or guard["status"] != "within":
            reason = dispositions.get(name)
            if not metric_registry.specific(reason) or not brief_review.has_answer(reason):
                raise ValueError(f"{name} is {guard['status']}; give the PM's guardrail disposition")
    conflicts = conflicting_readings(item)
    for group in conflicts:
        metric = item["measurements"][group[0]]["metric"]
        result = event["outcomes"].get(metric, {})
        if result.get("status") in {"met", "missed"} and not set(group) <= set(result["measurements"]):
            raise ValueError("Correct or account for conflicting observations: " + ", ".join(group))
    manual = [ref for ref, row in item["measurements"].items()
              if ref not in item["corrections"] and "observation" not in row and not metric_registry.reference_metric(metrics[row["metric"]])]
    if recent:
        required = set()
        for change in recent:
            identifier = change["id"]
            if change["type"] == "correct-measurement":
                identifier = item["corrections"][identifier].get("replacement")
            if identifier and change["type"] in {"correct-measurement", "measurement"}:
                row = item["measurements"][identifier]
                if not row.get("guardrail") and usable(item, identifier, metrics):
                    required.add(identifier)
        cited = {ref for outcome in event["outcomes"].values() for ref in outcome["measurements"]}
        if required - cited:
            raise ValueError("Cite the material evidence before closing or scheduling follow-up: " + ", ".join(sorted(required - cited)))
    return {"guardrails": guards, "changes": list(recent), "conflicting_readings": conflicts,
            "manually_assessed": manual, "unusable_measurements": [
        ref for ref in item["measurements"] if not usable(item, ref, metrics)]}
