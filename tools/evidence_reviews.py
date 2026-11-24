"""Connect scoped evidence to decisions and keep review history in the owning record."""

from datetime import date
from hashlib import sha256
from itertools import chain, combinations, product
import json
import re

import layout
import records
import storage

HEADING = "Evidence review history"
RISK_LANGUAGE = re.compile(
    r"\b(?:prohibit\w*|forbid\w*|blocked?|blocks?|cannot|must not|not permitted|"
    r"invalidat\w*|contradict\w*|without (?:consent|approval|clearance|sign-off))\b", re.I)
STOP = set("a an the for and from can could when which where who what whether does is are must should will "
           "before after until under without with all some on in to of this that do our sign off".split())
GATE = re.compile(r"\b(?:must|require[sd]?|only after|subject to)\b.{0,80}\b(?:approv\w*|clearance|sign.off|consent|authori[sz]ation)\b", re.I)
OPEN = {"open", "follow-up", "retain"}


def identifier(*parts):
    raw = json.dumps(parts, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return "risk-" + sha256(raw.encode()).hexdigest()[:20]


def history(text):
    if HEADING not in text:
        return []
    if text.count("## " + HEADING) > 1 and sum(heading == HEADING for heading, *_ in records.section_blocks(text)) > 1:
        raise ValueError(f"Duplicate {HEADING} section")
    body = records.section(text, HEADING)
    if body is None:
        return []
    lines = body.strip().splitlines()
    if len(lines) < 3 or lines[0] != "```jsonl" or lines[-1] != "```":
        raise ValueError(f"Invalid {HEADING} section. Restore its recorded events.")
    events = [storage.json_input(line) for line in lines[1:-1]]
    seen = set()
    for event in events:
        if (not isinstance(event, dict) or not isinstance(event.get("id"), str)
                or not re.fullmatch(r"risk-[0-9a-f]{20}", event["id"])
                or not isinstance(event.get("state"), str)
                or event["state"] not in OPEN | {"dismiss", "resolve"}
                or not isinstance(event.get("reason"), str) or not event["reason"].strip()
                or not isinstance(event.get("on"), str)):
            raise ValueError(f"Invalid {HEADING} event")
        if date.fromisoformat(event["on"]).isoformat() != event["on"]:
            raise ValueError(f"Invalid event date in {HEADING}")
        if event["state"] == "open":
            if (event["id"] in seen or not isinstance(event.get("claims"), list) or not event["claims"]
                    or any(not isinstance(c, dict) or not isinstance(c.get("text"), str) for c in event["claims"])
                    or not isinstance(event.get("scope"), dict)
                    or event["scope"].keys() != {"product", "area", "initiative"}
                    or any(v is not None and not isinstance(v, str) for v in event["scope"].values())
                    or not isinstance(event.get("classification"), str)
                    or not isinstance(event.get("targets"), list)
                    or any(not isinstance(t, str) for t in event["targets"])):
                raise ValueError(f"Invalid opening event in {HEADING}")
            seen.add(event["id"])
        else:
            if event["id"] not in seen or not isinstance(event.get("source"), str):
                raise ValueError(f"Missing original review or PM source in {HEADING}")
            day = event.get("review_on")
            if (event["state"] == "follow-up") != bool(day) or (day and (
                    not isinstance(day, str) or date.fromisoformat(day).isoformat() != day or day < event["on"])):
                raise ValueError(f"Invalid follow-up date in {HEADING}")
    return events


def append(text, additions):
    if not additions:
        return text
    # The fenced data must never create markup, a local link, or a citation in its owner.
    def encode(event):
        value = json.dumps(event, ensure_ascii=True, sort_keys=True)
        def escape_string(match):
            result = match[0]
            for char in "<>[]{}`":
                result = result.replace(char, "\\u" + format(ord(char), "04x"))
            return result
        return re.sub(r'"(?:\\.|[^"\\])*"', escape_string, value)

    lines = "\n".join(encode(event) for event in additions)
    blocks = {name: (start, content, end) for name, start, content, end in records.section_blocks(text)}
    if HEADING in blocks:
        _, content, end = blocks[HEADING]
        boundary = text.rindex("\n```", content, end)
        return text[:boundary] + "\n" + lines + text[boundary:]
    start = blocks["Context controls"][0]
    return text[:start] + f"## {HEADING}\n\n```jsonl\n{lines}\n```\n\n" + text[start:]


def latest(events, through=None):
    reviews = {}
    for event in events:
        if through and event["on"] > through:
            continue
        key = event["id"]
        if event["state"] == "open":
            reviews.setdefault(key, {**event, "history": [event]})
        elif key in reviews:
            reviews[key]["state"] = event["state"]
            reviews[key]["history"].append(event)
            reviews[key]["disposition"] = event
            reviews[key]["review_on"] = event.get("review_on")
    return reviews


def scope_for(doc, area=None):
    return {"product": doc["product"], "area": area or doc["area"], "initiative": doc["initiative"]}


def compatible(a, b):
    return all(not a.get(k) or not b.get(k) or a[k] == b[k] for k in ("product", "area", "initiative"))


def applicable(review, scope, areas=()):
    map_review = layout.stakeholder_record(review.get("owner", ""))
    if (map_review and not scope.get("stakeholders")
            or not map_review and scope.get("stakeholders") and not scope.get("product")):
        return False
    own = review["scope"]
    if own.get("product") and own["product"] != scope.get("product"):
        return False
    if own.get("initiative") and own["initiative"] != scope.get("initiative"):
        return False
    return not own.get("area") or own["area"] in {*areas, scope.get("area")}


def claims(doc, rows):
    for row in rows:
        decision = row["section"] == "Decisions already closed"
        if not decision and not (row["binding"] or RISK_LANGUAGE.search(row["text"]) or GATE.search(row["text"])):
            continue
        text = row["text"]
        fields = [cell.strip() for cell in text.strip("|").split("|")] if decision else []
        details = fields[3] if len(fields) == 5 else text
        area = re.search(r"Product area ([a-z0-9-]+) —", text)
        yield {"record": doc["record"], "record_id": records.work_state(doc["text"])[0].get("ID"),
               "section": row["section"], "text": text, "sources": row["sources"],
               "authority": fields[2] if len(fields) == 5 else "Source owner to verify",
               "question": fields[0] if fields else "", "decision_scope": fields[1] if fields else "",
               "assertion": details, "scope": scope_for(doc, area[1] if area else None)}


def terms(text):
    return set(re.findall(r"[^\W_]+", text.casefold())) - STOP


def conflicts(a, b):
    if (layout.stakeholder_record(a["record"]) != layout.stakeholder_record(b["record"])
            or not compatible(a["scope"], b["scope"])):
        return False
    # Source IDs are local to each record. Compare meaning-bearing words before the citation.
    first, second = (x["assertion"].split(" [S", 1)[0] for x in (a, b))
    if terms(first) == terms(second):
        return False
    if a["decision_scope"] and b["decision_scope"]:
        left, right = terms(a["decision_scope"]), terms(b["decision_scope"])
        if not (left <= right or right <= left):
            return False
        if a["question"].casefold() == b["question"].casefold():
            return True
    def stance(value):
        return bool(RISK_LANGUAGE.search(value)), bool(GATE.search(value))
    return (stance(a["assertion"]) != stance(b["assertion"])
            and len(terms(a["assertion"]) & terms(b["assertion"]) - {"source", "excerpt", "fact", "rule", "s1"}) >= 3)


def pair_candidates(claims, owner=None):
    if owner is None:
        pairs = combinations(claims, 2)
    else:
        local = [row for row in claims if row["record"] == owner]
        others = [row for row in claims if row["record"] != owner]
        pairs = chain(combinations(local, 2), product(local, others))
    for a, b in pairs:
        if conflicts(a, b):
            sides = sorted((a, b), key=lambda c: (c["record_id"] or c["record"], c["section"], c["text"]))
            key = identifier([(c["record_id"], c["section"], c["text"],
                               [(s["Source"], s["Source date"], s.get("coverage")) for s in c["sources"]]) for c in sides])
            owner_side = max(sides, key=lambda claim: sum(bool(v) for v in claim["scope"].values()))
            yield {"id": key, "owner": owner_side["record"], "scope": {k: a["scope"][k] or b["scope"][k] for k in a["scope"]},
                   "state": "open", "classification": "potential conflict", "reason": "Potentially conflicting guidance. Verify authority before committing.",
                   "claims": sides, "targets": []}


def observations(documents, through):
    import task_context
    result = []
    for doc in documents:
        areas = set(task_context.AREA.findall(doc["text"]))
        result.extend(claims(doc, task_context.linked_entries(doc, areas, through)))
    return result


def stored(documents, through=None, *, strict_owner=None):
    reviews = {}
    for doc in documents:
        try:
            local = latest(history(doc["text"]), through)
        except (ValueError, TypeError) as exc:
            if doc["record"] == strict_owner:
                raise ValueError(f"Restore the evidence review history in {strict_owner}: {exc}") from exc
            key = identifier("unreadable history", doc["record"])
            reason = f"Could not read evidence review history in {doc['record']}: {exc}"
            local = {key: {"id": key, "state": "open", "reason": reason, "scope": scope_for(doc),
                           "classification": "unreadable history", "targets": [], "history": [],
                           "on": through or date.today().isoformat(),
                           "claims": [{"record": doc["record"], "text": "Review history unavailable.",
                                       "authority": "Unverified"}]}}
        for key, review in local.items():
            reviews[key] = {**review, "owner": doc["record"]}
    return reviews


def check_risk(value, sources):
    if not isinstance(value, dict) or not {"reason"} <= value.keys() <= {"reason", "authority", "targets", "source"}:
        raise ValueError("An evidence risk needs a reason and optional authority, targets, or source")
    for key in ("reason", "authority"):
        if key in value and (not isinstance(value[key], str) or not records.specific(value[key])
                             or value[key].splitlines() != [value[key]]):
            raise ValueError(f"Provide one concrete risk {key}")
    targets = value.get("targets", [])
    if not isinstance(targets, list) or not all(isinstance(x, str) and re.fullmatch(r"[a-z0-9-]+/[a-z0-9-]+", x)
                                                for x in targets) or len(set(targets)) != len(targets):
        raise ValueError("Risk targets must be distinct qualified initiative IDs")
    if "source" in value and (type(value["source"]) is not int or not 1 <= value["source"] <= len(sources)):
        raise ValueError("Use a supplied source index for the risk")


def reported(doc, selected, sources, *, assess_plan=False):
    for entry in selected:
        risk = entry.get("risk", {})
        source_index = entry.get("source") or risk.get("source")
        source = {k: v for k, v in sources[source_index - 1].items()
                  if k in {"reference", "date", "checked_on", "coverage"}} if source_index else {}
        claim = entry.get("quote") or entry.get("question", "")
        restriction = bool(RISK_LANGUAGE.search(claim))
        partial = source.get("coverage") in {"partial", "unavailable"}
        if not risk and not restriction and not (partial or assess_plan):
            continue
        scope = scope_for(doc, entry.get("product_area"))
        detail = {"record": doc["record"], "record_id": records.work_state(doc["text"])[0].get("ID"),
                  "section": entry["section"], "text": claim,
                  "location": entry.get("location"), "source": source,
                  "authority": risk.get("authority") or entry.get("decision", {}).get("person") or "Source owner to verify"}
        reason = risk.get("reason")
        if not reason:
            if restriction:
                reason = "Check this restriction against current commitments."
            elif partial:
                reason = "Source coverage is incomplete. Its impact on this scope needs assessment."
            else:
                reason = "Compare this new evidence with the approved initiative assumptions."
        classification = "reported risk" if risk else "potential restriction" if restriction else "unassessed"
        key = identifier(records.work_state(doc["text"])[0].get("ID"), scope, claim, entry.get("location"),
                         source.get("reference"), source.get("date"), source.get("coverage"),
                         reason, detail["authority"], sorted(risk.get("targets", [])))
        yield {"id": key, "scope": scope, "claims": [detail], "reason": reason, "state": "open",
               "targets": risk.get("targets", []), "classification": classification}


def capture_events(private, documents, owner, selected, sources, responses, *, check_initiatives=True):
    today = date.today()
    current = stored(documents.values(), strict_owner=owner)
    doc = documents[owner]
    peers = (d for d in documents.values() if compatible(scope_for(doc), scope_for(d)))
    rows = observations(peers, today)
    candidates = list(pair_candidates(rows, owner))
    candidates.extend(reported(doc, selected, sources, assess_plan=check_initiatives and needs_plan_review(private, doc)))
    additions = []
    for row in candidates:
        if row["id"] not in current:
            event = {**row, "owner": owner, "on": today.isoformat()}
            current[row["id"]] = {**event, "owner": owner}
            additions.append(event)
    for response in responses:
        if response["record"] != owner:
            continue
        review = current.get(response["id"])
        if not review or review["owner"] != owner:
            raise ValueError("Choose a current risk ID and its owning context record")
        event = {k: v for k, v in response.items() if k != "record"}
        event["on"] = today.isoformat()
        previous = (review.get("history") or [review])[-1]
        if all(previous.get(k) == v for k, v in event.items() if k != "on"):
            continue
        additions.append(event)
        current[event["id"]] = {**review, "history": [event]}
    return additions


def validate_responses(responses):
    if not isinstance(responses, list):
        raise ValueError("Provide a list of PM review responses")
    for item in responses:
        if not isinstance(item, dict) or not {"id", "record", "state", "reason", "source"} <= item.keys() <= {
                "id", "record", "state", "reason", "source", "review_on"}:
            raise ValueError("A response needs its risk ID, owner record, state, PM reason, and source")
        if any(not isinstance(v, str) or not records.specific(v) or v.splitlines() != [v] for v in item.values()):
            raise ValueError("Use concrete single-line response fields")
        if item["state"] not in {"retain", "dismiss", "resolve", "follow-up"}:
            raise ValueError("Choose retain, dismiss, resolve, or follow-up")
        if (item["state"] == "follow-up") != ("review_on" in item):
            raise ValueError("Supply review_on for a follow-up")
        if "review_on" in item and date.fromisoformat(item["review_on"]) < date.today():
            raise ValueError("Choose a current or future follow-up date")


def needs_plan_review(private, doc):
    import initiative_store
    import layout
    product_name, initiative = doc["product"], doc["initiative"]
    if not product_name or not (private / layout.initiative_register(product_name)).exists():
        return False
    try:
        _, _, register = initiative_store.read(private.parent, product_name)
        for item in register.items.values():
            if initiative and item["id"].split("/", 1)[1] != initiative:
                continue
            if doc["area"] and item["areas"] and f"product/{product_name}/area/{doc['area']}" not in item["areas"]:
                continue
            if item["phase"] in {"candidate", "planned", "delivery"}:
                return True
        return False
    except (ValueError, OSError):
        return True  # Preserve the pending review when the signed basis cannot be checked.


def applies_to_task(review, scope, areas, documents):
    if applicable(review, scope, areas) and (not review.get("targets") or not scope.get("product")):
        return True
    if not scope.get("product"):
        return False
    import layout
    doc = documents.get(layout.product(scope["product"]))
    if not doc:
        return False
    product_id = records.work_state(doc["text"])[0].get("ID")
    for target in review.get("targets", []):
        prefix, _, slug = target.partition("/")
        if prefix == product_id and (not scope.get("initiative") or scope["initiative"] == slug):
            return True
    return False


def in_scope(doc, scope, areas, company):
    return ((scope.get("stakeholders") and layout.stakeholder_record(doc["record"])) or
            (company and doc["company"]) or
            (scope.get("product") and doc["product"] == scope["product"] and doc["area"] in {None, *areas}
             and doc["initiative"] in (None, scope.get("initiative"))))


def scoped_reviews(documents, selected, saved, scope, areas, through, *, recall_ids=(), recall_all=False):
    candidates = pair_candidates(observations(selected, through))
    reviews = {r["id"]: r for r in candidates if applicable(r, scope, areas)}
    for key, review in saved.items():
        recall_owner = (key in recall_ids or recall_all) and applicable(review, scope, areas)
        if recall_owner or applies_to_task(review, scope, areas, documents):
            reviews[key] = review
    return reviews


def review_sources(review):
    """Collect source pointers from a context risk or signed signal review."""
    result = [review.get("owner"), review.get("evidence", {}).get("source")]
    for claim in review["claims"]:
        result.append(claim.get("record"))
        source = claim.get("source")
        result.append(source.get("reference") if isinstance(source, dict) else source)
        sources = claim.get("sources")
        if isinstance(sources, list):
            result.extend(row.get("Source") for row in sources if isinstance(row, dict))
    if disposition := review.get("disposition"):
        result.append(disposition.get("source"))
    return list(dict.fromkeys(value for value in result if isinstance(value, str) and value))


def review_due(review, through):
    """Check unresolved evidence and dated dispositions without moving decisions."""
    if not review.get("active", True):
        return False
    if review["state"] in {"open", "needs-triage", "material", "uncertain", "revise"}:
        return not review.get("review_on") or review["review_on"] <= through.isoformat()
    return (review["state"] in {"follow-up", "retain", "retained"}
            and bool(review.get("review_on")) and review["review_on"] <= through.isoformat())


def launch_context(private, product_name, item):
    """Read scoped context once, including current claims behind a recorded advisory."""
    import task_context
    through = date.today()
    docs = task_context.context_documents(private, through=through)
    areas = {subject.rsplit("/", 1)[-1] for subject in item["areas"]}
    scope = {"product": product_name, "initiative": item["id"].split("/", 1)[1]}
    selected = [doc for doc in docs.values() if in_scope(doc, scope, areas, True)]
    reviews = scoped_reviews(docs, selected, stored(docs.values(), through.isoformat()), scope, areas, through)
    active = {}
    entries = {}
    for key, review in reviews.items():
        if review["state"] not in OPEN:
            continue
        evidence = []
        for claim in review["claims"]:
            name = claim.get("record") if isinstance(claim.get("record"), str) else None
            if name in docs and name not in entries:
                doc = docs[name]
                relevant_areas = set(task_context.AREA.findall(doc["text"]))
                entries[name] = list(task_context.linked_entries(doc, relevant_areas, through))
            rows = [r for r in entries.get(name, []) if r["section"] == claim.get("section")]
            matches = [r for r in rows if claim["text"] and claim["text"] in r["text"]]
            if not matches:
                sources = {source.get("Source") or source.get("reference") for source in claim.get("sources", [])
                           if isinstance(source, dict)}
                if isinstance(claim.get("source"), dict):
                    sources.add(claim["source"].get("reference"))
                matches = [r for r in rows if any(s["Source"] in sources for s in r["sources"])]
            evidence.append({"record": name, "section": claim.get("section"), "current_entries": matches})
        active[key] = {**review, "current_claim_evidence": evidence}
        if review["classification"] == "unreadable history":
            # This is a present diagnostic, with no known original opening date.
            active[key].pop("on", None)
    return active


def workspace_reviews(private):
    import task_context
    if private is None:
        return {}
    return stored(task_context.context_documents(private).values(), date.today().isoformat())


def for_initiative(private, product, item, *, reviews=None):
    """Only project positively associated context risks onto a registered initiative."""
    reviews = workspace_reviews(private) if reviews is None else reviews
    return [{**review, "active": True,
             "review_on": (review["on"] if review["state"] == "open" and review["classification"] != "unreadable history"
                           else review.get("review_on"))}
            for review in reviews.values()
            if review["state"] in OPEN and
            (item["id"] in review.get("targets", []) or
             (review["scope"].get("product") == product and
              (review["scope"].get("initiative") == item["id"].split("/", 1)[1] or
               (review["classification"] == "unreadable history" and not review["scope"].get("initiative")))))]


def preview(private, prepared, sources, *, destination_docs=None):
    """Review supplied claims before a destination or a write has been authorized."""
    import task_context
    docs = destination_docs
    if docs is None:
        docs = task_context.context_documents(private) if private.is_dir() else {}
    existing = observations(docs.values(), date.today())
    pending = []
    findings = []
    for row in prepared:
        target = row.get("destination")
        doc = docs.get(target, {"record": target, "product": row.get("product"), "area": row.get("product_area"),
                                "initiative": row.get("initiative"), "text": ""})
        for review in reported(doc, [row], sources, assess_plan=destination_docs is None and needs_plan_review(private, doc)):
            findings.append({"reason": review["reason"], "classification": review["classification"], "claims": review["claims"]})
        if not target or not row.get("source") or row.get("question"):
            continue
        source = sources[row["source"] - 1]
        decision = row.get("decision", {})
        claim = {"record": target, "section": row["section"], "scope": scope_for(doc, row.get("product_area")),
                 "question": decision.get("question", ""), "decision_scope": decision.get("scope", ""),
                 "assertion": row.get("rule") or row["quote"], "text": row["quote"],
                 "authority": decision.get("person") or row.get("risk", {}).get("authority") or "Source owner to verify",
                 "sources": [source], "location": row["location"]}
        if decision or row.get("rule") or RISK_LANGUAGE.search(claim["text"]):
            for prior in chain(existing, pending):
                if conflicts(prior, claim):
                    findings.append({"reason": "Potentially conflicting guidance. Verify authority before committing.",
                                     "classification": "potential conflict", "claims": [prior, claim]})
            pending.append(claim)
    return findings
