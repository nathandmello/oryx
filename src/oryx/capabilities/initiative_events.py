"""Replay validated product initiative transactions into read models."""

from datetime import date
import json
import re
from urllib.parse import urlsplit

from oryx.capabilities import brief_review
from oryx.capabilities import launch_readiness
import initiative_intake
from oryx.capabilities import metric_registry
from oryx.capabilities import outcome_evidence
import storage
from oryx.capabilities.opportunities import SLUG
from records import specific

DISCOVERY_PLAN_SCOPE = "plan-and-sources"
EXTENDED_DISCOVERY_SCOPE = "plan-sources-and-custom-sections"

OPEN_PHASES = {"inbox", "under consideration", "in discovery", "defining", "candidate", "planned", "delivery"}
IN_DEFINITION = {"inbox", "under consideration", "in discovery", "defining"}
TRANSITIONS = {
    "evaluate": ({"inbox", "under consideration"}, "under consideration"),
    "start-discovery": ({"under consideration", "in discovery"}, "in discovery"),
    "prepare-brief": ({"under consideration", "in discovery"}, "defining"),
    "approve-initiative": ({"defining"}, "candidate"),
    "plan": ({"candidate"}, "planned"),
    "unplan": ({"planned"}, "candidate"),
    "start-delivery": ({"planned"}, "delivery"),
    "ship": ({"delivery"}, "shipped"),
    "review-outcomes": ({"shipped"}, "shipped"),
    "defer": (OPEN_PHASES, "deferred"),
    "decline": (OPEN_PHASES | {"deferred"}, "declined"),
    "reopen": ({"deferred", "declined", "defining", "candidate", "planned", "delivery"}, "under consideration"),
    "expedite": ({"inbox", "under consideration", "in discovery", "defining", "candidate"}, "delivery"),
}
PHASES = ("inbox", *dict.fromkeys(phase for _, phase in TRANSITIONS.values()))
HORIZONS = ("now", "next", "later")
RISKS = ("value", "usability", "feasibility", "viability")
RESULTS = ("supported", "contradicted", "inconclusive")
OUTCOME_STATUSES = ("met", "missed", "inconclusive", "pending", "unmeasured")
SIGNAL_IMPACTS = ("routine", "material", "uncertain")
SIGNAL_ACTIONS = ("assess", "retain", "follow-up", "revise", "reopen")
AREA_SUBJECT = re.compile(rf"product/({SLUG.pattern})/area/({SLUG.pattern})")
OPTIONAL_FIELDS = {
    "capture": {"areas": "product areas"},
    "measurement": {"observation": "object", "restatement": "text"},
    "guardrail-reading": {"restatement": "text"},
    "guardrail": {"adopted_from": "object"},
    "correct-measurement": {"replacement": "slug", "comparison_source": "text"},
}

