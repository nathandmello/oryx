"""Check observable decision inputs when the PM reviews a new brief revision."""

from html import unescape
import re

import records


QUESTIONS = {
    "Known, assumed, and unknown": "State the observation and the uncertainty to investigate.",
    "Learning goals and exit criteria": "State the decision and the evidence that would change it.",
    "Approach and timebox": "Name the research method or the work that will answer the question.",
    "Capacity and review": "Name the people or capacity assigned and how progress will be reviewed.",
    "Findings and recommendation": "State what was learned and which next decision it supports.",
    "Proposal": "Describe the proposed initiative.",
    "Value and alignment": "Explain how the initiative advances a customer or business objective.",
    "Approach and scope": "Describe the first increment or a material scope decision.",
    "Delivery and launch": "Describe how the change will reach its intended users.",
    "Assumptions and risks": "Identify a material uncertainty, risk, or supported reason it does not apply.",
    "Sources": "Name an identifiable evidence source or a specific evidence gap.",
}
ACKNOWLEDGEMENTS = {
    "noted", "acknowledged", "reviewed", "approved", "agreed", "confirmed", "discussed", "done",
    "covered", "complete", "completed", "ok", "okay", "yes", "no", "tbd", "todo",
    "pending", "unknown", "none", "n", "a", "and",
}
NON_ANSWERS = {
    "not applicable", "no comment", "as above", "see above", "same as above", "as discussed",
    "to follow", "follow up", "no known risks", "no risks", "no details",
}
STATUS = re.compile(
    r"(?:(?:reviewed|agreed|approved|noted|acknowledged|discussed|confirmed) (?:by|with) (?:the |our )?"
    r"(?:team|pm|owner|stakeholders?|leadership)|(?:to be|will be|yet to be) "
    r"(?:defined|determined|confirmed|discussed|reviewed|decided|completed|provided|added))"
)
# A duration alone describes when. The approved review_on is the authoritative checkpoint.
DURATION_ONLY = re.compile(
    r"(?:(?:for|over|within|in|during|the|next|this|expected|duration|timebox|is|tbd|planned|of) )*"
    r"(?:[a-z0-9]+ )?(?:business |working )?(?:days?|weeks?|months?|hours?|sprints?|quarters?)"
    r"(?: (?:of|for) (?:discovery|research))?"
)


def visible(text):
    """Only visible headings and body text can answer the review questions."""
    text = re.sub(r"<!--.*?(?:-->|\Z)", "", text, flags=re.S)
    lines = []
    fence = None
    for line in text.splitlines():
        match = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
        if match and fence is None:
            fence = match[1]
        elif fence is not None:
            if match and match[1][0] == fence[0] and len(match[1]) >= len(fence) and not match[2].strip():
                fence = None
        else:
            lines.append(line)
    return "\n".join(lines)


def words(text):
    return " ".join(re.findall(r"[^\W_]+", unescape(text).casefold()))


def answer_parts(body, prompt, heading):
    body = re.sub(r"</?[a-zA-Z][a-zA-Z0-9-]*(?:\s+[^<>]*?)?/?>", " ", body)
    if heading != "Sources":
        body = re.sub(r"\[S\d+\]\([^)\n]*\)", "", body, flags=re.I)
        body = re.sub(r"\[([^]\n]*)\]\([^)\n]+\)", r"\1", body)
    # A source label alone identifies a row. The row needs a citation or destination.
    body = re.sub(r"\[S\d+\]", "", body, flags=re.I)
    ignored = {words(heading), words(prompt), *NON_ANSWERS}
    if heading == "Sources":
        ignored.update({"see", "source", "sources", "reference", "references"})
    ignored.update(words(line) for line in re.split(r"[.!?]\s+", prompt))
    parts = []
    for line in body.splitlines():
        if line.lstrip().startswith("#"):
            continue
        line = re.sub(r"^\s*(?:(?:[-+*>]|\d+[.)])\s+|\[[ xX]\]\s*)+", "", line)
        for phrase in re.split(r"[.!?;]\s+", line):
            normalized = words(phrase)
            if (not any(char.isalpha() for char in normalized) or normalized in ignored
                    or set(normalized.split()) <= ACKNOWLEDGEMENTS or STATUS.fullmatch(normalized)):
                continue
            if heading == "Approach and timebox" and DURATION_ONLY.fullmatch(normalized):
                continue
            parts.append(normalized)
    return parts


def has_answer(value):
    """Recognize visible free text beyond placeholders and status acknowledgements."""
    return isinstance(value, str) and records.specific(value) and bool(answer_parts(visible(value), "", ""))


def check_review_content(text, kind, headings, *, root):
    template = (root / "templates" / f"{kind}.md").read_text(encoding="utf-8")
    document = visible(text)
    errors = []
    answers = {}
    for heading in headings:
        body = (records.section(document, heading) or "").strip()
        prompt = records.section(template, heading) or ""
        parts = answer_parts(body, prompt, heading)
        answer = " ".join(parts)
        if not parts:
            errors.append(f"{heading}: {QUESTIONS[heading]}")
        elif answer in answers:
            errors.append(f"{heading} repeats {answers[answer]}. {QUESTIONS[heading]}")
        answers[answer] = heading
    if errors:
        raise ValueError("Complete the brief for this review:\n" + "\n".join(errors))
