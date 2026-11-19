"""Check arithmetic and declared comparability for material numerical claims."""

from datetime import date, timedelta
from decimal import Decimal, DecimalException, localcontext
import re

from metric_registry import CALCULATIONS, WINDOW_DAYS, WINDOW_MONTHS, day, window_basis


METRIC = re.compile(r"\b(?:churn|revenue|margin|retention|conversion|growth|forecast|denominator|numerator|"
                    r"percentage|metric|kpi|year.over.year|month.over.month|(?:follow|compare).{0,30}numbers)\b"
                    r"|(?:\d\s*%|[$€£]\s*\d)", re.I)
CLAIM = re.compile(r"\b(?:revenue|churn|retention|conversion|margin|growth|rate|percentage|share)\b", re.I)
METADATA = ("definition", "population", "unit", "basis", "timezone")


def is_claim(text):
    return bool(CLAIM.search(text) and re.search(r"\d", text))


def amount(value, name, issues):
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        issues.append(f"Supply {name} as a finite number.")
        return None
    try:
        number = Decimal(str(value))
        if not number.is_finite() or (number and abs(number.adjusted()) > 100):
            raise ValueError()
        return number
    except (ValueError, DecimalException):
        issues.append(f"Supply {name} as a finite number within the supported range.")
        return None


def reading_value(item):
    issues = []
    value = amount(item.get("value") if isinstance(item, dict) else None, "observed value", issues)
    if issues:
        raise ValueError(issues[0])
    return value


def observation_dates(item):
    start, end = (day(item[name]) for name in ("start", "end"))
    if start >= end:
        raise ValueError("The observation start must precede its exclusive end")
    return start, end


def observation(item, label, issues, *, through=None):
    if not isinstance(item, dict):
        issues.append(f"Supply the {label} observation and its measurement basis.")
        return {}
    for name in (*METADATA, "source"):
        value = item.get(name)
        if not isinstance(value, str) or value.strip().casefold() in {"", "unknown", "n/a", "tbd"}:
            issues.append(f"Identify the {label} {name}.")
    try:
        start, end = observation_dates(item)
    except (KeyError, ValueError):
        issues.append(f"Give the {label} start and exclusive end as ordered ISO dates.")
        return dict(item, elapsed=None, dates=None)
    elapsed = (end - start).days
    cutoff = through if through is not None else date.today()
    if (end - timedelta(days=1)) > cutoff:
        issues.append(f"The {label} window includes dates after {cutoff.isoformat()}.")
    basis = item.get("basis")
    if item.get("complete") is not True:
        issues.append(f"Confirm the {label} period is complete for the stated basis.")
    if isinstance(basis, str):
        days = WINDOW_DAYS.get(basis)
        if days is not None and elapsed != days:
            issues.append(f"The {label} window does not match its {basis} basis.")
        months = WINDOW_MONTHS.get(basis)
        if months is not None and (
            start.day != 1 or end.day != 1 or (start.month - 1) % months != 0
            or 12 * (end.year - start.year) + end.month - start.month != months
        ):
            issues.append(f"The {label} window does not match its {basis} boundaries.")
    return dict(item, elapsed=elapsed, dates=(start, end))


def comparison(payload, kind, issues):
    current = observation(payload.get("current"), "current", issues)
    baseline = observation(payload.get("baseline"), "baseline", issues)
    for name in METADATA:
        if current.get(name) and baseline.get(name) and current[name] != baseline[name]:
            issues.append(f"The current and baseline {name} differ.")
    if current.get("dates") and baseline.get("dates"):
        if baseline["dates"][1] > current["dates"][0]:
            issues.append("Baseline and current windows overlap or are out of order.")
        if (current.get("elapsed") != baseline.get("elapsed") and
                current.get("basis") not in tuple(WINDOW_MONTHS)):
            issues.append("The comparison windows cover different numbers of days.")
    if kind == "percentage_points" and (current.get("unit"), baseline.get("unit")) != ("percent", "percent"):
        issues.append("Enter both rates in percent units for a percentage-point change.")
    value = amount(current.get("value"), "current value", issues)
    previous = amount(baseline.get("value"), "baseline value", issues)
    if value is None or previous is None or issues:
        return None
    if kind == "percentage_points":
        return value - previous
    if previous <= 0:
        issues.append("A nonpositive baseline does not support a conventional growth percentage. Give levels or absolute change.")
        return None
    return (value - previous) / previous * 100


