"""Project backlog, roadmap, and trace views from verified initiative records."""

import csv
from datetime import date
from hashlib import sha256
from html import escape
from io import StringIO
import json

import brief_review
import evidence_reviews
import experiment_drafts
import initiative_areas
import layout
import metric_registry
import outcome_evidence
import records
from initiative_events import HORIZONS, IN_DEFINITION, PHASES, RATIONALE_MARK, decision_rationale, iso_date, text

BACKLOG_FIELDS = {
    "product", "id", "title", "problem", "audience", "phase", "rank", "effort", "unit",
    "captured_on", "last_decision_on", "revisit", "sources", "areas", "evidence_reviews", "outcome_risks",
}
ROADMAP_FIELDS = {
    "product", "cycle", "horizon", "rank", "id", "title", "outcome", "success_metrics", "phase",
    "effort", "unit", "period_start", "period_end", "trade_off", "planning_record", "delivery", "areas",
    "evidence_reviews",
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
    scheduled = decision.get("review_on") or decision.get("revisit")
    dates = [change["on"] for change in item["evidence_changes"]]
    if decision.get("action") == "review-outcomes":
        follow = decision["follow_up"]
        triggers = item["review_trigger_measurements"]
        if follow:
            scheduled = follow["on"]
        elif triggers:
            scheduled = item["measurements"][triggers[0]]["observed_on"]
        for revisions in item["guardrails"].values():
            dates.extend(rule["effective_on"] for rule in revisions if rule["effective_on"] > decision["on"])
    if dates:
        if iso_date(scheduled):
            dates.append(scheduled)
        return min(dates)
    return scheduled


def signed_claim_reason(snapshot):
    event = {"type": "decision", "reason": snapshot["reason"], "on": snapshot["on"]}
    if decision_rationale(event):
        return event["reason"].partition(RATIONALE_MARK)[0]
    return event["reason"]


def signal_claims(private, basis):
    approval, selection = basis["approval"], basis["selection"]
    brief = approval["brief"]
    claims = []
    if private is not None and brief:
        path = private / brief["path"]
        try:
            if path.resolve() == path and path.is_file():
                contents = path.read_bytes()
                if sha256(contents).hexdigest() == brief["sha256"]:
                    prose = brief_review.visible(contents.decode("utf-8"))
                    for section in ("Assumptions and risks", "Approach and scope", "Proposal"):
                        for line in (records.section(prose, section) or "").splitlines():
                            claim = line.strip().removeprefix("- ")
                            if text(claim):
                                claims.append({"text": claim, "authority": "PM-approved Initiative Brief",
                                               "record": brief["path"], "section": section, "revision": brief["sha256"],
                                               "source": approval["source"]})
        except (OSError, UnicodeError):
            pass
    for field in ("scope", "obligation", "reason"):
        if approval[field]:
            claims.append({"text": signed_claim_reason(approval) if field == "reason" else approval[field],
                           "authority": "PM-signed " + approval["action"],
                           "source": approval["source"]})
    if selection:
        claims.append({"text": signed_claim_reason(selection), "authority": "PM-signed plan",
                       "source": selection["source"], "record": selection["comparison"]["path"],
                       "revision": selection["comparison"]["sha256"]})
    return claims


def signal_reviews(private, item):
    reviews = []
    for source, review in item.get("_signal_reviews", {}).items():
        active = review["basis"]["approval"] == item["_plan_approval"]
        last = review["history"][-1] if review["history"] else None
        state, reason, follow_up, claims, review_on = (
            "needs-triage", "Compare new evidence with the approved approach.", None, [],
            review["evidence"]["observed_on"],
        )
        if last:
            state = {"retain": "retained", "reopen": "reopened"}.get(last["action"], last["action"])
            if state == "assess":
                state = last["impact"]
            reason, follow_up = last["reason"], last["follow_up"]
            if last["references"]["claim"]:
                claims = [last["references"]["claim"]]
            if follow_up:
                review_on = follow_up["on"]
            elif state in {"routine", "retained", "reopened"}:
                review_on = None
        elif active and private is not None:
            claims = signal_claims(private, review["basis"])[:5]
        if not active and state in {"needs-triage", "material", "uncertain", "follow-up", "revise"}:
            state = "archived"
        reviews.append({
            "id": source, "state": state, "reason": reason, "claims": claims, "active": active,
            "evidence": review["evidence"], "basis": review["basis"], "follow_up": follow_up,
            "review_on": review_on if active else None, "history": review["history"],
            "residual_risk": last["residual_risk"] if last else None,
        })
    return reviews


def evidence_review_labels(reviews):
    labels = []
    for review in reviews:
        if not review["active"] or review["state"] == "routine":
            continue
        claim = f" ({review['claims'][0]['text']})" if review["claims"] else ""
        evidence = review.get("evidence", {}).get("summary")
        description = f"{evidence} — {review['reason']}" if evidence else review["reason"]
        labels.append(f"{review['state']}: {review['id']}{claim} — {description}")
    return labels


def backlog(registrations, phase=None, due=False, all_phases=False, *, area=None, private=None):
    phases = IN_DEFINITION | {"candidate"}
    if phase is not None:
        phases = {phase}
    elif due or all_phases:
        phases = set(PHASES)
    rows = []
    context_reviews = evidence_reviews.workspace_reviews(private)
    for product, register in registrations:
        for item in register.items.values():
            if item["phase"] not in phases or (area is not None and area not in item["areas"]):
                continue
            decision = item["decisions"][-1] if item["decisions"] else {}
            revisit = next_review(item, decision)
            review_date = iso_date(revisit)
            reviews = signal_reviews(private, item)
            reviews += evidence_reviews.for_initiative(private, product, item, reviews=context_reviews)
            review_dates = [iso_date(review["review_on"]) for review in reviews if review["review_on"]]
            if review_dates and (not review_date or min(review_dates) < review_date):
                review_date = min(review_dates)
                revisit = review_date.isoformat()
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
                "outcome_risks": outcome_risks(item),
                "evidence_reviews": evidence_review_labels(reviews),
            })
    return sorted(rows, key=lambda row: (
        row["product"], PHASES.index(row["phase"]), row["rank"] or float("inf"), row["captured_on"], row["id"],
    ))