FIELDS = {
    "setup": {"company": "path", "product_context": "path", "max_open": "positive", "max_discovery": "count"},
    "limits": {"max_open": "positive", "max_discovery": "count", "source": "text"},
    "capture": {"initiative": "initiative ID", "title": "text", "source": "text", "observed_on": "past date", "summary": "text"},
    "set-areas": {"initiative": "initiative ID", "areas": "product areas", "source": "text"},
    "signal": {"initiative": "initiative ID", "source": "text", "observed_on": "past date", "summary": "text"},
    "review-signal": {"initiative": "initiative ID", "signal": "text", "claim": "optional text",
                      "impact": "signal impact", "action": "signal action", "on": "past date",
                      "reason": "text", "source": "text", "residual_risk": "optional text",
                      "follow_up": "review follow-up"},
    "describe": {"initiative": "initiative ID", "problem": "text", "audience": "text", "outcome": "text", "source": "text"},
    "metric": {"metric": "slug", "name": "text", "definition": "text", "unit": "text", "source": "text"},
    "target": {"initiative": "initiative ID", "metric": "slug", "baseline": "text", "target": "text", "due": "date",
               "guardrails": "text", "source": "text"},
    "hypothesis": {"initiative": "initiative ID", "hypothesis": "slug", "statement": "text", "risk": "risk", "source": "text"},
    "assess": {"initiative": "initiative ID", "hypothesis": "slug", "confidence": "confidence", "evidence": "text", "limits": "text"},
    "experiment": {"initiative": "initiative ID", "experiment": "experiment ID", "hypothesis": "slug", "metric": "slug",
                   "method": "text", "criterion": "text", "planned_on": "date", "source": "text"},
    "result": {"initiative": "initiative ID", "result": "slug", "experiment": "experiment ID", "observation": "text",
               "conclusion": "conclusion", "observed_on": "past date", "source": "text"},
    "measurement": {"initiative": "initiative ID", "measurement": "slug", "metric": "slug", "value": "text",
                    "observed_on": "past date", "source": "text"},
    "guardrail": {"initiative": "initiative ID", "guardrail": "slug", "metric": "slug", "operator": "bound",
                  "threshold": "number", "unit": "text", "basis": "window", "population": "text",
                  "effective_on": "date", "source": "text"},
    "guardrail-reading": {"initiative": "initiative ID", "guardrail": "slug", "metric": "slug", "measurement": "slug",
                         "value": "number", "observed_on": "past date", "source": "text", "observation": "object"},
    "correct-measurement": {"initiative": "initiative ID", "measurement": "slug", "reason": "text", "source": "text"},
    "cycle": {"cycle": "slug", "capacity": "count", "unit": "text", "starts_on": "date", "ends_on": "date", "options": "initiative IDs"},
    "decision": {"initiative": "initiative ID", "action": "transition", "on": "past date", "reason": "text", "source": "text"},
}
EVALUATION_FIELDS = {
    "value": "customer or business value, or null",
    "strategic_fit": "connection to an objective or obligation, or null",
    "urgency": "timing and consequence of waiting, or null",
    "sources": "list of distinct signal source locators already on this initiative",
    "unknowns": "unresolved questions, or null when all dimensions and sources are available",
}
DECISION_FIELDS = {
    "evaluate": {"evaluation": "evaluation"},
    "start-discovery": {"review_on": "date"},
    "plan": {"cycle": "slug", "rank": "positive", "horizon": "horizon", "effort": "positive"},
    "start-delivery": {"delivery": "URL"},
    "ship": {"review_on": "date"},
    "review-outcomes": {"outcomes": "target reviews", "follow_up": "review follow-up"},
    "defer": {"revisit": "text"},
    "expedite": {"delivery": "URL", "owner": "text", "obligation": "text", "deadline": "date", "scope": "text", "review_on": "date"},
}


def iso_date(value):
    try:
        parsed = date.fromisoformat(value)
        return parsed if parsed.isoformat() == value else None
    except (TypeError, ValueError):
        return None


def text(value):
    return (isinstance(value, str) and value == value.strip() and specific(value)
            and not re.search(r"[\x00-\x1f\x7f]", value) and bool(re.search(r"\w", value)))


RATIONALE_FIELDS = ("choice", "alternatives", "tradeoff", "owner", "scope", "reopen_when")
RATIONALE_MARK = " | Reviewed rationale: "


def reviewed_rationale(event):
    """Store optional reviewed detail in the existing reason field, readable by version 1."""
    if not isinstance(event, dict) or event.get("type") != "decision" or "rationale" not in event:
        return event
    detail = event["rationale"]
    if not isinstance(detail, dict) or set(detail) - {"review_on"} != set(RATIONALE_FIELDS):
        raise ValueError("Decision rationale needs " + ", ".join(RATIONALE_FIELDS) + " and optional review_on")
    if (not text(event.get("reason")) or RATIONALE_MARK in event["reason"] or
            not all(text(detail[key]) for key in RATIONALE_FIELDS if key != "alternatives")):
        raise ValueError("Use concrete single-line decision and rationale fields")
    alternatives = detail["alternatives"]
    if (not isinstance(alternatives, list) or not alternatives or not all(text(item) for item in alternatives)
            or len({item.casefold() for item in [detail["choice"], *alternatives]}) != len(alternatives) + 1):
        raise ValueError("Name at least one distinct credible alternative to the chosen option")
    if "review_on" in detail and (not iso_date(detail["review_on"]) or not iso_date(event.get("on"))
                                   or detail["review_on"] < event["on"]):
        raise ValueError("Set the rationale review date on or after the decision")
    if any(event[key] != detail[key] for key in {"scope", "owner", "review_on"} & event.keys() & detail.keys()):
        raise ValueError("The rationale must match the approved decision's scope, owner and review date")
    approved = {key: value for key, value in event.items() if key != "rationale"}
    approved["reason"] += RATIONALE_MARK + json.dumps(detail, ensure_ascii=False, sort_keys=True)
    return approved


