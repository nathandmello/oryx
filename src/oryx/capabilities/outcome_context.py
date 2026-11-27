"""Select scoped evidence for an outcome assessment. The PM establishes what success means."""

import json
import re

import layout


# Each supported request identifies its subject once for both routing and the activity check.
SUBJECT = r"(?:the |our )?(?P<subject>[^?.!\n]+?)"
WHAT_CHANGED = re.compile(
    r"^(?:did|has|have|help (?:me|us) (?:check|assess|understand) (?:if|whether))\s+" + SUBJECT
    + r"\s+(?:(?:(?:get|gotten|become) (?:better|worse)|succeed(?:ed)?|move(?:d)? the needle)"
      r"(?: (?:in|for|during|since|after|as of|over|last|this) [^?.!\n]+)?"
      r"|(?:improve(?:d)?|decline(?:d)?|reduce(?:d)?|increase(?:d)?|decrease(?:d)?)"
      r"(?: (?P<measure>[^?.!\n]+))?)[?.! ]*$", re.I)
HOW_PERFORMING = re.compile(r"^how (?:is|are|did|has|have) " + SUBJECT
                            + r" (?:perform(?:ing|ed)?|do(?:ing|ne)?|change(?:d)?)[?.! ]*$", re.I)
ACTIVITY = (r"(?:what (?:was|were|are) |(?:(?:can|could) (?:we|you) |help (?:me|us) )?"
            r"(?:assess|evaluate|review|compare) )(?:the )?")
TOPIC = r"(?:outcomes?|impact|performance|results?)"
NAMED_ACTIVITY = re.compile(r"^" + ACTIVITY + SUBJECT + r"(?:['’]s)? " + TOPIC + r"[?.! ]*$", re.I)
FOR_SUBJECT = re.compile(r"^" + ACTIVITY + TOPIC + r"(?:(?: for| of) " + SUBJECT + r")?[?.! ]*$", re.I)
CRITERION = re.compile(
    r"\b(?:success (?:means|looks like|measur\w*|metric|criteri\w*)|(?:agreed|approved|primary|target) (?:outcome|measure|metric)"
    r"|(?:outcome|goal|objective) (?:is|was)|(?:agreed to measure|measures? success|define success)|"
    r"(?:aim|intend|want) to (?:increase|reduce|improve)|(?:we|the team) (?:aims? for|tracks? success by))\b", re.I)


def assessment_request(prompt):
    prompt = re.sub(r"^please\s+", "", prompt.strip(), flags=re.I)
    for pattern in (WHAT_CHANGED, HOW_PERFORMING, NAMED_ACTIVITY, FOR_SUBJECT):
        match = pattern.fullmatch(prompt)
        if match and not re.search(r"\b(?:ask(?:ed)?|say|said|hear|heard|report(?:ed)?|mention(?:ed)?|tell|told|write|wrote)\b", match["subject"] or "", re.I):
            return match
    return None


def subject(prompt):
    match = assessment_request(prompt)
    return match["subject"] if match else None


def same_subject(row, doc, scope):
    if doc["product"] != scope["product"] or doc["initiative"] != scope.get("initiative"):
        return False
    # Older product briefs keep area claims inline, with the capture router's explicit area label.
    area = row.get("product_area") or doc["area"]
    return area == scope.get("area")


def definition(row):
    text = row["text"]
    first_line = text.splitlines()[0]
    directional_goal = row["section"] == "Area outcomes" and re.match(
        r"^- (?:Fact|Rule): (?:fewer|more|faster|shorter|reduce|increase|improve)\b", first_line, re.I)
    return bool(directional_goal or CRITERION.search(first_line)) and (
        text.startswith(("- Fact:", "- Rule:")) or row["section"] == "Decisions already closed")


def usable_candidate(row):
    return (bool(row.get("sources")) and not row.get("risk_reviews")
            and "\n  Open question at capture:" not in row["text"]
            and all(source["coverage"] != "unavailable" for source in row["sources"]))


def target_preview(item, product):
    """Return complete target records that fit; the approved initiative lookup always exposes the full set."""
    preview = []
    remaining = 1600
    for metric, target in item["targets"].items():
        row = {field: target[field] for field in ("baseline", "target", "due", "source")}
        row.update(metric=metric, initiative=item["id"], record=layout.initiative_register(product))
        size = len(json.dumps(row, ensure_ascii=False)) + 2
        if size > remaining:
            continue
        preview.append(row)
        remaining -= size
    return preview


def check(entries, targets, lookup, measure):
    return {
        "activity": "outcome-assessment",
        "status": "check_source_and_scope" if entries or targets or lookup or measure else "clarify_if_unknown",
        "evidence_entries": entries,
        "prerequisite": "The applicable outcome and measure the PM agreed for this scope.",
        "next_action": (
            "Check the PM's wording alongside the cited evidence and any qualifications or open reviews. "
            "Start with the measure named in the request or an already agreed outcome. "
            "Describe the desired direction only when the PM or the evidence establishes it. "
            "If several distinct outcomes still fit, ask one short question about which matters. "
            "For the chosen measure, retrieve its definition, cohort, period, baseline and observed result. "
            "Keep targets distinct from observations. Offer to find a missing comparison before drawing a conclusion."
            + (" Open initiative_lookup for all approved targets, definitions, corrected readings and guardrails." if lookup else "")
        ),
        "question_if_unclear": "How was that measure defined for this group?" if measure else "Which outcome would you like to check?",
        **({"initiative_lookup": lookup} if lookup else {}),
        **({"recorded_targets": targets} if targets else {}),
    }
