"""Select approved stakeholder evidence for the people addressed in the current request."""

from datetime import date
from hashlib import sha256
import json
import re

import context_index
import context_search
import stakeholder_profiles
import turn_intent


# Only the PM's instruction can select a reader. Quoted or pasted source material
# may itself contain requests to contact people.
QUOTED = re.compile(r"```[\s\S]*?(?:```|$)|`[^`]*(?:`|$)|\"[^\"]*(?:\"|$)|“[^”]*(?:”|$)|‘[^’]*(?:’|$)|"
                    r"(?<!\w)'[^'\n]+'(?!\w)")
SOURCE_START = re.compile(r"\b(?:transcript|excerpt|source(?: text)?|pasted (?:notes|email)|forwarded (?:message|email)|"
                          r"(?:meeting )?notes|quoted (?:text|message))\s*:", re.I)
OPT_OUT = re.compile(r"\b(?:without|skip|ignore|avoid|exclude|(?:do not|don['’]t|never) (?:read|use|consult|look up)) "
                     r"[^.,;!?]{0,65}\bprofiles?\b|\b(?:no profiles?|profiles? (?:off|are off limits))\b", re.I)
MEETING_WORK = re.compile(r"\b(?:prep(?:are)?|preparing|agenda|talking points|discuss|cover|plan|bring up|ask|rehearse)\b", re.I)
WRITING_WORK = re.compile(r"\b(?:writ(?:e|ing)|draft(?:ing)?|compose|polish|word|send|present|review|tailor|pitch|"
                          r"sending|respond|prepare|prep|rehearse|briefing|give me|help me|rewrite)\b|"
                          r"^(?:please )?(?:email|message|brief)\b", re.I)
PAST = re.compile(r"\b(?:as of|at the time|historical(?:ly)?|back then)\b", re.I)
AUDIENCE = r"(?:(?:our|my|the|both)\s+)*"
PROFILE_TASK = re.compile(r"\b(?:create|start|set up|review|correct|revise|update|build|make|show)\s+"
                          r"(?:just |one |a |the |an? existing |private |stakeholder )*profiles?\s+(?:for|of|on)\s+", re.I)
REQUESTS = (
    ("capture", PROFILE_TASK.pattern),
    ("position", r"\bwhere (?:does|did)\s+"),
    ("authority", r"\b(?:what can|does|can)\s+"),
    ("rehearsal", r"\b(?:how|what)\s+(?:would|will|might|could)\s+"),
    ("rehearsal", r"\b(?:simulate|rehearse|role[ -]?play)\s+(?:(?:the|a|my) (?:discussion|conversation|meeting|pitch) "
                  r"(?:with|to) |(?:the )?reactions? (?:of|from) )?"),
    ("meeting", r"\b(?:meeting|meet|1[:–-]1|one[ -]on[ -]one|sync|check[ -]in|briefing|conversation|agenda|review)\s+"
                r"(?:(?:tomorrow|today|this afternoon|next week) )?(?:with|for)\s+"),
    ("communication", r"\b(?:email|e-mail|message|memo|one[ -]pager|note|update|brief|pitch|proposal|deck|readout|"
                      r"presentation|pre[ -]?read|reply|response|opening|talking points)\s+(?:to|for)\s+"),
    ("communication", r"\b(?:email|message|brief)\s+"),
)
REQUESTS = [(activity, re.compile(pattern + AUDIENCE, re.I)) for activity, pattern in REQUESTS]
# Only a continuation of the same deliverable reuses its audience. Other tasks must select their own.
CONTINUATION = re.compile(r"^(?:(?:now|please|then|and|actually)[, ]+)*(?:(?:can|could|would) (?:you|we) )?(?:"
                          r"(?:make|rewrite|revise|shorten|tighten|polish|rehearse|redraft|trim|simplify) (?:it|that|this|the (?:draft|"
                          r"opening|message|update|memo|pitch|first (?:line|paragraph)))\b|"
                          r"(?:make (?:it|that) |keep (?:it|that) )?(?:shorter|more concise|more direct)[.!? ]*$|"
                          r"(?:what|how) (?:might|would|could|will) (?:she|he|they) |"
                          r"what (?:would|should|could|do) I (?:actually )?(?:ask|tell|say to) (?:her|him|them)\b|"
                          r"(?:give me|draft|write) .{0,45}\b(?:opening|reply|response) (?:for|to) |"
                          r"what (?:about|if) (?:her|his|their|they|she|he)\b)", re.I)