def decision_rationale(event):
    """Read an optional structured suffix without reinterpreting historical free text."""
    if not isinstance(event, dict) or event.get("type") != "decision" or not isinstance(event.get("reason"), str):
        return {}
    reason, separator, detail = event["reason"].partition(RATIONALE_MARK)
    if separator:
        try:
            rationale = storage.json_input(detail)
            candidate = reviewed_rationale({**event, "reason": reason, "rationale": rationale})
            if candidate["reason"] == event["reason"]:
                return rationale
        except ValueError:
            pass
    return {}


def is_url(value):
    if not text(value) or re.search(r"\s", value):
        return False
    try:
        parsed = urlsplit(value)
        return parsed.scheme == "https" and bool(parsed.hostname) and parsed.username is None
    except ValueError:
        return False



VALIDATORS = {
    "bound": lambda v: isinstance(v, str) and v in outcome_evidence.BOUNDS,
    "window": lambda v: isinstance(v, str) and v in metric_registry.REPORTING_WINDOWS,
    "number": lambda v: outcome_evidence.number(v) is not None,
    "object": lambda v: isinstance(v, dict),
    "text": text, "path": text, "slug": lambda v: isinstance(v, str) and SLUG.fullmatch(v) is not None,
    "optional text": lambda v: v is None or text(v),
    "signal impact": lambda v: v in SIGNAL_IMPACTS,
    "signal action": lambda v: v in SIGNAL_ACTIONS,
    "experiment ID": lambda v: isinstance(v, str) and SLUG.fullmatch(v.removeprefix("experiment.")) is not None,
    "initiative ID": lambda v: isinstance(v, str) and re.fullmatch(r"[a-z0-9-]+/[a-z0-9]+(?:-[a-z0-9]+)*", v) is not None,
    "initiative IDs": lambda v: isinstance(v, list) and bool(v)
    and all(isinstance(item, str) and re.fullmatch(r"[a-z0-9-]+/[a-z0-9]+(?:-[a-z0-9]+)*", item) for item in v)
    and len(v) == len(set(v)),
    "product areas": lambda v: isinstance(v, list)
    and all(isinstance(subject, str) and AREA_SUBJECT.fullmatch(subject) for subject in v)
    and len(set(v)) == len(v),
    "positive": lambda v: type(v) is int and v > 0,
    "count": lambda v: type(v) is int and v >= 0,
    "confidence": lambda v: type(v) is int and 0 <= v <= 10,
    "date": lambda v: iso_date(v) is not None,
    "past date": lambda v: (day := iso_date(v)) is not None and day <= date.today(),
    "risk": lambda v: v in RISKS, "conclusion": lambda v: v in RESULTS,
    "transition": lambda v: isinstance(v, str) and v in TRANSITIONS,
    "horizon": lambda v: v in HORIZONS, "URL": is_url,
}


def validate_evaluation(value):
    if not isinstance(value, dict) or value.keys() != EVALUATION_FIELDS.keys():
        raise ValueError("evaluation needs " + ", ".join(EVALUATION_FIELDS))
    for key in ("value", "strategic_fit", "urgency", "unknowns"):
        if value[key] is not None and not text(value[key]):
            raise ValueError(f"evaluation.{key} needs concrete text or null")
    sources = value["sources"]
    if not isinstance(sources, list) or not all(text(source) for source in sources) or len(sources) != len(set(sources)):
        raise ValueError("evaluation.sources needs a list of distinct signal source locators")
    if value["unknowns"] is None and (not sources or any(value[k] is None for k in ("value", "strategic_fit", "urgency"))):
        raise ValueError("Describe the missing evidence or assessment in evaluation.unknowns")


def validate_target_reviews(outcomes, approved):
    if not isinstance(outcomes, dict):
        raise ValueError("Provide an outcomes object keyed by target metric ID")
    for metric, review in outcomes.items():
        if (not VALIDATORS["slug"](metric) or not isinstance(review, dict)
                or set(review) != {"status", "measurements", "assessment"}):
            raise ValueError("Each target review needs its metric ID, status, measurements, and assessment")
        status, measurements = review["status"], review["measurements"]
        if (status not in OUTCOME_STATUSES or not text(review["assessment"])
                or (not approved and not brief_review.has_answer(review["assessment"]))):
            raise ValueError(f"{metric}: provide an outcome status and a concrete PM assessment")
        if (not isinstance(measurements, list) or not all(VALIDATORS["slug"](ref) for ref in measurements)
                or len(set(measurements)) != len(measurements)):
            raise ValueError(f"{metric}: cite a list of distinct measurement IDs")
        if status in ("met", "missed", "inconclusive") and not measurements:
            raise ValueError(f"{metric}: cite measured evidence for this assessment")


