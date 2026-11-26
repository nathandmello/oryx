"""Read explicit session controls from the PM's own request before optional processing."""

import hashlib
import json
import re
from uuid import uuid4

import pm_profile
import storage


# A pasted document supplies evidence. Its speakers cannot change the PM's settings.
SOURCE_START = re.compile(
    r"(?:^|\n)[ \t]*(?:>|```|\[\d+\]\s+|(?:\[?\d{1,2}:\d{2}(?::\d{2})?\]?)\s+)|"
    r"\b(?:transcript|quoted (?:email|message)|email body|source text|meeting minutes)\s*:\s*", re.I)
QUOTE = re.compile(r'"[^"\n]*"|“[^”\n]*”|`[^`\n]*`')
DIRECT_REQUEST = r"^(?:(?:can|could|would|will) (?:we|you) (?:mind )?)?"
OFF = re.compile(DIRECT_REQUEST +
                 r"(?:(?:let['’]s|please|go|keep(?:ing)?|make|take|this is|we['’]re|this part is|i want (?:this|to go))\s+)*"
                 r"(?:(?:(?:this|that|the|our)(?:\s+(?:conversation|discussion|exchange|chat|part))?|conversation|it)\s+)?"
                 r"off[ -](?:the[ -])?record\b", re.I)
ON = re.compile(DIRECT_REQUEST +
                r"(?:(?:let['’]s|please|go|we['’]re|we are|this is)\s+)*"
                r"(?:back on (?:the )?record|resume (?:the )?(?:transcript )?logging)\b", re.I)
PROFILE_REFUSAL = re.compile(
    r"\b(?:do not|don't|never|please avoid)\s+(?:[^.?!\n]{0,55}\b(?:profil(?:e|es|ing)|stakeholder (?:record|context))\b)|"
    r"\b(?:keep|leave)\s+(?:this|that|it)\s+out of\s+(?:the |any |my )?(?:profile|stakeholder)|"
    r"\b(?:chat[ -]only|no profiling|no (?:stakeholder )?profile (?:updates?|changes?))\b", re.I)
MUTE_TIPS = re.compile(r"\b(?:stop|mute|silence|disable|turn off)\b[^.?!\n]{0,45}\b(?:context|cache|compaction)\b[^.?!\n]{0,26}\b(?:tips|suggestions|reminders|nudges|advice)\b", re.I)
MUTE_PROFILES = re.compile(r"\b(?:stop|mute|silence|disable|turn off)\b[^.?!\n]{0,45}\b(?:stakeholder|profiles?)\b[^.?!\n]{0,26}\b(?:tips|suggestions|reminders|nudges|offers)\b", re.I)
EXPLICIT_MUTE = re.compile(
    r"^(?:please\s+)?(?:stop|mute|silence|disable|turn off)\s+(?:all\s+)?(?:the\s+)?"
    r"(?P<target>stakeholder(?: profile)?|profile|context(?: window)?|compaction|cache)\s+"
    r"(?:tips|suggestions|nudges|reminders|advice)(?:\s+(?:for|from) (?:my |the )?"
    r"(?P<source>transcripts?|wiki|email|chat|onboarding))?[.! ]*$", re.I)


def exact_mute(prompt):
    match = EXPLICIT_MUTE.fullmatch(instruction(prompt))
    if not match:
        return None
    name = "profile-suggestions" if match["target"].lower().startswith(("stakeholder", "profile")) else "context-advice"
    source = (match["source"] or "").lower().removesuffix("s")
    return [name, "off", *(["--source", source] if source else [])]


PM_BREAK = re.compile(r"\b(?:take a break|stopping (?:here|for today)|pause (?:here|for lunch)|done for today|leave (?:this|it) (?:here|until tomorrow))\b", re.I)
SWITCH_TASK = re.compile(r"\b(?:unrelated (?:task|question|topic)|switch(?:ing)? to an unrelated|separate topic)\b", re.I)
MILESTONE = re.compile(r"\b(?:before (?:we|i) (?:move|start|draft)|(?:we(?:'re| are) |i'm )?(?:ready to|let's) (?:move on to|start drafting)|what(?:'s| is) next|next phase)\b", re.I)


