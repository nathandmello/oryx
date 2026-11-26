"""Reserve one optional prompt across clients. Keep reviewed references separate from delivery receipts."""

from hashlib import sha256
import json
import re
import sys
from time import time

import layout
import overrides
import pm_profile
import storage
import workspace


FILE = ".state/optional-offers.json"
TOKEN = re.compile(r"[0-9a-f]{64}")
COOLDOWN = 30 * 60
STATES = {"pending", "reserved", "presented", "declined", "deferred"}


def digest(value):
    return sha256(value.encode()).hexdigest()


def approved(private, workflow, source):
    if not overrides.suggestions_allowed(private, "optional-suggestions", source):
        return False
    if workflow in {"stakeholder-profile", "profile-onboarding"}:
        return overrides.profile_suggestions_allowed(private, source)
    if workflow == "context-advice":
        return overrides.context_advice_allowed(private, source)
    return True


def valid_token(token):
    return isinstance(token, str) and TOKEN.fullmatch(token) is not None


def valid_handle(workflow, handle):
    if workflow == "profile-onboarding":
        return (isinstance(handle, dict) and handle.keys() == {"revision", "optional"}
                and all(type(value) is int and value >= 0 for value in handle.values()))
    if workflow == "stakeholder-profile":
        import stakeholder_signals
        return stakeholder_signals.safe_handle(handle)
    return False


def recall(private, row):
    if row["workflow"] == "profile-onboarding":
        import onboarding_profile_step
        return onboarding_profile_step.invitation(private, row["grant_ref"], delivered=row["status"] != "pending")
    import stakeholder_signals
    return stakeholder_signals.recall(private, row["grant_ref"])


def current_handle(private, row):
    if row["workflow"] == "profile-onboarding" and "grant_ref" in row:
        return bool(recall(private, row))
    if row["workflow"] == "stakeholder-profile" and "grant_ref" in row:
        import stakeholder_signals
        return stakeholder_signals.allowed_handle(private, row["grant_ref"])
    return False


def read(private):
    path = pm_profile.safe_path(private, FILE)
    raw = path.read_bytes() if path.is_file() else None
    rows = storage.json_input(raw) if raw is not None else {}
    if not isinstance(rows, dict):
        raise ValueError("Invalid optional offer receipts")
    for token, row in rows.items():
        required = {"workflow", "source_kind", "status", "at", "priority"}
        if (not valid_token(token) or not isinstance(row, dict)
                or not required <= row.keys() <= required | {"pause", "grant_ref"}
                or not isinstance(row["status"], str) or row["status"] not in STATES or type(row["at"]) is not int
                or row["at"] < 0 or type(row["priority"]) is not int or not 0 <= row["priority"] <= 100
                or ("pause" in row and not valid_token(row["pause"]))
                or ("grant_ref" in row and not valid_handle(row["workflow"], row["grant_ref"]))):
            raise ValueError("Invalid optional offer receipt")
        layout.slug(row["workflow"])
        layout.slug(row["source_kind"])
    return raw, rows


def save(private, raw, rows):
    data = json.dumps(rows, sort_keys=True) + "\n"
    if (raw is not None or rows) and raw != data.encode():
        storage.replace_text(pm_profile.safe_path(private, FILE), raw, data, mode=0o600)


def select(private, candidates, *, moment, mode, pause=None):
    """Hold the Studio lock through revalidation and reservation, before handing an offer to any client."""
    if moment not in {"busy", "pause"} or mode not in {"thought-partner", "quiet", "expedite"}:
        raise ValueError("Supply the current work mode and moment")
    try:
        with storage.writer_lock(private):
            return reserve(private, candidates, moment, mode, digest(pause) if pause else None)
    except (ValueError, OSError, RuntimeError):
        # Optional work must never block the parent request or expose private errors.
        return {"status": "unavailable"}


