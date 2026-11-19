"""Check arithmetic and declared comparability for material numerical claims."""

from datetime import date, timedelta
from decimal import Decimal, DecimalException, localcontext
import re

from metric_registry import CALCULATIONS


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


def observation(item, label, issues):
    if not isinstance(item, dict):
        issues.append(f"Supply the {label} observation and its measurement basis.")
        return {}
    for name in (*METADATA, "source"):
        value = item.get(name)
        if not isinstance(value, str) or value.strip().casefold() in {"", "unknown", "n/a", "tbd"}:
            issues.append(f"Identify the {label} {name}.")
    try:
        start, end = (date.fromisoformat(item[name]) for name in ("start", "end"))
        if start >= end:
            raise ValueError()
    except (KeyError, TypeError, ValueError):
        issues.append(f"Give the {label} start and exclusive end as ordered ISO dates.")
        return dict(item, elapsed=None)
    basis = item.get("basis")
    if item.get("complete") is not True:
        issues.append(f"Confirm the {label} period is complete for the stated basis.")
    if basis in ("day", "week", "rolling 30 days") and (end - start).days != {
        "day": 1, "week": 7, "rolling 30 days": 30
    }[basis]:
        issues.append(f"The {label} window does not match its {basis} basis.")
    if basis in ("calendar month", "calendar quarter", "calendar year"):
        months = {"calendar month": 1, "calendar quarter": 3, "calendar year": 12}[basis]
        boundary = (start.day == end.day == 1 and (start.month - 1) % months == 0
                    and 12 * (end.year - start.year) + end.month - start.month == months)
        if not boundary:
            issues.append(f"The {label} window does not match its {basis} boundaries.")
    return dict(item, elapsed=(end - start).days, dates=(start, end))


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
                current.get("basis") not in ("calendar month", "calendar quarter", "calendar year")):
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
            end = date.fromisoformat(item["end"])
            if date.fromisoformat(item["start"]) < end:
                return (end - timedelta(days=1)).isoformat()
        except (KeyError, ValueError, TypeError):
            pass
    return fallback


def registry_issues(payload, kind, definitions, issues):
    for label, metric in definitions.items():
        item = payload.get(label)
        if not isinstance(item, dict):
            continue
        if not metric:
            issues.append(f"No approved definition was effective for the {label} observation.")
            continue
        reference = metric["reference"]
        if item.get("definition") != reference:
            issues.append(f"The {label} definition differs from {reference}.")
        if item.get("population") != metric["population"]:
            issues.append(f"The {label} population differs from {reference}.")
        unit = metric["unit"]
        if unit.startswith("currency"):
            matches = isinstance(item.get("unit"), str) and re.fullmatch(r"[A-Z]{3}" + re.escape(unit[8:]), item["unit"])
        else:
            matches = item.get("unit") == unit
        if not matches:
            issues.append(f"Use the {label} unit for {reference}: {unit}.")
        if kind in CALCULATIONS:
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
    if definitions and definitions.get("current"):
        result["metric_reference"] = definitions["current"]["reference"]
    return result
