"""Evaluate a work observation and remember only opaque receipts for unsolicited offers."""

import json
import re
from time import time

import evidence_spans
import source_evidence
import overrides
import pm_profile
import storage

FILE = ".state/stakeholder-suggestions.json"
TOKEN = re.compile(r"[0-9a-f]{64}")
# A presentation across sources should not start a stream of interruptions.
COOLDOWN_SECONDS = 30 * 60
def ledger(private):
    path = pm_profile.safe_path(private, FILE)
    raw = path.read_bytes() if path.is_file() else None
    value = storage.json_input(raw) if raw is not None else {}
    if (not isinstance(value, dict) or any(
            not TOKEN.fullmatch(key) or not isinstance(row, dict) or row.keys() != {"at", "outcome"}
            or type(row["at"]) is not int or row["at"] < 0 or row["outcome"] not in ("presented", "declined")
            for key, row in value.items())):
        raise ValueError("Invalid optional stakeholder reminder cache")
    return raw, value


def check_workspace(private):
    try:
        ledger(private)
    except (OSError, ValueError, RuntimeError):
        return [f"{FILE}: invalid optional reminder cache"]
    return []


def remember(private, token, status):
    if not isinstance(token, str) or not TOKEN.fullmatch(token) or status not in ("presented", "decline"):
        raise ValueError("Use the opaque token from a reviewed stakeholder offer")
    with storage.writer_lock(private):
        original, receipts = ledger(private)
        prior = receipts.get(token)
        if status == "decline" and prior is None:
            raise ValueError("Decline only an offer already presented to the PM")
        if prior and (prior["outcome"] == "declined" or status == "presented"):
            return {"status": prior["outcome"]}
        outcome = "declined" if status == "decline" else status
        receipts[token] = {"at": int(time()), "outcome": outcome}
        path = pm_profile.safe_path(private, FILE)
        storage.replace_text(path, original, json.dumps(receipts, sort_keys=True) + "\n")
    return {"status": outcome}


PURPOSE = "stakeholder-profile"
# Require an explicit work preference or recurring work request. Context and conditions stay verbatim.
PREFERENCE = re.compile(r"\b(?:I (?:prefer|need|want|usually|always|only|would like|don['’]t|do not|never)|"
                        r"I['’]d (?:prefer|like)|(?:please|always) (?:bring|send|start|include|show|attach|give|lead|flag)|"
                        r"(?:could|can) (?:you|we) (?:bring|send|start|include|show))\b", re.I)
WORK = re.compile(r"\b(?:evidence|examples?|customers?|data|metrics?|numbers?|costs?|risks?|decisions?|"
                  r"reviews?|proposals?|options?|comparisons?|trends?|updates?|charts?|tables?|"
                  r"slides?|decks?|summar(?:y|ies)|briefs?|reports?|emails?|messages?|slack|"
                  r"one[- ]page\w*|in writing|written|escalations?|incidents?|rollouts?|meetings?|tickets?|"
                  r"denominators?|conversion|forecasts?|pilots?|approval|gates?|trade[- ]?offs?|alternatives?|"
                  r"estimates?|prototypes?|e[- ]?mails?|feedback|research|exceptions?|outcomes?|objectives?)\b", re.I)
INCIDENTAL = re.compile(r"\b(?:this (?:pilot|decision|launch) only|vote (?:yes|no)|approve (?:this|the) rollout)\b", re.I)
UNCERTAIN = re.compile(r"\b(?:maybe|perhaps|might|unsure|sometimes|if|unless|except|until|only|when|whenever|each|every)\b", re.I)


def valid_evidence(value):
    return (isinstance(value, dict) and value.keys() == {"grant", "start", "end", "span"}
            and all(isinstance(value[k], str) and TOKEN.fullmatch(value[k]) for k in ("grant", "span"))
            and type(value["start"]) is int and type(value["end"]) is int
            and 0 <= value["start"] < value["end"] <= 2**40 + source_evidence.LIMIT
            and value["end"] - value["start"] <= 2048)


def safe_handle(handle):
    return valid_evidence(handle)