AWAY = re.compile(r"\b(?:switch|new task|different (?:topic|reader|audience|task)|someone else|instead (?:write|draft)|"
                  r"(?:send|address|adapt|tailor|rewrite) (?:it|this|that) (?:to|for)\b)", re.I)

def instruction_text(prompt):
    request = turn_intent.instruction(prompt)
    request = re.split(r"\b(?:transcript|source|document|forwarded email|pasted message) "
                       r"(?:says|reads|instructs|requests|asks)\b|(?:^|\n)(?:From|To|Subject):", request, maxsplit=1, flags=re.I)[0]
    return SOURCE_START.split(QUOTED.sub(" ", request), maxsplit=1)[0].partition("\n")[0].strip()


def continuation(prompt):
    instruction = instruction_text(prompt)
    return bool(any(CONTINUATION.match(sentence.strip()) for sentence in re.split(r"[.!?]+", instruction))
                and not AWAY.search(instruction) and not OPT_OUT.search(prompt))


REACTION = re.compile(r"\s*(?:['’]s\s+)?(?:say|think|react|respond|feel|push back|ask|want|object|support|"
                      r"oppose|challenge|care|receive|take|view|approach|expect|question|need|concerns?|reactions?)\b", re.I)
NEXT_PERSON = re.compile(r"\s*(?:,\s*(?:and\s+)?|\band\s+|&\s*)" + AUDIENCE, re.I)
QUALIFIER = re.compile(r"\s+(?:about|at|before|after|in|on|for|regarding|with|and|to|a|an|the|tomorrow|today|"
                       r"next|this|that|please|so|using|based|who|re|when|while|as|by|from|now|only|stand|approve|decide|recommend|advise|sign)\b", re.I)
TOPICS = {
    "authority": (), "position": (),
    "capture": ("role", "communication", "goals", "concerns", "evidence", "relationships", "history"),
    "communication": ("communication", "goals", "evidence", "concerns"),
    "meeting": ("goals", "concerns", "evidence", "communication", "history", "relationships", "role"),
    "rehearsal": ("concerns", "evidence", "goals", "history", "communication", "role", "relationships"),
}


def identity_matches(text, by_label):
    """Look up the longest matching name, alias or role. Shorter prefixes cannot break a tie."""
    best, matched = 0, []
    # The longest permitted role is 240 characters. Include room for alternate whitespace.
    for word in re.finditer(r"[\w-]+|[^\w\s-]+", text[:480]):
        prefix = text[:word.end()]
        choices = by_label.get(stakeholder_profiles.normalized(prefix))
        if choices and (word.end() == len(text) or not re.match(r"[\w-]", text[word.end():])):
            best, matched = word.end(), choices
    end = text[best:]
    # "Maya Lee" must not resolve to Maya Chen merely because Lee has no file.
    if best and re.match(r"\s+[^\W\d_]", end) and not (QUALIFIER.match(end) or REACTION.match(end)):
        return 0, []
    # A PM may explicitly identify namesakes by team in the same sentence.
    team = re.match(r"\s+from\s+(?:the\s+)?(.+?)(?=,|[.!?;]|\s+(?:and|about|on|for|with)\b|$)", end, re.I)
    if best and team:
        match = re.compile(r"(?<!\w)" + re.escape(team[1].strip()) + r"(?!\w)", re.I)
        matched = [person for person in matched if match.search(person["role"])]
        best += team.end()
    return best, matched


AUTHORITY_VERB = re.compile(r"\b(?:approv(?:e|al)|decide|recommend|advise|sign off|have (?:approval|authority|the final say))\b", re.I)
POSITION_VERB = re.compile(r"\bstand on\b", re.I)


def requests_for(prompt):
    for activity, pattern in REQUESTS:
        if activity == "authority" and not AUTHORITY_VERB.search(prompt):
            continue
        if activity == "position" and not POSITION_VERB.search(prompt):
            continue
        for match in pattern.finditer(prompt):
            yield match.start(), activity, match


