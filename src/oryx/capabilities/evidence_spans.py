"""Locate attributed passages in authorized plain text. Preserve the original byte ranges."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import re

NAME = r"[^\W\d_][\w’'\-]*(?: [^\W\d_][\w’'\-]*){0,3}"
TIME = r"(?:\d{1,2}:)?\d{1,2}:\d{2}(?:\.\d{1,3})?"
# Some transcript exports append a role to the speaker label. Recognize professional
# role words only. Free-form parentheses can instead attribute the words to someone else.
ROLE_TERM = (r"(?:design(?:er)?|product|research(?:er)?|eng(?:ineer(?:ing)?)?|operations?|ops|"
             r"sales|service|finance|legal|support|manager|lead|director|staff|senior|"
             r"chair|secretary|treasurer|facilitator|editor|observer|coordinator|owner|PM|VP|UX)")
# A team label can describe any business, including a small cooperative's service desk.
# Never treat a phrase that introduces another source or speaker as a team qualifier.
ROLE_HEAD = r"(?:desk|team|department|unit|office|crew|committee|division|lead|manager|coordinator)"
QUALIFIER = r"(?!(?i:quoting|via|per|for|on|from|speaking|representing|reading|relaying)\b)[a-z][a-z-]{0,31}"
TEAM_TAG = rf"(?:{QUALIFIER}[ \t]+){{1,3}}(?i:{ROLE_HEAD})"
ROLE = rf"(?:[ \t]+\((?:(?i:{ROLE_TERM}(?:[ -]{ROLE_TERM}){{0,3}})|{TEAM_TAG})\))?"
LABEL = re.compile(rf"^\s*(?:[-*>]\s+)?(?:\[?(?:(?P<day>\d{{4}}-\d{{2}}-\d{{2}})[ T])?(?P<at>{TIME})\]?\s+)?(?P<person>{NAME}){ROLE}"
                   rf"(?:\s+\[?(?P<after>{TIME})\]?)?\s*:\s*(?P<body>\S.*)$")
QUOTED = re.compile(rf'^\s*(?P<person>{NAME}) (?:said|wrote|asked|replied),?\s+["“](?P<body>.+?)["”][.]?\s*$')
REPORT = re.compile(rf"^\s*(?:[-*]\s+)?(?P<person>{NAME}) (?P<report>(?:"
                    r"asked|told|prefers?|usually asks|always asks|requested|requires?|wants?|needs?|"
                    r"explained|said|recommended|noted|prioriti[sz]es|looks for|values|insists on|"
                    r"would like|expects|generally reviews|raised|emphasized|emphasised|will|was|is|has|attended|joined)\b.*)$")
SENDER = re.compile(rf'^From:\s*["“]?(?P<person>{NAME})["”]?(?:\s*<[^<>\s]+>)?\s*$', re.I)
HEADER = re.compile(r"^[A-Za-z][A-Za-z0-9-]{0,48}:")
THREAD = re.compile(r"^(?:\s*>|\s*[-]+ ?(?:Original|Forwarded) Message|\s*On .+ wrote:|From:)", re.I)
INSTRUCTION = re.compile(r"\b(?:ignore (?:all |previous |prior |your )*(?:instructions?|rules?)|system prompt|"
                         r"secret key|api key|password|bearer token|private key|off[ -]the[ -]record|"
                         r"diagnos(?:is|ed)|medical|pregnan\w*|religio\w*|personal life)\b", re.I)


@dataclass(frozen=True)
class Span:
    start: int
    end: int
    person: str
    body: str
    original: str
    at: str
    form: str
    attribution_at: int | None = None
    observed_on: str = "unknown"


def person_name(actor):
    return (actor.casefold() not in {"i", "we", "pm", "user", "assistant", "system", "unknown", "speaker", "note", "notes",
                                     "from", "to", "cc", "bcc", "subject", "date", "reply-to", "message-id", "sender"}
            and all(word[0].isupper() for word in actor.split()))


def email_spans(lines, offset):
    sender, sender_at, position, index = None, None, offset, 0
    for raw in lines:
        line = raw.rstrip("\r\n")
        if not HEADER.match(line) and not (index and line.startswith((" ", "\t"))):
            break
        if line.casefold().startswith("from:"):
            match = SENDER.fullmatch(line)
            if sender or not match or not person_name(match["person"]):
                return ()
            sender, sender_at = match["person"], position
        position += len(raw.encode())
        index += 1
    if sender is None:
        return ()
    rows = []
    for i in range(index, len(lines)):
        raw = lines[i]
        start = position
        position += len(raw.encode())
        line = raw.rstrip("\r\n")
        if THREAD.match(line):
            break
        if not line.strip():
            continue
        if INSTRUCTION.search(line):
            continue
        # An unjoined paragraph may contain a material exception in the next line.
        if i + 1 < len(lines) and lines[i+1].strip() and not THREAD.match(lines[i+1]):
            continue
        if i > index and lines[i-1].strip():
            continue
        rows.append(Span(start, start + len(line.encode()), sender, line.strip(), line, "", "email", sender_at))
    return tuple(rows)


def attributed(text, kind, offset=0):
    """Extract actor, timecode and original statement once for all authorized consumers."""
    lines = text.splitlines(keepends=True)
    if kind in ("email", "mail"):
        return email_spans(lines, offset)
    position, rows, last = offset, [], None
    for raw in lines:
        start = position
        position += len(raw.encode())
        original = raw.rstrip("\r\n")
        match = LABEL.fullmatch(original)
        form = "speech"
        if not match:
            match = QUOTED.fullmatch(original)
            form = "quotation"
        if not match:
            match = REPORT.fullmatch(original)
            form = "account" if kind == "chat" else "report"
        if not match:
            if last is not None and original.strip():
                rows[last] = None
            last = None
            continue
        actor = match["person"]
        last = None
        if not person_name(actor) or INSTRUCTION.search(original):
            continue
        fields = match.groupdict()
        body = fields.get("body") or original.strip()
        day = fields.get("day") or "unknown"
        if day != "unknown":
            try:
                if date.fromisoformat(day) > date.today():
                    continue
            except ValueError:
                continue
        rows.append(Span(start, start + len(original.encode()), actor, body, original,
                         fields.get("at") or fields.get("after") or "", form, observed_on=day))
        last = len(rows) - 1
    return tuple(item for item in rows if item is not None)


def inspect(text, info):
    spans = attributed(text, info["kind"], info["offset"])
    if info["coverage"] != "partial":
        return spans
    raw = text.encode()
    result = []
    for span in spans:
        left = span.start - info["offset"]
        right = span.end - info["offset"]
        if not left and info["offset"] != 0:
            continue  # The granted range may start inside a speaker label.
        remainder = raw[right:].decode()
        if not remainder.lstrip("\r\n") and not info["ends_at_eof"] and span.form != "quotation":
            continue  # The grant stops before the next exchange. A qualification may follow.
        if remainder and not remainder.startswith(("\r", "\n")):
            continue
        result.append(span)
    return tuple(result)