def normalized_signal_review(event):
    """Compare current and historical receipts using the same human approval label."""
    reference = event["references"]
    claim = reference["claim"]
    if not isinstance(claim, dict) or not isinstance(claim.get("authority"), str):
        return event
    authority = claim["authority"]
    if not authority.startswith("PM-signed "):
        return event
    return {**event, "references": {**reference, "claim": {**claim, "authority": "PM-approved " + authority.removeprefix("PM-signed ")}}}


def validate_event(event, approved=False):
    if not isinstance(event, dict) or not isinstance(event.get("type"), str) or event["type"] not in FIELDS:
        raise ValueError("Choose a supported transaction type. Run pm.py initiative schema.")
    kind = event["type"]
    fields = FIELDS[kind]
    if kind in OPTIONAL_FIELDS:
        fields = {**fields, **{name: fmt for name, fmt in OPTIONAL_FIELDS[kind].items() if name in event}}
    if kind == "decision":
        action = event.get("action")
        if not VALIDATORS["transition"](action):
            raise ValueError("Choose a supported decision action")
        fields = {**fields, **DECISION_FIELDS.get(action, {})}
    if kind == "decision" and event["action"] == "review-outcomes" and "guardrail_dispositions" in event:
        fields = {**fields, "guardrail_dispositions": "object"}
    if kind == "measurement" and "observation" in event:
        fields = {**fields, "value": "number"}
    if approved and kind in outcome_evidence.READINGS | {"guardrail", "correct-measurement"}:
        if "recorded_on" in event:
            fields = {**fields, "recorded_on": "past date"}
        elif kind != "measurement":
            raise ValueError("Expected the approved transaction date")
    if approved and kind in outcome_evidence.READINGS | {"metric", "guardrail"} and "contract" in event:
        fields = {**fields, "contract": "object"}
    if approved and kind == "decision" and event["action"] == "review-outcomes" and "evidence_review" in event:
        fields = {**fields, "evidence_review": "object"}
    known = {"type", *fields}
    if kind == "decision" and action == "ship":
        if "exceptions" in event:
            known.add("exceptions")
            exceptions = event["exceptions"]
            if not isinstance(exceptions, dict):
                raise ValueError("Give ship exceptions by outstanding readiness ID")
            for identifier, exception in exceptions.items():
                if (not isinstance(identifier, str) or not isinstance(exception, dict)
                        or set(exception) != {"reason", "authority"} or not text(exception["authority"])
                        or not text(exception["reason"]) or not brief_review.has_answer(exception["reason"])):
                    raise ValueError("Each ship exception needs a specific reason and the approving authority")
        if approved and "readiness" in event:
            known.add("readiness")
            launch_readiness.validate_snapshot(event["readiness"])
    if approved and kind == "capture" and "intake_review" in event:
        known.add("intake_review")
    if approved and needs_reference(event):
        known.add("references")
    missing = known - event.keys()
    extra = event.keys() - known
    if missing or extra:
        raise ValueError(f"{kind}: missing {sorted(missing)}; unknown {sorted(extra)}")
    for name, value_type in fields.items():
        if value_type == "evaluation":
            # Older histories can contain the original free-text evaluation.
            if not (approved and text(event[name])):
                validate_evaluation(event[name])
        elif value_type == "target reviews":
            validate_target_reviews(event[name], approved)
        elif value_type == "review follow-up":
            follow_up = event[name]
            if follow_up is not None and not (
                isinstance(follow_up, dict) and set(follow_up) == {"on", "action"}
                and iso_date(follow_up["on"]) and text(follow_up["action"])
                and (approved or brief_review.has_answer(follow_up["action"]))
            ):
                raise ValueError("Provide a dated follow_up with on and action, or null to close")
        elif not VALIDATORS[value_type](event[name]):
            raise ValueError(f"{kind}.{name} needs {value_type}")
    if not approved and kind in {"hypothesis", "experiment"}:
        required_answers = ("statement", "source") if kind == "hypothesis" else ("method", "criterion", "source")
        for name in required_answers:
            if not brief_review.has_answer(event[name]):
                raise ValueError(f"{kind}.{name} needs a concrete answer before review")
        if kind == "experiment" and brief_review.words(event["method"]) == brief_review.words(event["criterion"]):
            raise ValueError("experiment.criterion needs a decision rule distinct from the test method")
    if approved and "references" in known:
        check_reference(event)