def authorized_grant(private, handle, *, optional=True):
    if not valid_evidence(handle):
        raise ValueError("Use a checked source passage reference")
    _, doc = source_evidence.state(private)
    grant = doc["grants"].get(handle["grant"])
    if (not grant or grant["purposes"] != [PURPOSE] or grant["retention"] != "review"
            or source_evidence.revoked(doc, grant, private) or not source_evidence.retainable(grant["reference"])
            or optional and not overrides.profile_suggestions_allowed(private, grant["kind"])):
        raise ValueError("Source permission for this stakeholder review is unavailable")
    if not grant["offset"] <= handle["start"] < handle["end"] <= grant["offset"] + grant["length"]:
        raise ValueError("Passage outside the authorized range")
    return grant


def allowed_handle(private, handle):
    try:
        grant = authorized_grant(private, handle)
        if source_evidence.local_ref(grant["reference"]):
            stat = pm_profile.safe_path(private, source_evidence.local_name(grant["reference"])).stat()
            return source_evidence.fingerprint([stat.st_size, stat.st_mtime_ns]) == grant["local_version"]
        return True
    except (ValueError, OSError, RuntimeError):
        return False


def accepted_source_available(private, handle):
    """Use the positive filing grant for an accepted claim without enabling optional suggestions."""
    try:
        grant = authorized_grant(private, handle, optional=False)
        if source_evidence.local_ref(grant["reference"]):
            source_evidence.reread(private, grant, PURPOSE)
        return True
    except (ValueError, OSError, RuntimeError):
        return False


def source_request(private, handle):
    grant = authorized_grant(private, handle)
    return {"evidence": handle, **{k: grant[k] for k in ("reference", "source_id", "revision", "kind",
                                                        "coverage", "offset", "length", "purposes")}}


RECURRING = re.compile(r"\b(?:whenever|before each|every|usually|always|typically|for each|for all|"
                       r"each time|regularly|in general|prefers?|expects?|insists on|requires?)\b", re.I)
SECONDHAND = re.compile(r"\b(?:said|told|heard|claimed|believes?|thinks?)\b.*(?:\bI\b|[“\"])", re.I)


def usable(span):
    """Exclude unsafe or ambiguous attribution before either automatic or annotation-led review."""
    return (not INCIDENTAL.search(span.body) and not evidence_spans.INSTRUCTION.search(span.original)
            and not (span.form in ("speech", "email") and SECONDHAND.search(span.body))
            and len(span.body.split()) >= 5 and len(span.original) <= 900 and len(span.original.encode()) <= 2048
            and span.body.rstrip('”"').endswith((".", "?", "!")))


def qualify(span):
    if not usable(span) or not WORK.search(span.body):
        return False
    if span.form in ("account", "report"):
        return bool(RECURRING.search(span.body))
    return bool(PREFERENCE.search(span.body) or RECURRING.search(span.body))


def prompt_for_review(spans):
    return {"status": "review", "instruction": (
        "Inspect these attributed passages for an explicit work-related criterion, concern, goal or preference. "
        "Check scope, conditions and uncertainty. Submit only supported material with person, excerpt and locator in "
        "observations.stakeholder-profile, or an empty list. The agent reviews privately. Ask the PM only for a material gap."),
        "passages": [{"person": s.person, "excerpt": s.original, "locator": locator_for(s)} for s in spans[:12]]}



def phrasing(span):
    """The default quote and grammatical first-person paraphrases retain every qualifier."""
    if span.form in ("account", "report"):
        author = "The PM" if span.form == "account" else "The source"
        return [f"{author} reported, “{span.original.strip()}”"]
    verb = "wrote" if span.form == "email" else "said"
    quote = f'{span.person} {verb}, “{span.body}”'
    if span.at:
        quote = f'At {span.at}, {quote}'
    choices = [quote]
    for lead, verb in (("I prefer ", "prefers "), ("I need ", "needs "), ("I want ", "wants "),
                       ("I do not want ", "does not want "), ("I don’t want ", "does not want "),
                       ("I don't want ", "does not want ")):
        if span.body.startswith(lead):
            rest = span.body[len(lead):]
            if re.search(r"\b(?:I|me|my|mine|myself|we|us|our|ours|you|your|here|now|"
                         r"today|yesterday|tomorrow|this|these|next|last)\b", rest, re.I):
                break  # The speaker's remaining perspective needs the direct quotation.
            paraphrase = f"{span.person} {verb}{rest}"
            choices.append((f"At {span.at}, " if span.at else "") + paraphrase)
            break
    return choices


def locator_for(span):
    locator = f"bytes {span.start}-{span.end}" + (f" at {span.at}" if span.at else "")
    if span.attribution_at is not None:
        locator += f", sender at byte {span.attribution_at}"
    return locator