def audience(prompt, identities):
    requests = sorted(requests_for(prompt), key=lambda item: item[0])
    by_label = stakeholder_profiles.indexed_labels(identities, short_names=True)
    for _, activity, request in requests:
        if activity == "capture" and re.search(r"\b(?:said|says|wrote|requested|asked to)\b", prompt[:request.start()], re.I):
            continue
        if ((activity == "meeting" and not MEETING_WORK.search(prompt))
                or (activity == "communication" and not WRITING_WORK.search(prompt))
                or re.search(r"(?:\bdon['’]t|\bdo not|\bnever)\b[^.!?;]{0,55}$", prompt[:request.start()], re.I)):
            continue
        cursor, slots, separator = request.end(), [], None
        while cursor < len(prompt):
            length, matched = identity_matches(prompt[cursor:], by_label)
            if not matched:
                if slots and ("and" in separator.group().casefold() or "&" in separator.group() or prompt[cursor:cursor+1].isupper()):
                    slots.append([])  # Ask about the unknown panel member before reading anyone.
                break
            slots.append(matched)
            cursor += length
            separator = NEXT_PERSON.match(prompt, cursor)
            if not separator or not re.match(r"[\w]", prompt[separator.end():]):
                break
            cursor = separator.end()
        if not slots:
            if activity == "capture":
                return activity, []
            continue
        tail = prompt[cursor:].lstrip()
        if activity == "authority" and not AUTHORITY_VERB.match(tail):
            continue
        if activity == "position" and not POSITION_VERB.match(tail):
            continue
        if activity == "rehearsal" and request.group().lower().startswith(("what ", "how ")) and not REACTION.match(prompt[cursor:]):
            continue
        if activity == "meeting" and re.search(r"\b(?:rehearse|simulate|role[ -]?play)\b", prompt, re.I):
            activity = "rehearsal"
        return activity, slots
    return None, []


def pointer(person):
    return sha256(person["id"].encode()).hexdigest()


def resumed_audience(prior, instruction, identities):
    """Use a saved audience only for a draft edit or an explicit answer to a namesake question."""
    if not isinstance(prior, dict) or prior.get("activity") not in TOPICS:
        return None, []
    slots = prior.get("slots")
    if not isinstance(slots, list) or not 1 <= len(slots) <= 6:
        return None, []
    current = {pointer(person): person for person in identities}
    if not all(isinstance(slot, list) and slot and all(isinstance(key, str) and key in current for key in slot) for slot in slots):
        return None, []
    groups = [[current[key] for key in slot] for slot in slots]
    ambiguous = [i for i, slot in enumerate(groups) if len(slot) > 1]
    if ambiguous:
        fragment = re.sub(r"^(?:(?:I mean|I meant|the|our|my)\s+)+", "", instruction.strip(), flags=re.I)
        for i in ambiguous:
            length, chosen = identity_matches(fragment, stakeholder_profiles.indexed_labels(groups[i], short_names=True))
            if len(chosen) == 1 and re.fullmatch(r"[.!? ]*", fragment[length:]):
                groups[i] = chosen
                return prior["activity"], groups
        return None, []
    if not continuation(instruction):
        return None, []
    replacement = re.search(r"\b(?:for|to)\s+(?!(?:him|her|them|a (?:minute|moment))\b)", instruction, re.I)
    if replacement and prior["activity"] == "communication":
        # A newly addressed reader replaces the previous audience, including when the new identity is unknown.
        selected, slots = audience("Draft a memo " + instruction[replacement.start():], identities)
        return (selected, slots) if selected else (None, [])
    # A pronoun with several possible antecedents cannot select a person's private evidence.
    if len(groups) > 1 and re.search(r"\b(?:she|her|hers|he|him|his)\b", instruction, re.I):
        mentioned = []
        for group in groups:
            person = group[0]
            labels = [person["name"], person["name"].split()[0], *person.get("aliases", [])]
            if any(re.search(r"(?<!\w)" + re.escape(label) + r"(?!\w)", instruction, re.I) for label in labels):
                mentioned.append(person)
        return prior["activity"], [mentioned or [group[0] for group in groups]]
    return prior["activity"], groups