def ratio(payload, kind, issues):
    current = observation(payload.get("current"), "rate", issues)
    numerator = amount(current.get("numerator"), "numerator", issues)
    denominator = amount(current.get("denominator"), "denominator", issues)
    denominator_basis = current.get("denominator_basis")
    if not isinstance(denominator_basis, str) or denominator_basis.strip().casefold() in {"", "unknown", "n/a", "tbd"}:
        issues.append("Say who is eligible for the denominator and when they are counted.")
    if kind == "proportion" and current.get("numerator_subset") is not True:
        issues.append("Check that the numerator only counts eligible members of the denominator.")
    if kind == "cohort_ratio" and current.get("same_cohort") is not True:
        issues.append("Check that numerator and denominator measure the same opening cohort.")
    if current.get("unit") != "percent":
        issues.append("Use percent units for this calculation.")
    if denominator is not None and denominator <= 0:
        issues.append("This calculation needs a positive denominator.")
    if kind == "proportion" and numerator is not None and denominator is not None and not 0 <= numerator <= denominator:
        issues.append("The numerator must be between zero and its eligible denominator.")
    if kind == "cohort_ratio" and numerator is not None and numerator < 0:
        issues.append("The closing cohort amount must be nonnegative.")
    return numerator / denominator * 100 if not issues else None


def observation_day(item, fallback):
    if isinstance(item, dict):
        try:
            _, end = observation_dates(item)
            return (end - timedelta(days=1)).isoformat()
        except (KeyError, ValueError):
            pass
    return fallback


def matches_unit(unit, approved_unit):
    if approved_unit.startswith("currency"):
        return isinstance(unit, str) and re.fullmatch(r"[A-Z]{3}" + re.escape(approved_unit[8:]), unit) is not None
    return unit == approved_unit


def registry_observation_issues(item, label, definition, issues):
    reference = definition["reference"]
    if item.get("definition") != reference:
        issues.append(f"The {label} definition differs from {reference}.")
    if item.get("population") != definition["population"]:
        issues.append(f"The {label} population differs from {reference}.")
    unit = definition["unit"]
    if not matches_unit(item.get("unit"), unit):
        issues.append(f"Use the {label} unit for {reference}: {unit}.")
    approved_basis = window_basis(definition)
    if approved_basis is not None and item.get("basis") != approved_basis:
        issues.append(f"The {label} basis differs from the approved reporting window. Use {approved_basis} for {reference}.")


def reading_issues(item, definition, observed_on):
    """Check declared evidence against the signed definition and observation date."""
    issues = []
    cutoff = observed_on if type(observed_on) is date else day(observed_on)
    reading = observation(item, "reading", issues, through=cutoff)
    if not isinstance(item, dict):
        return issues
    if not definition:
        return issues + ["Supply the approved definition for the reading."]
    registry_observation_issues(item, "reading", definition, issues)
    dates = reading.get("dates")
    effective_on = definition.get("effective_on")
    if dates and effective_on and day(effective_on) >= dates[1]:
        issues.append("The approved definition was not effective by the reading cutoff.")
    return issues


def registry_issues(payload, kind, definitions, issues):
    for label, metric in definitions.items():
        item = payload.get(label)
        if not isinstance(item, dict):
            continue
        if not metric:
            issues.append(f"No approved definition was effective for the {label} observation.")
            continue
        registry_observation_issues(item, label, metric, issues)
        if kind in CALCULATIONS:
            reference = metric["reference"]
            if kind != metric.get("calculation"):
                issues.append(f"The {kind} calculation does not match {reference}. Check its approved formula.")
            if item.get("denominator_basis") != metric["denominator"]:
                issues.append(f"The eligible denominator differs from {reference}.")
    current, baseline = definitions.get("current"), definitions.get("baseline")
    if current and baseline and current["reference"] != baseline["reference"]:
        issues.append("The approved definition changed between periods. Verify a restatement on a shared basis before comparing.")


def check(payload, definitions=None):
    if not isinstance(payload, dict) or payload.get("kind") not in ("growth", "percentage_points", "proportion", "cohort_ratio"):
        raise ValueError("Choose kind growth, percentage_points, proportion, or cohort_ratio")
    kind = payload["kind"]
    issues = []
    with localcontext() as context:
        context.prec = 40
        computed = ratio(payload, kind, issues) if kind in CALCULATIONS else comparison(payload, kind, issues)
        if definitions:
            registry_issues(payload, kind, definitions, issues)
        reported = amount(payload["reported"], "reported result", issues) if "reported" in payload else None
        if computed is not None and reported is not None:
            precision = min(12, max(0, -reported.as_tuple().exponent))
            if abs(computed - reported) > Decimal(5).scaleb(-precision - 1):
                issues.append("The reported value does not match the recalculation at its stated precision.")
        value = format(computed.normalize(), "f") if computed is not None else None
    result = {"status": "needs_review" if issues else "consistent", "value": value,
              "unit": "percentage points" if kind == "percentage_points" else "percent", "issues": issues}
    if definitions:
        result["approved_reporting_windows"] = {label: window_basis(row) for label, row in definitions.items()}
        unconfirmed = [label for label, row in definitions.items() if row and not window_basis(row)]
        if unconfirmed:
            result["window_notes"] = [
                f"Confirm the {label} reporting window against the period description; its approved basis is unspecified."
                for label in unconfirmed]
        if definitions.get("current"):
            result["metric_reference"] = definitions["current"]["reference"]
    return result