def topic_for(body):
    for topic, pattern in (
        ("history", r"\b(?:used to|no longer|previously|changed my mind|formerly)\b"),
        ("role", r"\b(?:my role|report to|responsible for|accountable for)\b"),
        ("goals", r"\b(?:my goal|our objective|success means|my target)\b"),
        ("concerns", r"\b(?:my concern|concerned about|worry about|worried about)\b"),
        ("evidence", r"\b(?:evidence|examples?|metrics?|numbers?|comparisons?|data|measures?|denominators?|charts?)\b"),
    ):
        if re.search(pattern, body, re.I):
            return topic
    return "communication"


def details(info, span, handle):
    # Single exchanges establish what was said on that occasion. Scope never comes from an annotation.
    topic = topic_for(span.body)
    kind = "observed" if info["kind"] in ("meeting", "transcript") and span.form == "speech" else "reported"
    locator = locator_for(span)
    scope = f"This exchange in {info['reference']}, {locator}"
    author = {"account": "PM account", "report": info["reference"]}.get(span.form, span.person)
    return {"person": span.person, "topic": topic, "kind": kind, "wording": phrasing(span)[0],
            "source": f"ingestion:{info['source_id']} ({info['reference']}, {locator})",
            "locator": locator, "excerpt": span.original, "scope": scope, "subject": info["subject"],
            "observed_on": span.observed_on, "attribution": author,
            "coverage": info["coverage"], "source_revision": info["revision"], "source_id": info["source_id"],
            "conditional_or_uncertain": bool(UNCERTAIN.search(span.body)), "evidence": handle}


def bound_handle(grant, span):
    return {"grant": grant, "start": span.start, "end": span.end, "span": source_evidence.digest(span.original.encode())}


def checked(private, handle, *, source=None, optional=True):
    grant = authorized_grant(private, handle, optional=optional)
    text = source_evidence.reread(private, grant, PURPOSE, source)
    if grant["kind"] == "chat" and source_evidence.PRIVATE_TURN.search(text):
        raise ValueError("This message excludes optional profile use")
    for span in evidence_spans.inspect(text, grant):
        if bound_handle(handle["grant"], span) == handle and usable(span):
            return grant, span, details(grant, span, handle)
    raise ValueError("The original source no longer supports this attributed passage")


def validate_change(private, change, *, source=None):
    """Recheck the original and every factual field before preview or filing."""
    if not valid_evidence(change.get("evidence")):
        raise ValueError("Supply the original review handle")
    _, span, expected = checked(private, change["evidence"], source=source, optional=False)
    import stakeholder_profiles
    matches = matching_people(private, span.person)
    current = stakeholder_profiles.read(private, change["id"])[1]
    if current and current["id"] not in {p["id"] for p in matches}:
        raise ValueError("The accepted identity does not identify the speaker in this source")
    identity_ok = change["name"] == span.person or any(p["id"] == change["id"] and p["name"] == change["name"] for p in matches)
    if not identity_ok or any(change[k] != expected[k] for k in
            ("topic", "source", "excerpt", "scope", "subject", "observed_on")):
        raise ValueError("The claim changes the speaker, source, topic or scope. Review the original passage")
    if change["kind"] == "hypothesis" and change["attribution"] == "PM":
        return
    if (change["kind"] != expected["kind"] or change["attribution"] != expected["attribution"]
            or change["wording"] not in phrasing(span)):
        raise ValueError("This factual wording is unsupported. Keep the original conditions or review an explicit PM interpretation")


def matched_annotation(row, item, span):
    if not isinstance(row, dict) or row.get("significance", "material") not in ("material", "conflict", "ambiguous"):
        return False
    # Keep legacy ranked observations as pointers only. Every supplied factual field must match the original.
    if row.get("person") != span.person or row.get("excerpt") not in (span.original, span.body):
        return False
    if row.keys() - {"person", "excerpt", "significance", "why", "profile_id", "wording", "locator", "topic",
                     "scope", "kind", "subject", "observed_on", "attribution"}:
        return False
    if "wording" in row and row["wording"] not in phrasing(span):
        return False
    if "locator" in row and row["locator"] not in (item["locator"], span.at or item["locator"]):
        return False
    return all(row[key] == item[key] for key in ("topic", "kind", "scope", "subject", "observed_on", "attribution") if key in row)