def needs_reference(event):
    return event["type"] in {"setup", "cycle", "review-signal"} or (
        event["type"] == "decision" and event["action"] in {"start-discovery", "prepare-brief", "approve-initiative"}
    )


def check_reference(event):
    reference = event["references"]
    if event["type"] == "review-signal":
        valid = isinstance(reference, dict) and set(reference) == {"basis", "claim"}
    elif event["type"] == "setup":
        valid = (isinstance(reference, dict) and set(reference) == {"company_id", "product_id"}
                 and all(isinstance(value, str) and re.fullmatch(r"[a-z0-9][a-z0-9-]{2,79}", value)
                         for value in reference.values()))
    else:
        keys = {"path", "id", "sha256"}
        if (event.get("action") == "start-discovery" and isinstance(reference, dict)
                and reference.get("scope") in (DISCOVERY_PLAN_SCOPE, EXTENDED_DISCOVERY_SCOPE)):
            keys.add("scope")
        valid = (event.get("action") == "prepare-brief" and reference == {}) or (
            isinstance(reference, dict) and set(reference) == keys
            and text(reference["path"]) and text(reference["id"]) and isinstance(reference["sha256"], str)
            and re.fullmatch(r"[a-f0-9]{64}", reference["sha256"])
        )
    if not valid:
        raise ValueError("Expected a verified document reference")


def identity(value):
    return " ".join(re.findall(r"\w+", value.casefold()))


def linked(items, identifier, label):
    if identifier not in items:
        raise ValueError(f"Unknown {label}: {identifier}")
    return items[identifier]


def unique(items, identifier, value, label):
    if identifier in items:
        raise ValueError(f"Duplicate {label}: {identifier}")
    items[identifier] = value