def instruction(prompt):
    """Select the request before a recognizable quoted source or fenced attachment."""
    return SOURCE_START.split(prompt, maxsplit=1)[0].strip()


def controls(prompt):
    words = QUOTE.sub(' ', instruction(prompt)).replace('’', "'")
    # Commands can follow the PM's opening sentence, as in 'For context only. Off the record.'
    statements = [part.strip() for part in re.split(r'[.!?\n]+', words)]
    choices = [False if ON.match(s) else True for s in statements if ON.match(s) or OFF.match(s)]
    mute = 'context-advice' if MUTE_TIPS.search(words) else None
    if MUTE_PROFILES.search(words):
        mute = 'profile-suggestions'
    return (choices[-1] if choices else None, bool(PROFILE_REFUSAL.search(words)), mute)


def next_step(prompt):
    words = QUOTE.sub(' ', instruction(prompt))
    if PM_BREAK.search(words):
        return 'break'
    if SWITCH_TASK.search(words):
        return 'unrelated'
    if MILESTONE.search(words):
        return 'continue'
    return None


HANDOFF_EXIT = re.compile(
    r"\b(?:new|unrelated|separate|different) (?:task|question|topic|conversation|subject)\b|"
    r"\b(?:change|switch)(?: the)? (?:topic|subject|tasks?|gears)\b|"
    r"^(?:(?:please|now|let['’]s)\s+)*(?:exit|leave|stop|close|finish|pause|end|drop|park|set aside)"
    r"(?:\s+(?:this|that|the|current|our|active)){0,2}(?:\s+(?:task|handoff|work|review|topic|thread|here))?([.!?]|$)|"
    r"\b(?:done|finished) (?:with|for) (?:this|today)\b", re.I)


def leaves_handoff(prompt):
    words = QUOTE.sub(' ', instruction(prompt)).strip()
    return bool(HANDOFF_EXIT.search(words) or next_step(words) in ("unrelated", "break"))


def pending_path(private, client, session):
    if private is None or not client or not isinstance(session, str) or not session:
        return None
    name = hashlib.sha256((client + '\0' + session).encode()).hexdigest()
    return pm_profile.safe_path(private, ".state/pending-submissions/" + name)


def end_submission(private, client, session, *, expected=None):
    try:
        path = pending_path(private, client, session)
        if path and path.is_file():
            with storage.writer_lock(private):
                if expected is not None:
                    active = storage.json_input(path.read_bytes())
                    if not isinstance(active, dict) or active.get("event") != expected:
                        return
                path.unlink(missing_ok=True)
    except (OSError, ValueError, RuntimeError):
        pass  # A stale marker can defer an optional offer. It cannot interrupt the PM.


def turn_key(private, client, session, payload, prompt):
    native = next((value for field in ('turn_id', 'message_id', 'user_message_id', 'prompt_id')
                   if isinstance(value := payload.get(field), str) and value), None)
    key = hashlib.sha256(('oryx-pm-turn\0' + str(session or '') + '\0' + (native or prompt)).encode()).hexdigest()
    if native:
        end_submission(private, client, session)
        return key
    path = pending_path(private, client, session)
    if path is None:
        return key
    # Until another submission or a client boundary, identical callbacks are indistinguishable.
    with storage.writer_lock(private):
        raw = path.read_bytes() if path.is_file() else None
        previous = storage.json_input(raw) if raw is not None else {}
        if (isinstance(previous, dict) and previous.get("request") == key
                and isinstance(previous.get("event"), str) and re.fullmatch("[a-f0-9]{32}", previous["event"])):
            return previous["event"]
        event = uuid4().hex
        storage.replace_text(path, raw, json.dumps({"request": key, "event": event}), mode=0o600)
        return event