def relevant_evidence(profile, activity, subjects, prompt, scope, tokenize, identifiers, limit, budget):
    topics = TOPICS[activity]
    available = [entry for entry in profile["entries"] if entry["kind"] in {"reported", "observed"}
                 and not entry.get("earlier_role") and entry.get("review_by", "9999-12-31") >= date.today().isoformat()
                 and entry["subject"] in subjects and entry["topic"] in topics
                 and (entry["observed_on"] == "unknown" or entry["observed_on"] <= date.today().isoformat())]
    if not available:
        return []
    # The general search model ranks only the already-authorized person's eligible
    # passages. A memory-only index keeps people out of the shared retrieval cache.
    rows = [{"record": profile["path"], "section": entry["topic"], "text": entry["wording"]} for entry in available]
    labels = {(row["record"], row["section"]): row["section"] for row in rows}
    _, scores, _ = context_search.rank(prompt, scope, rows, labels, context_index.Index(), tokenize, identifiers)
    priority = sorted(range(len(available)), key=lambda i: (scores[i], -topics.index(available[i]["topic"]),
                                                            available[i]["observed_on"] or ""), reverse=True)
    fields = ("id", "topic", "kind", "wording", "subject", "scope", "source", "attribution", "observed_on")
    selected = []
    for i in priority:
        row = {key: available[i][key] for key in (*fields, "review_by") if key in available[i]}
        size = len(json.dumps(row, ensure_ascii=False))
        if size <= budget:
            selected.append(row)
            budget -= size
        if len(selected) >= limit:
            break
    return selected


def for_task(private, prompt, scope, through, tokenize, identifiers, *, prior=None, remember=None):
    instruction = instruction_text(prompt)
    if not instruction or OPT_OUT.search(prompt) or through != date.today() or PAST.search(instruction):
        return None
    direct = any(requests_for(instruction))
    if not direct and not (prior and (continuation(instruction) or prior.get("clarify"))):
        return None
    try:
        identities = stakeholder_profiles.lookup(private)
        activity, slots = audience(instruction, identities) if direct else (None, [])
        pronoun_request = re.search(r"\b(?:to|for|with|would|might|could|ask) (?:her|him|them|he|she|they)\b", instruction, re.I)
        if activity is None and prior and (not direct or pronoun_request):
            activity, slots = resumed_audience(prior, instruction, identities)
        if activity == "capture" and not slots:
            return {"status": "setup", "activity": activity,
                    "next_action": "Confirm the person's identity and one work observation. Preview the exact wording before saving."}
        if not slots:
            return None
        if len(slots) > 6 or any(not slot or len(slot) > 6 for slot in slots):
            return {"status": "clarify", "question": "Which people should we prepare for? Confirm the intended names or roles."}
        choices = [person for slot in slots if len(slot) > 1 for person in slot]
        if remember is not None:
            remember.update(activity=activity, slots=[[pointer(person) for person in slot] for slot in slots],
                            clarify=bool(choices))
        if choices:
            return {"status": "clarify", "choices": [{key: item[key] for key in ("id", "name", "role")} for item in choices],
                    "question": "Which person did you mean? Confirm their name or role before using a profile."}
        targets = {slot[0]["id"]: slot[0] for slot in slots}
        subjects = {"general"}
        if scope.get("product"):
            product = "product/" + scope["product"]
            subjects.add(product)
            for level in ("area", "initiative"):
                if scope.get(level):
                    subjects.add(f"{product}/{level}/{scope[level]}")
        people = []
        for item in targets.values():
            name_shared = sum(stakeholder_profiles.normalized(item["name"]) in
                              {stakeholder_profiles.normalized(name) for name in [other["name"], *other.get("aliases", [])]}
                              for other in identities) > 1
            person = {key: item[key] for key in ("id", "name", "role")}
            if name_shared:
                person["shared_name"] = True
            if activity in {"authority", "position"}:
                # Decision rights and initiative positions have their own authoritative records.
                people.append(person)
                continue
            profile = stakeholder_profiles.show(private, item["id"])
            if any(profile.get(field) != item.get(field) for field in ("id", "name", "role", "aliases", "revision")):
                if remember is not None:
                    remember.clear()
                return {"status": "unavailable", "message": "Verify the private identity directory with stakeholder-profile index."}
            limit = min(3, max(1, 6 // len(targets)))
            entries = relevant_evidence(profile, activity, subjects, instruction, scope, tokenize, identifiers,
                                        limit, 6500 // len(targets))
            people.append({**person, "record": profile["path"], "entries": entries})
        return {"status": "resolved", "activity": activity, "people": people}
    except (OSError, ValueError):
        if remember is not None:
            remember.clear()
        return {"status": "unavailable", "message": "Verify the accepted record and its private directory with stakeholder-profile index."}