class Register:
    """Keep the latest state and the relationships needed for validation and exports."""

    def __init__(self, product):
        self.product = product
        self.setup = None
        self.limits = {}
        self.items = {}
        self.metrics = {}
        self.cycles = {}
        self.approved_at = {}
        self.sources = {}

    def add_signal(self, item, event):
        reference = event["source"].casefold()
        if reference in self.sources:
            raise ValueError(f"Source already captured under {self.sources[reference]}. Cite a distinct source or locator.")
        self.sources[reference] = item["id"]
        signal = {key: event[key] for key in ("source", "observed_on", "summary")}
        item["signals"].append(signal)
        if item["_plan_approval"]:
            selection = None
            if item["planning"]:
                decision = next(decision for decision in reversed(item["decisions"]) if decision["action"] == "plan")
                cycle = self.cycles[item["planning"]["cycle"]]
                selection = {key: decision[key] for key in ("action", "on", "source", "reason")}
                selection["comparison"] = cycle["references"]
            item["_signal_reviews"][signal["source"]] = {
                "evidence": signal, "basis": {"approval": item["_plan_approval"], "selection": selection},
                "history": [],
            }

    def accept(self, event, index):
        validate_event(event, approved=True)
        kind = event["type"]
        if any(AREA_SUBJECT.fullmatch(area)[1] != self.product for area in event.get("areas", [])):
            raise ValueError(f"Use a product area subject scoped to product/{self.product}")
        if kind == "setup":
            if index:
                raise ValueError("A product register has one setup")
            self.setup = event
            self.set_limits(event)
            return
        if self.setup is None:
            raise ValueError("Set up the product register first")
        if kind == "limits":
            self.set_limits(event)
        elif kind == "cycle":
            if event["ends_on"] < event["starts_on"]:
                raise ValueError("Planning cycle end must follow its start")
            for identifier in event["options"]:
                linked(self.items, identifier, "option in this product")
            unique(self.cycles, event["cycle"], {**event, "compared_at": index, "placements": []}, "planning cycle")
        elif kind == "metric":
            source = event["source"]
            definition = metric_registry.reference_metric(event)
            for old in self.metrics.values():
                if identity(old["name"]) != identity(event["name"]):
                    continue
                prior = old["source"]
                prior_definition = metric_registry.reference_metric(old)
                same_metric = definition and (not prior_definition or
                    prior_definition.removeprefix("company.") == definition.removeprefix("company."))
                if not (same_metric and (not prior_definition or source.rsplit("@", 1)[1] != prior.rsplit("@", 1)[1])):
                    raise ValueError("Reuse the existing metric definition")
            unique(self.metrics, event["metric"], event, "metric ID")
        elif kind == "capture":
            self.capture(event)
        else:
            item = linked(self.items, event["initiative"], "initiative in this product")
            self.update_item(item, event, index)
        self.check_limits()

    def set_limits(self, event):
        if event["max_discovery"] > event["max_open"]:
            raise ValueError("Discovery limit cannot exceed the open backlog limit")
        self.limits = {key: event[key] for key in ("max_open", "max_discovery")}

    def check_limits(self):
        if sum(item["phase"] in OPEN_PHASES for item in self.items.values()) > self.limits["max_open"]:
            raise ValueError("Open backlog limit exceeded. Review existing work with the PM.")
        if sum(item["phase"] == "in discovery" for item in self.items.values()) > self.limits["max_discovery"]:
            raise ValueError("Active discovery limit exceeded. Resolve the capacity trade-off first.")

    def capture(self, event):
        identifier = event["initiative"]
        if identifier.split("/")[0] != self.setup["references"]["product_id"]:
            raise ValueError("Initiative ID must use the registered product context ID")
        proposed_title = identity(event["title"])
        for existing in self.items.values():
            if identity(existing["title"]) == proposed_title:
                raise ValueError(f"Possible duplicate title on {existing['id']}. Review it before capture.")
        item = {
            "id": identifier, "title": event["title"], "phase": "inbox", "description": None,
            "areas": sorted(event.get("areas", [])), "areas_source": event["source"] if "areas" in event else None,
            "signals": [], "hypotheses": {}, "assessments": {}, "experiments": {}, "results": {},
            "targets": {}, "measurements": {}, "decisions": [], "planning": None, "delivery": None, "released_on": None,
            "review_trigger_measurements": [], "guardrails": {}, "corrections": {}, "evidence_changes": [],
            "discovery": None, "initiative_brief": None, "discovery_findings": None,
            "_plan_approval": None, "_signal_reviews": {},
        }
        if "intake_review" in event:
            initiative_intake.validate_review(self.items, event["intake_review"])
            item["intake_review"] = event["intake_review"]
        unique(self.items, identifier, item, "initiative ID")
        self.add_signal(item, event)

    def update_item(self, item, event, index):
        kind = event["type"]
        if kind in {"describe", "target", "hypothesis", "set-areas"} and item["phase"] not in IN_DEFINITION:
            raise ValueError(f"Reopen the initiative for review before changing {kind}")
        if kind == "signal":
            self.add_signal(item, event)
        elif kind == "review-signal":
            self.review_signal(item, event, index)
        elif kind == "set-areas":
            item["areas"] = sorted(event["areas"])
            item["areas_source"] = event["source"]
        elif kind == "describe":
            if any(other is not item and other["description"] and
                   tuple(identity(other["description"][key]) for key in ("problem", "audience")) ==
                   tuple(identity(event[key]) for key in ("problem", "audience")) for other in self.items.values()):
                raise ValueError("Possible duplicate problem and audience. Review the existing initiative.")
            item["description"] = event
        elif kind == "target":
            linked(self.metrics, event["metric"], "product metric")
            item["targets"][event["metric"]] = event
        elif kind == "hypothesis":
            unique(item["hypotheses"], event["hypothesis"], event, "hypothesis in this initiative")
        elif kind == "assess":
            linked(item["hypotheses"], event["hypothesis"], "hypothesis in this initiative")
            if item["phase"] not in IN_DEFINITION:
                raise ValueError("Reopen the initiative before revising decision-critical evidence")
            item["assessments"][event["hypothesis"]] = (index, event)
        elif kind == "experiment":
            if "." in event["experiment"] and event["experiment"] != "experiment." + event["metric"]:
                raise ValueError("The draft experiment ID must match its metric")
            linked(item["hypotheses"], event["hypothesis"], "hypothesis in this initiative")
            linked(self.metrics, event["metric"], "product metric")
            unique(item["experiments"], event["experiment"], event, "experiment in this initiative")
        elif kind == "result":
            experiment = linked(item["experiments"], event["experiment"], "experiment in this initiative")
            if event["observed_on"] < experiment["planned_on"]:
                raise ValueError("Experiment results must follow their test plan")
            unique(item["results"], event["result"], event, "result in this initiative")
        elif kind == "guardrail":
            outcome_evidence.add_rule(item, event, self.metrics.get(event["metric"]))
        elif kind in outcome_evidence.READINGS:
            metric = linked(self.metrics, event["metric"], "product metric")
            outcome_evidence.add_reading(item, event, metric)
        elif kind == "correct-measurement":
            outcome_evidence.correct(item, event, self.metrics)
        else:
            self.decide(item, event, index)

    def review_signal(self, item, event, index):
        review = linked(item["_signal_reviews"], event["signal"], "signal recorded under an approved plan")
        approval = review["basis"]["approval"]
        reference = event["references"]
        claim = reference["claim"]
        if (approval != item["_plan_approval"] or review["basis"] != reference["basis"]
                or (claim is not None and (not isinstance(claim, dict) or claim.get("text") != event["claim"]))
                or (claim is None) != (event["claim"] is None)):
            raise ValueError("Review evidence against the active approval and its linked claim")
        history = review["history"]
        if history and normalized_signal_review(history[-1]) == normalized_signal_review(event):
            raise ValueError("This signal review is already recorded")
        if event["on"] < max(approval["on"], review["evidence"]["observed_on"],
                             history[-1]["on"] if history else approval["on"]):
            raise ValueError("Signal reviews must follow the evidence, approval, and earlier reviews")
        action, impact = event["action"], event["impact"]
        if impact == "routine" and (action != "assess" or event["follow_up"] or event["residual_risk"]):
            raise ValueError("Close a routine signal with an assessment and no remaining risk or follow-up")
        if impact != "routine" and (not claim or not event["residual_risk"]):
            raise ValueError("Link a specific approved claim and state the residual risk")
        if (action == "follow-up" and not event["follow_up"]
                or action == "reopen" and event["follow_up"]
                or event["follow_up"] and event["follow_up"]["on"] < event["on"]):
            raise ValueError("A signal follow-up needs a date on or after its review; reopening ends that plan review")
        history.append(event)
        if action == "reopen":
            decision = {key: event[key] for key in ("initiative", "on", "reason", "source")}
            self.decide(item, {**decision, "type": "decision", "action": "reopen"}, index)

    def decide(self, item, event, index):
        action = event["action"]
        phase = item["phase"]
        allowed, following = TRANSITIONS[action]
        if phase not in allowed:
            raise ValueError(f"Cannot {action} from {phase}")
        earliest = item["decisions"][-1]["on"] if item["decisions"] else item["signals"][0]["observed_on"]
        if event["on"] < earliest:
            raise ValueError("Decision dates must be chronological")
        review = event.get("review_on") or event.get("revisit", "")
        if review and re.match(r"^\d{4}-", review) and (not iso_date(review) or review < event["on"]):
            raise ValueError("Review date must be on or after the decision")
        if action in {"approve-initiative", "expedite"}:
            item["_plan_approval"] = {
                "index": index, **{key: event[key] for key in ("action", "on", "source", "reason")},
                "brief": event.get("references"), "scope": event.get("scope"), "obligation": event.get("obligation"),
            }
        elif action in {"ship", "reopen", "defer", "decline"}:
            item["_plan_approval"] = None
        if action in {"start-discovery", "prepare-brief", "approve-initiative"} and not item["description"]:
            raise ValueError("Record the evidenced problem, audience, and intended outcome first")
        if action == "evaluate" and isinstance(event["evaluation"], dict):
            signals = {signal["source"]: signal for signal in item["signals"]}
            for source in event["evaluation"]["sources"]:
                signal = linked(signals, source, "signal source in this initiative")
                if signal["observed_on"] > event["on"]:
                    raise ValueError("Evaluation cannot cite a signal observed after the decision")
        if action == "start-discovery":
            if not item["hypotheses"]:
                raise ValueError("Record the decision-critical hypotheses before authorizing discovery")
            item["discovery"] = (index, event["references"])
        elif action == "prepare-brief" and phase == "in discovery":
            if not event["references"]:
                raise ValueError("Formal discovery requires approved findings")
            started, _ = item["discovery"]
            if any(item["assessments"].get(key, (-1,))[0] < started for key in item["hypotheses"]):
                raise ValueError("Assess each decision-critical hypothesis during the current timebox")
            item["discovery_findings"] = event["references"]
        elif action == "approve-initiative":
            if not item["targets"]:
                raise ValueError("Set at least one linked success metric and target before approval")
            item["initiative_brief"] = event["references"]
            self.approved_at[item["id"]] = index
        elif action == "plan":
            self.plan(item, event)
        elif action == "unplan":
            item["planning"]["reserved"] = False
            item["planning"] = None
        elif action == "ship":
            item["released_on"] = event["on"]
        elif action == "review-outcomes":
            self.review_outcomes(item, event)
        elif action in {"start-delivery", "expedite"}:
            item["delivery"] = event["delivery"]
            if item["planning"]:
                item["planning"]["started"] = True
        elif action in {"reopen", "defer", "decline"}:
            if item["planning"] and not item["planning"]["started"]:
                item["planning"]["reserved"] = False
            item.update(planning=None, delivery=None, discovery=None, initiative_brief=None, discovery_findings=None)
        item["decisions"].append(event)
        item["phase"] = following

    def review_outcomes(self, item, event):
        outcomes = event["outcomes"]
        if outcomes.keys() != item["targets"].keys():
            raise ValueError("Review every initiative target exactly once using its metric ID")
        checked = "evidence_review" in event
        if checked and event["evidence_review"] != outcome_evidence.review_snapshot(item, event, self.metrics):
            raise ValueError("The approved outcome review must match its evidence and guardrails")
        measured = set()
        for identifier, measurement in item["measurements"].items():
            if measurement["observed_on"] > event["on"]:
                raise ValueError("The outcome review cannot predate the recorded measurements")
            if not measurement.get("guardrail") and outcome_evidence.usable(item, identifier, self.metrics, checked=checked):
                measured.add(measurement["metric"])
        for metric, review in outcomes.items():
            for identifier in review["measurements"]:
                measurement = linked(item["measurements"], identifier, "measurement in this initiative")
                if not outcome_evidence.usable(item, identifier, self.metrics, checked=checked):
                    raise ValueError(f"{identifier} is unusable evidence; cite an active checked measurement")
                if measurement.get("guardrail") or measurement["metric"] != metric:
                    raise ValueError(f"{identifier} measures a different target than {metric}")
            if review["status"] == "unmeasured" and metric in measured:
                raise ValueError(f"{metric} has recorded measurements and cannot be marked unmeasured")
            if review["status"] == "pending" and event["follow_up"] is None:
                raise ValueError(f"{metric}: pending evidence needs a dated follow_up")
        follow_up = event["follow_up"]
        if follow_up is None:
            cited = {ref for review in outcomes.values() for ref in review["measurements"]}
            missing = {key for key in item["review_trigger_measurements"]
                       if outcome_evidence.usable(item, key, self.metrics, checked=checked)} - cited
            if missing:
                raise ValueError("Cite the new measurements that reopened the review: " + ", ".join(sorted(missing)))
            item["review_trigger_measurements"].clear()
        elif follow_up["on"] < event["on"]:
            raise ValueError("The follow-up date must be on or after the outcome review")
        if checked:
            item["evidence_changes"].clear()

    def plan(self, item, event):
        cycle = linked(self.cycles, event["cycle"], "planning cycle")
        if item["id"] not in cycle["options"]:
            raise ValueError("The planning cycle did not compare this initiative ID")
        if event["on"] > cycle["ends_on"]:
            raise ValueError("Cannot reserve capacity in a closed planning cycle")
        active = [placement for placement in cycle["placements"] if placement["reserved"]]
        if any(placement["rank"] == event["rank"] for placement in active):
            raise ValueError("Planning rank is already occupied in this cycle")
        if sum(placement["effort"] for placement in active) + event["effort"] > cycle["capacity"]:
            raise ValueError("Planning cycle capacity exceeded")
        placement = {**event, "reserved": True, "started": False}
        cycle["placements"].append(placement)
        item["planning"] = placement