def roadmap(registrations, cycle_filter=None, *, area=None, private=None):
    rows = []
    matched = False
    context_reviews = evidence_reviews.workspace_reviews(private)
    for product, register in registrations:
        matched = matched or cycle_filter in register.cycles
        for item in register.items.values():
            placement = item["planning"]
            if placement is None or (cycle_filter is not None and placement["cycle"] != cycle_filter):
                continue
            if area is not None and area not in item["areas"]:
                continue
            cycle = register.cycles[placement["cycle"]]
            reviews = signal_reviews(private, item)
            reviews += evidence_reviews.for_initiative(private, product, item, reviews=context_reviews)
            rows.append({
                "product": product, "id": item["id"], "title": item["title"], "phase": item["phase"],
                "areas": item["areas"],
                "outcome": item["description"]["outcome"], "success_metrics": sorted(item["targets"]),
                "cycle": placement["cycle"], "rank": placement["rank"], "horizon": placement["horizon"],
                "effort": placement["effort"], "unit": cycle["unit"],
                "trade_off": decision_rationale(placement).get("tradeoff", placement["reason"]),
                "period_start": cycle["starts_on"], "period_end": cycle["ends_on"],
                "planning_record": cycle["references"]["path"], "delivery": item["delivery"],
                "evidence_reviews": evidence_review_labels(reviews),
            })
    if cycle_filter is not None and not matched:
        raise ValueError(f"Unknown planning cycle: {cycle_filter}")
    return sorted(rows, key=lambda row: (
        row["product"], row["period_start"], row["cycle"], HORIZONS.index(row["horizon"]), row["rank"],
    ))


def outcome_risks(item):
    if item["phase"] != "shipped":
        return []
    summary = outcome_evidence.guardrail_summary(item, date.today().isoformat())
    risks = []
    for name, row in summary.items():
        rule = row["bound"]
        if row["status"] != "within":
            label = f"{name}: {row['status']} ({outcome_evidence.SYMBOLS[rule['operator']]} {rule['threshold']} {rule['unit']})"
            risks.append(label)
        if row["missing_current_reading"] and row["status"] == "breached":
            risks.append(f"{name}: no usable reading for the current bound")
    for group in outcome_evidence.conflicting_readings(item):
        risks.append("Conflicting target readings: " + ", ".join(group))
    if item["decisions"][-1]["action"] == "review-outcomes":
        for target, result in item["decisions"][-1]["outcomes"].items():
            if result["status"] in {"inconclusive", "pending", "unmeasured"}:
                risks.append(f"{target}: {result['status']}")
    risks.extend(f"{change['type']}: {change['id']} awaits review" for change in item["evidence_changes"])
    adopted = {rule["adopted_from"]["target"] for revisions in item["guardrails"].values()
               for rule in revisions if "adopted_from" in rule}
    for target, row in item["targets"].items():
        if target not in adopted and row["guardrails"].strip().lower() not in {"none", "no guardrails"}:
            risks.append(f"{target}: review guardrail note — {row['guardrails']}")
    return risks


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
    metric_ids = sorted(set(metric_ids) | {row["metric"] for revisions in item["guardrails"].values() for row in revisions})
    initiative = {key: value for key, value in item.items() if not key.startswith("_")}
    initiative.update(experiment_drafts=drafts, signal_reviews=signal_reviews(private, item),
                      context_risks=evidence_reviews.for_initiative(private, product, item))
    if item["phase"] == "shipped":
        ship = next(event for event in reversed(item["decisions"]) if event["action"] == "ship")
        initiative["launch_review"] = ("Recorded in the signed ship decision." if "readiness" in ship
                                       else "Readiness was not recorded in this historical ship decision.")
        initiative["guardrail_results"] = outcome_evidence.guardrail_summary(item, date.today().isoformat())
        initiative["outcome_risks"] = outcome_risks(item)
        initiative["conflicting_readings"] = outcome_evidence.conflicting_readings(item)
        initiative["unusable_measurements"] = [ref for ref in item["measurements"]
                                               if not outcome_evidence.usable(item, ref, register.metrics)]
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