def reserve(private, candidates, moment, mode, pause):
    raw, rows = read(private)
    now = int(time())
    import stakeholder_signals
    _, previous = stakeholder_signals.ledger(private)
    incoming = {}
    for candidate in candidates:
        if (not isinstance(candidate, dict) or not isinstance(candidate.get("workflow"), str)
                or not layout.SLUG.fullmatch(candidate["workflow"])
                or not isinstance(candidate.get("source_kind"), str)
                or not layout.SLUG.fullmatch(candidate["source_kind"])):
            continue
        token = candidate.get("token")
        workflow = candidate["workflow"]
        source = candidate["source_kind"]
        priority = candidate.get("priority", 50)
        if (not valid_token(token) or type(priority) is not int or not 0 <= priority <= 100
                or not isinstance(candidate.get("offer"), dict)):
            continue
        if not approved(private, workflow, source) or token in previous:
            continue
        if workflow == "context-advice" and "observation" in candidate:
            import context_advice
            if not context_advice.still_current(private, candidate):
                continue
        if token in rows and rows[token]["status"] != "pending":
            continue
        row = {"workflow": workflow, "source_kind": source, "priority": priority, "status": "pending", "at": now}
        if "grant_ref" in candidate:
            if not valid_handle(workflow, candidate["grant_ref"]):
                continue
            row["grant_ref"] = candidate["grant_ref"]
            if not current_handle(private, row):
                continue
            # Only an explicitly retainable handle can survive a busy moment.
            rows.setdefault(token, row)
        incoming[token] = (row, candidate["offer"])

    cooling = any(r["at"] + COOLDOWN > now for r in previous.values()) or any(
        row["status"] != "pending" and (row["at"] + COOLDOWN > now or pause and row.get("pause") == pause)
        for row in rows.values())
    if mode != "thought-partner" or moment != "pause" or cooling:
        save(private, raw, rows)
        return {"status": "deferred" if incoming or any(r["status"] == "pending" for r in rows.values()) else "none"}

    choices = {token: row for token, row in rows.items() if row["status"] == "pending"}
    choices.update({token: item[0] for token, item in incoming.items()})
    for token in sorted(choices, key=lambda t: (choices[t]["priority"], choices[t]["at"], t)):
        row = choices[token]
        if not approved(private, row["workflow"], row["source_kind"]):
            continue
        if "grant_ref" in row and not current_handle(private, row):
            rows.pop(token, None)
            continue
        if token in incoming:
            offer = incoming[token][1]
        else:
            offer = recall(private, row)
            if not offer or offer.get("token") != token:
                continue
        rows[token] = dict(row, status="reserved", at=now)
        if pause:
            rows[token]["pause"] = pause
        save(private, raw, rows)
        if row["workflow"] == "profile-onboarding" and "grant_ref" in row:
            import onboarding_profile_step
            onboarding_profile_step.mark_offered(private, row["grant_ref"])
        return {**offer, "status": offer.get("status", "offer"), "token": token, "workflow": row["workflow"]}
    save(private, raw, rows)
    return {"status": "none"}


def disposition(private, token, status):
    outcome = {"presented": "presented", "decline": "declined", "defer": "deferred"}.get(status)
    if not valid_token(token) or not outcome:
        raise ValueError("Supply a reserved offer token and its disposition")
    with storage.writer_lock(private):
        raw, rows = read(private)
        row = rows.get(token)
        if row is None:
            # Receipts from installations that predate the common selector remain valid.
            import stakeholder_signals
            _, legacy = stakeholder_signals.ledger(private)
            if token in legacy and status in {"presented", "decline"}:
                return stakeholder_signals.remember(private, token, status)
            raise ValueError("Choose an offer already reserved for delivery")
        if row["status"] == "pending":
            raise ValueError("Wait for a natural pause before presenting the offer")
        if row["status"] == "declined" or row["status"] == "deferred" and outcome != "declined":
            return {"status": row["status"]}
        row["status"] = outcome
        if outcome == "declined":
            row.pop("grant_ref", None)
        save(private, raw, rows)
        return {"status": outcome}


def discover(private, token=None, *, source=None):
    """An uncertain delivery can be discovered by request, never automatically repeated."""
    import stakeholder_signals
    if token is not None and not valid_token(token):
        raise ValueError("Use an offer token from the private list")
    if source is not None and (token is None or not isinstance(source, dict)):
        raise ValueError("Supply a selected offer and its freshly authorized source")
    with storage.writer_lock(private):
        _, rows = read(private)
        found = []
        for key, row in rows.items():
            if (token and token != key or row["status"] in {"declined", "presented"}
                    or not approved(private, row["workflow"], row["source_kind"])):
                continue
            if "grant_ref" in row and not current_handle(private, row):
                continue
            item = {"token": key, "workflow": row["workflow"], "delivery": row["status"]}
            if row["workflow"] == "profile-onboarding" and "grant_ref" in row:
                if token:
                    item["offer"] = recall(private, row)
            elif "grant_ref" in row:
                import source_evidence
                request = stakeholder_signals.source_request(private, row["grant_ref"])
                if source is not None or source_evidence.local_ref(request["reference"]):
                    offer = stakeholder_signals.recall(private, row["grant_ref"], source=source)
                    if not offer or offer.get("token") != key:
                        continue
                    if token:
                        item["offer"] = offer
                elif token:
                    item["source_request"] = request
            found.append(item)
        return {"offers": found}


def check_workspace(private):
    try:
        read(private)
        return []
    except (OSError, ValueError, RuntimeError):
        return [f"{FILE}: invalid private optional offer receipts"]


def add_commands(commands):
    group = commands.add_parser("offer", help="Review optional work held for a natural pause")
    group.set_defaults(hub_action=run)
    verbs = group.add_subparsers(dest="operation", required=True)
    verbs.add_parser("list", help="Find deferred or uncertain deliveries without repeating them")
    show = verbs.add_parser("show", help="Check a retained reference under its current grant")
    show.add_argument("token")
    show.add_argument("--reread", action="store_true", help="Supply a fresh authorized remote source as JSON on standard input")
    for action in ("presented", "defer", "decline"):
        verbs.add_parser(action).add_argument("token")


def run(root, args, prepare_write):
    private = workspace.repo(root, "workspace")
    if args.operation in {"list", "show"}:
        source = storage.json_input(sys.stdin.read()) if getattr(args, "reread", False) else None
        result = discover(private, getattr(args, "token", None), source=source)
    else:
        prepare_write(root)
        result = disposition(private, args.token, args.operation)
    print(json.dumps(result, ensure_ascii=False, indent=2))