def matching_people(private, speaker):
    import stakeholder_profiles
    needle = stakeholder_profiles.normalized(speaker)
    return [p for p in stakeholder_profiles.lookup(private, speaker)
            if needle in [stakeholder_profiles.normalized(label) for label in [p["name"], *p.get("aliases", [])]]]


def canonical_fact(span):
    statement = span.body
    if span.form in ("account", "report") and statement.startswith(span.person + " prefers "):
        statement = "I prefer " + statement[len(span.person + " prefers "):]
    return " ".join(statement.casefold().split())


def candidate(private, info, span, offer, *, annotation=None):
    import stakeholder_profiles
    annotation = annotation or {}
    matches = matching_people(private, span.person)
    chosen = annotation.get("profile_id")
    if chosen:
        matches = [p for p in matches if p["id"] == chosen]
        if not matches:
            return None
    who = matches[0] if len(matches) == 1 else None
    if who:
        existing = stakeholder_profiles.show(private, who["id"], offer["topic"])
        if any(row.get("evidence") == offer["evidence"] or (row["excerpt"] == span.original and
                row["subject"] == offer["subject"] and row["attribution"] == offer["attribution"])
               for row in existing["entries"]):
            return None
    # Link a transcript, its article and a recap by the actual originating event, speaker and utterance.
    token = source_evidence.fingerprint([PURPOSE, info["event_id"], span.person.casefold(),
                                        canonical_fact(span), info["subject"]])
    clarify = len(matches) > 1 or annotation.get("significance") in ("ambiguous", "conflict")
    offer.update({"status": "clarify" if clarify else "offer", "action": "update" if who else "create",
                  "token": token, "reason": "Check this sourced detail before a similar conversation."})
    if who:
        offer["profile_id"] = who["id"]
        offer["person"] = who["name"]
    if len(matches) > 1:
        offer["matches"] = [{k: p[k] for k in ("id", "name", "role")} for p in matches]
    if "wording" in annotation:
        offer["wording"] = annotation["wording"]
    return {"workflow": PURPOSE, "token": token, "source_kind": info["kind"], "priority": 50,
            "grant_ref": offer["evidence"], "offer": offer}


def recall(private, handle, *, source=None):
    try:
        grant, span, offer = checked(private, handle, source=source)
        result = candidate(private, grant, span, offer)
        return result["offer"] if result else None
    except (OSError, ValueError, RuntimeError):
        return None


def evaluate(private, source, observations, *, moment, mode):
    if observations == [] or not overrides.profile_suggestions_allowed(private, source["kind"]):
        return {"status": "none" if observations == [] else "silenced"}
    info, spans = source["source"], source["spans"]
    accepted, rejected, candidates = [], 0, []
    eligible = [s for s in spans if usable(s)]
    if observations is None:
        accepted.extend((span, None) for span in eligible if qualify(span))
        accepted = accepted[:32]
        if not accepted and eligible:
            return prompt_for_review(eligible)
        if not eligible and WORK.search(source["text"]) and len(source["text"].split()) >= 8:
            return {"status": "review", "instruction": (
                "Inspect the original for a complete attributed statement about working with a person. "
                "If the speaker or scope is unclear, retain that uncertainty. Submit [] for no supported finding. "
                "A clarification from the PM is a separately attributed source.")}
    else:
        for observation in observations:
            found = [s for s in eligible if matched_annotation(observation, details(info, s, None), s)]
            if len(found) == 1:
                accepted.append((found[0], observation))
            else:
                rejected += 1
    if accepted:
        grant = source_evidence.remember(private, info, PURPOSE)
        if not grant:
            return {"status": "clarify", "reason": "Identify a stable, permitted original source for this review."}
        for span, annotation in accepted:
            offer = details(info, span, bound_handle(grant, span))
            item = candidate(private, info, span, offer, annotation=annotation)
            if item and all(previous["token"] != item["token"] for previous in candidates):
                candidates.append(item)
    result = {"status": "deferred" if candidates else "none", "candidates": candidates}
    if observations is None:
        accepted_spans = {span for span, _ in accepted}
        remaining = [s for s in eligible if s not in accepted_spans and WORK.search(s.body)]
        if remaining:
            result["additional_review"] = prompt_for_review(remaining)
    if rejected:
        result["unsupported_rows"] = rejected
    return result
