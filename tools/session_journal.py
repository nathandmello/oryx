"""Keep consent, normalized visible exchanges and interruption gaps in local owner-only storage."""

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import subprocess
import time
from uuid import uuid4

import journal_native


_admission = ContextVar("oryx_journal_current_submission", default=None)
CLIENTS = ("claude", "codex")
DEFAULT_DAYS = 90
MAX_TEXT = 256 * 1024
IDENTIFIER = re.compile(r"[A-Za-z0-9_.:-]{1,128}")
STORE_ID = re.compile(r"[0-9a-f]{64}")
EVENT_ID = re.compile(r"jrn-[0-9a-f]{32}")
WORK_SCOPE = re.compile(r"[a-z0-9]+(?:[-/][a-z0-9]+)*")
CREDENTIAL = re.compile(
    r"-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----|\b(?:gh[pousr]_[a-zA-Z0-9]{20,}|"
    r"sk-[A-Za-z0-9_-]{20,}|AKIA[A-Z0-9]{16})\b|"
    r"(?i:\b(?:password|api[_ -]?key|access[_ -]?token|client[_ -]?secret)\s*[:=]\s*\S+|"
    r"\bAuthorization:\s*(?:Bearer|Basic)\s+\S+)"
)
SCHEMA = (
    "CREATE TABLE IF NOT EXISTS policy (singleton INTEGER PRIMARY KEY CHECK(singleton=1),"
    " enabled INTEGER NOT NULL, days INTEGER NOT NULL, generation INTEGER NOT NULL)",
    "INSERT OR IGNORE INTO policy VALUES (1, 0, 90, 0)",
    "CREATE TABLE IF NOT EXISTS pauses (client TEXT, session TEXT, paused INTEGER, generation INTEGER, PRIMARY KEY(client, session))",
    "CREATE TABLE IF NOT EXISTS turns (seq INTEGER PRIMARY KEY, client TEXT, session TEXT, native TEXT,"
    " submitted REAL, epoch TEXT, scope TEXT, user_event TEXT UNIQUE, prompt TEXT, reply_event TEXT UNIQUE,"
    " reply TEXT, finished REAL, cursor TEXT, replay_key TEXT UNIQUE, state TEXT, reason TEXT)",
    "CREATE UNIQUE INDEX IF NOT EXISTS native_turn ON turns(client,session,native) WHERE native IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS session_turn ON turns(client,session,seq)",
)
MISSING = "No verified completed reply"
INTERRUPTED = "The next submission arrived before a verified reply"
RESTRICTED = "Visible text excluded from the journal"


def _identifier(value):
    return isinstance(value, str) and IDENTIFIER.fullmatch(value) is not None


def _session(client, session):
    if client not in CLIENTS or not _identifier(session):
        raise ValueError("Choose a supported client and a valid native session ID")


def _scope(value):
    if isinstance(value, str) and len(value) <= 100 and WORK_SCOPE.fullmatch(value):
        return value
    return None


def _secure(path, *, directory):
    info = path.lstat()
    test = stat.S_ISDIR if directory else stat.S_ISREG
    if (not test(info.st_mode) or path.resolve() != path or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) & 0o077 or (not directory and info.st_nlink != 1)):
        raise ValueError("Use private journal storage owned and accessible only by the current user")


def _journal_home(*, exclude=None, provision=False):
    state = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state")
    base = state / "oryx" / "journals"
    if (not state.is_absolute() or base.resolve() != base or (exclude is not None and base.is_relative_to(exclude))
            or any((p / ".git").is_file() or (p / ".git" / "HEAD").is_file() for p in (base, *base.parents))):
        raise ValueError("Place local continuity storage outside Git repositories and installation backups")
    if provision:
        state.mkdir(mode=0o700, parents=True, exist_ok=True)
    for parent in (base.parent, base):
        if provision:
            parent.mkdir(mode=0o700, exist_ok=True)
        if os.path.lexists(parent):
            _secure(parent, directory=True)
    return base


def protected_home(private):
    """Return the checked namespace to mask when this checkout cannot open its own journal."""
    return _journal_home(exclude=private.parent, provision=True)


def _birth_time(path, info):
    stamp = getattr(info, "st_birthtime_ns", None)
    if stamp is not None:
        return str(stamp)
    if hasattr(info, "st_birthtime"):
        return str(info.st_birthtime)
    # Python's Linux stat_result omits statx creation time. GNU stat exposes its full precision.
    try:
        stamp = subprocess.check_output(["stat", "-c", "%w", "--", str(path)], timeout=2,
                                        stderr=subprocess.DEVNULL,
                                        env={"PATH": os.defpath, "LC_ALL": "C", "TZ": "UTC0"}).decode("ascii").strip()
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        raise ValueError("Cannot verify the Studio directory creation time") from exc
    if stamp == "-":
        return None
    if not re.fullmatch(r"[0-9-]+ [0-9:.]+ \+0000", stamp):
        raise ValueError("Unrecognized Studio directory creation time")
    return stamp


def _location(private, *, provision=False, require_recording=False):
    private = Path(private)
    if private.resolve() != private or not private.is_dir():
        raise ValueError("Use an installed Studio for local continuity")
    # A new checkout at a familiar pathname does not inherit its predecessor's consent.
    identity = private.stat()
    birth = _birth_time(private, identity)
    if require_recording and birth is None:
        raise ValueError("Recording needs a filesystem that reports the Studio directory creation time")
    # A privacy-only store can remember explicit pauses on other filesystems. It cannot grant recording consent.
    instance = f":{identity.st_dev}:{identity.st_ino}:{birth or 'privacy-only'}"
    key = hashlib.sha256(os.fsencode(private) + instance.encode()).hexdigest()
    folder = _journal_home(exclude=private.parent, provision=provision) / key
    if provision:
        folder.mkdir(mode=0o700, exist_ok=True)
    if os.path.lexists(folder):
        _secure(folder, directory=True)
        if (folder / ".git").is_file() or (folder / ".git/HEAD").is_file():
            raise ValueError("Place local continuity storage outside Git repositories")
    return folder, birth is not None


def location(private, *, provision=False):
    return _location(private, provision=provision)[0]


@contextmanager
def _folder_lock(folder, *, exclusive=False):
    # Keep the owner directory as a stable lock inode, including after a store is erased.
    import fcntl
    fd = os.open(folder, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH | fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)


@contextmanager
def _store(private, *, create=False, require_recording=False):
    folder, _ = _location(private, provision=create, require_recording=require_recording)
    if not folder.is_dir():
        yield None
        return
    with _folder_lock(folder), _database(folder, create=create) as db:
        yield db


@contextmanager
def _database(folder, *, create=False):
    file = folder / "journal.sqlite3"
    if not os.path.lexists(file):
        if not create:
            yield None
            return
        try:
            os.close(os.open(file, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600))
        except FileExistsError:
            pass
    _secure(file, directory=False)
    for suffix in ("-journal", "-wal", "-shm"):
        extra = file.with_name(file.name + suffix)
        if os.path.lexists(extra):
            _secure(extra, directory=False)
    db = None
    try:
        db = sqlite3.connect(file, timeout=2, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA secure_delete=ON")
        db.execute("PRAGMA temp_store=MEMORY")
        db.execute("BEGIN IMMEDIATE")
        for statement in SCHEMA:
            db.execute(statement)
        cutoff = time.time() - _policy(db)["days"] * 86400
        db.execute("DELETE FROM turns WHERE submitted<=?", (cutoff,))
        yield db
        db.commit()
    except sqlite3.Error as exc:
        raise ValueError("The private journal is unavailable") from exc
    finally:
        if db is not None:
            db.close()


def _policy(db):
    return db.execute("SELECT enabled,days,generation FROM policy").fetchone()


def _paused(db, client, session):
    return bool(db and db.execute("SELECT 1 FROM pauses WHERE client=? AND session=? AND paused=1", (client, session)).fetchone())


def off_record(private, client, session_id):
    if client not in CLIENTS or not _identifier(session_id):
        return False
    try:
        with _store(private) as db:
            return _paused(db, client, session_id)
    except (OSError, ValueError, sqlite3.Error):
        return True  # A failed privacy check must not release text to another workflow.


def _seal(db, reason, where="", params=()):
    db.execute("UPDATE turns SET state='gap', reason=?, cursor=NULL WHERE state='pending'" + where,
               (reason, *params))


def set_off_record(private, client, session_id, pause):
    _session(client, session_id)
    if type(pause) is not bool:
        raise ValueError("Choose whether to pause this session")
    with _store(private, create=pause) as db:
        if db:
            if pause:
                db.execute("INSERT INTO pauses VALUES (?,?,1,1) ON CONFLICT(client,session) DO UPDATE SET"
                           " paused=1,generation=generation+1 WHERE paused=0", (client, session_id))
                _seal(db, "Recording paused before completion", " AND client=? AND session=?", (client, session_id))
            else:
                db.execute("UPDATE pauses SET paused=0 WHERE client=? AND session=?", (client, session_id))
    return {"client": client, "session_id": session_id, "off_record": pause}


def configure(private, *, enabled=None, days=None):
    if days is not None and (type(days) is not int or not 1 <= days <= 36500):
        raise ValueError("Set retention between 1 and 36500 days")
    if enabled is not None and type(enabled) is not bool:
        raise ValueError("Choose whether to enable the journal")
    with _store(private, create=enabled is True or days is not None, require_recording=enabled is True) as db:
        if db:
            if enabled is False and _policy(db)["enabled"]:
                db.execute("UPDATE policy SET generation=generation+1")
                _seal(db, "Recording disabled before completion")
            if enabled is not None:
                db.execute("UPDATE policy SET enabled=?", (int(enabled),))
            if days is not None:
                db.execute("UPDATE policy SET days=?", (days,))
                db.execute("DELETE FROM turns WHERE submitted<=?", (time.time() - days * 86400,))
        return _status(db)


def _status(db):
    policy = _policy(db) if db else {"enabled": False, "days": DEFAULT_DAYS}
    return {"enabled": bool(policy["enabled"]), "retention_days": policy["days"],
            "purpose": "Local session continuity"}


def status(private):
    with _store(private) as db:
        result = _status(db)
        folder, available = _location(private)
        if db:
            result["store_id"] = folder.name
        if not available:
            result.update(enabled=False, available=False,
                          reason="The Studio filesystem does not report directory creation time")
        return result


def _text(value):
    if (not isinstance(value, str) or not value.strip() or len(value.encode("utf-8")) > MAX_TEXT
            or "\0" in value or CREDENTIAL.search(value)):
        return None
    return value


def _event_id():
    return "jrn-" + uuid4().hex


def _finish(db, row, reply, now):
    text = _text(reply)
    if text is None:
        db.execute("UPDATE turns SET state='gap', reason=?, cursor=NULL WHERE seq=?", (RESTRICTED, row["seq"]))
    else:
        db.execute("UPDATE turns SET state='complete', reply_event=?, reply=?, finished=?, cursor=NULL, reason=NULL"
                   " WHERE seq=?", (_event_id(), text, now, row["seq"]))


def _recover(db, private, row, now):
    if row["cursor"]:
        completed = journal_native.recover(private, row["client"], row["session"], json.loads(row["cursor"]),
                                           row["prompt"], row["native"], row["submitted"])
        if completed:
            reply, delivered = completed
            if isinstance(reply, str) and reply.strip() and delivered <= now + 1:
                _finish(db, row, reply, delivered)
                return True
    return False


def _pending(db, client, session):
    return db.execute("SELECT * FROM turns WHERE client=? AND session=? AND state='pending' ORDER BY seq DESC LIMIT 1",
                      (client, session)).fetchone()


def _admit(db, private, client, session, payload, scope, now):
    native = payload.get("turn_id")
    if native is not None and not _identifier(native):
        return
    if native and db.execute("SELECT 1 FROM turns WHERE client=? AND session=? AND native=?",
                             (client, session, native)).fetchone():
        return
    prompt = _text(payload.get("prompt"))
    prior = _pending(db, client, session)
    cursor = journal_native.checkpoint(private, client, session, payload, now) if prompt else None
    message_id = payload.get("user_message_id", payload.get("message_id"))
    identity = (client, session, "message", message_id) if _identifier(message_id) else None
    if identity is None and cursor and prompt:
        identity = (client, session, "cursor", cursor, hashlib.sha256(prompt.encode()).hexdigest())
    replay_key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest() if identity else None
    if replay_key and db.execute("SELECT 1 FROM turns WHERE replay_key=?", (replay_key,)).fetchone():
        return
    ambiguous = False
    if prior:
        if not native and not replay_key and prompt and prompt == prior["prompt"]:
            # Without a native event ID or file, an identical outstanding submission is ambiguous.
            return
        if not _recover(db, private, prior, now):
            _seal(db, INTERRUPTED, " AND seq=?", (prior["seq"],))
            ambiguous = not native
    generation = _policy(db)["generation"]
    pause = db.execute("SELECT generation FROM pauses WHERE client=? AND session=?", (client, session)).fetchone()
    epoch = f"{generation}/{pause['generation'] if pause else 0}"
    event = _event_id()
    db.execute("INSERT INTO turns(client,session,native,submitted,epoch,scope,user_event,prompt,cursor,replay_key,state,reason)"
               " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (client, session, native, now, epoch, _scope(scope), event, prompt,
                                                json.dumps(cursor) if cursor else None, replay_key, "pending" if prompt else "gap",
                                                (INTERRUPTED if ambiguous else MISSING) if prompt else RESTRICTED))
    return event


def _visible(payload):
    source = payload.get("source")
    if isinstance(source, dict) or payload.get("origin") not in (None, "human", "user", "assistant", "client"):
        return False
    if payload.get("hook_event_name") == "UserPromptSubmit" and payload.get("role") not in (None, "human", "user"):
        return False
    if payload.get("hook_event_name") == "Stop" and payload.get("role") not in (None, "assistant"):
        return False
    return not (payload.get("agent_id") or payload.get("agent_type") or payload.get("isSidechain")
                or payload.get("is_sidechain") or payload.get("isMeta") or payload.get("parent_session_id")
                or payload.get("source") in ("subagent", "tool") or payload.get("origin") in ("subagent", "tool")
                or payload.get("role") in ("tool", "developer", "system"))


def capture(private, client, payload, *, scope=None):
    """Trusted client hooks only. Collection has no conversational output or authority to file evidence."""
    try:
        event = payload.get("hook_event_name")
        session = payload.get("session_id")
        _admission.set(None)
        if event not in ("SessionStart", "UserPromptSubmit", "Stop") or not _visible(payload):
            return
        _session(client, session)
        with _store(private, require_recording=True) as db:
            if not db or not _policy(db)["enabled"] or _paused(db, client, session):
                return
            now = time.time()
            if event == "UserPromptSubmit":
                key = _admit(db, private, client, session, payload, scope, now)
                if key:
                    _admission.set((private, client, session, key))
                return
            row = _pending(db, client, session)
            if not row:
                return
            if event == "SessionStart":
                _recover(db, private, row, now)
                return
            native = payload.get("turn_id")
            if native is not None and (not _identifier(native) or native != row["native"]):
                return
            reply = payload.get("last_assistant_message")
            if isinstance(reply, str) and reply.strip() and (native or not row["native"] and row["reason"] != INTERRUPTED and row["epoch"] == "0/0"):
                _finish(db, row, reply, now)
            else:
                _recover(db, private, row, now)
    except (OSError, ValueError, RuntimeError, sqlite3.Error, OverflowError):
        return  # Only explicit journal commands report storage errors; capture never interrupts the primary task.


def _time(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat()


def _events(row):
    base = {"client": row["client"], "session_id": row["session"], "turn_id": row["native"],
            "scope": row["scope"], "purpose": "handoff"}
    yield dict(base, id=row["user_event"], time=_time(row["submitted"]), role="human",
               text=row["prompt"], status="visible" if row["prompt"] else "gap")
    if row["state"] == "complete":
        yield dict(base, id=row["reply_event"], time=_time(row["finished"]), role="assistant",
                   text=row["reply"], status="visible")
    else:
        yield dict(base, id=None, time=None, role="assistant", text=None, status="gap", reason=row["reason"])


def _allowed(db, client, session):
    return db and _policy(db)["enabled"] and not _paused(db, client, session)


def read_session(private, client, session_id, *, limit=20):
    _session(client, session_id)
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("Choose a limit between 1 and 100 turns")
    with _store(private) as db:
        result = {"client": client, "session_id": session_id, "events": []}
        if not _allowed(db, client, session_id):
            return result
        row = _pending(db, client, session_id)
        if row:
            _recover(db, private, row, time.time())
        rows = db.execute("SELECT * FROM turns WHERE client=? AND session=? ORDER BY seq DESC LIMIT ?",
                          (client, session_id, limit)).fetchall()
        result["events"] = [event for row in reversed(rows) for event in _events(row)]
        return result


def _reference(db, event_id, scope):
    if not db or not isinstance(event_id, str) or not EVENT_ID.fullmatch(event_id):
        return None
    row = db.execute("SELECT * FROM turns WHERE user_event=? OR reply_event=?", (event_id, event_id)).fetchone()
    if (not row or not _allowed(db, row["client"], row["session"])
            or (scope is not None and (not _scope(scope) or scope != row["scope"]))):
        return None
    return row


def resolve_reference(private, event_id, *, purpose="handoff", scope=None):
    if purpose != "handoff":
        return None
    with _store(private) as db:
        row = _reference(db, event_id, scope)
        if row:
            for event in _events(row):
                if event["id"] == event_id and event["status"] == "visible":
                    return {key: value for key, value in event.items() if key != "text"}
    return None


def bind_turn_scope(private, client, payload, scope, *, previous=None):
    """Bind only the live, admitted submission after its existing work checkpoint resolves."""
    session = payload.get("session_id")
    if (client not in CLIENTS or not _identifier(session) or not _scope(scope)
            or payload.get("hook_event_name") != "UserPromptSubmit" or not _visible(payload)):
        return None
    with _store(private) as db:
        if not _allowed(db, client, session):
            return None
        row = _pending(db, client, session)
        if (not row or _admission.get() != (private, client, session, row["user_event"])
                or row["scope"] not in (None, scope) or row["native"] != payload.get("turn_id")
                or row["prompt"] != _text(payload.get("prompt")) or row["reason"] == INTERRUPTED):
            return None
        if previous is not None:
            prior = db.execute("SELECT user_event, scope, epoch FROM turns WHERE client=? AND session=? AND seq<?"
                               " ORDER BY seq DESC LIMIT 1", (client, session, row["seq"])).fetchone()
            if not prior or (prior["user_event"], prior["scope"], prior["epoch"]) != (previous, scope, row["epoch"]):
                return None
        db.execute("UPDATE turns SET scope=? WHERE seq=?", (scope, row["seq"]))
        return row["user_event"]


def attach(private, client, session, event_id, scope, *, approved):
    _session(client, session)
    if approved is not True or not _scope(scope):
        raise ValueError("Approve the exact exchange and work scope before attaching it")
    with _store(private) as db:
        row = _reference(db, event_id, None)
        if (not row or row["client"] != client or row["session"] != session or not row["prompt"]
                or row["scope"] not in (None, scope)):
            raise ValueError("This exchange is unavailable for attachment in the selected scope")
        db.execute("UPDATE turns SET scope=? WHERE seq=?", (scope, row["seq"]))
        return {"id": event_id, "scope": scope}


def latest_reference(private, client, session_id, *, scope):
    _session(client, session_id)
    if not _scope(scope):
        return None
    with _store(private) as db:
        if not _allowed(db, client, session_id):
            return None
        row = db.execute("SELECT * FROM turns WHERE client=? AND session=? ORDER BY seq DESC LIMIT 1",
                         (client, session_id)).fetchone()
        if row and row["scope"] == scope and row["prompt"]:
            events = list(_events(row))
            event = events[-1] if row["state"] == "complete" else events[0]
            return {key: value for key, value in event.items() if key != "text"}
    return None


def later_exchanges(private, event_id, *, scope, limit=8):
    if not _scope(scope) or type(limit) is not int or not 1 <= limit <= 16:
        return []
    with _store(private) as db:
        row = _reference(db, event_id, scope)
        if not row or not row["prompt"]:
            return []
        # Stop at the first change of scope or consent. Count metadata across the allowed
        # interval, then read text only from its newest turns.
        interval = (row["client"], row["session"], row["seq"])
        boundary = db.execute("SELECT MIN(seq) FROM turns WHERE client=? AND session=? AND seq>?"
                              " AND (scope IS NOT ? OR epoch!=?)", (*interval, scope, row["epoch"])).fetchone()[0]
        clause = "WHERE client=? AND session=? AND seq>=?"
        if boundary is not None:
            clause += " AND seq<?"
            interval = (*interval, boundary)
        turns = db.execute("SELECT COUNT(*) FROM turns " + clause, interval).fetchone()[0]
        rows = db.execute("SELECT * FROM turns " + clause + " ORDER BY seq DESC LIMIT ?",
                          (*interval, (limit + 1) // 2)).fetchall()
        result = []
        for following in reversed(rows):
            if following["state"] == "pending":
                _recover(db, private, following, time.time())
                following = db.execute("SELECT * FROM turns WHERE seq=?", (following["seq"],)).fetchone()
            for event in _events(following):
                if following["seq"] == row["seq"] and (event_id == row["reply_event"] or event["role"] == "human"):
                    continue
                result.append(event)
        result = result[-limit:]
        skipped = 2 * turns - (2 if event_id == row["reply_event"] else 1) - len(result)
        if result and skipped:
            result[0]["omitted_earlier_events"] = skipped
        return result


def delete(private, *, client=None, session_id=None):
    if client is not None or session_id is not None:
        _session(client, session_id)
    with _store(private) as db:
        removed = 0
        if db and client:
            removed = db.execute("DELETE FROM turns WHERE client=? AND session=?", (client, session_id)).rowcount
        elif db:
            removed = db.execute("DELETE FROM turns").rowcount
        return {"deleted_turns": removed}


def owner_operation(args):
    return args.operation in ("stores", "delete-store") or (args.operation == "prune" and getattr(args, "store", None) is not None)


def _owner_home():
    if os.environ.get("PM_HUB_PROTECTED_ROOT"):
        raise ValueError("Manage local journal stores from the PM's own terminal")
    return _journal_home()


def stores():
    base = _owner_home()
    result = []
    if base.is_dir():
        for folder in sorted(base.iterdir()):
            if not STORE_ID.fullmatch(folder.name):
                continue
            _secure(folder, directory=True)
            with _folder_lock(folder):
                file = folder / "journal.sqlite3"
                if os.path.lexists(file):
                    _secure(file, directory=False)
                    result.append({"store_id": folder.name, "modified": _time(file.stat().st_mtime)})
    return {"stores": result}


def maintain_store(store_id, *, erase=False):
    if not isinstance(store_id, str) or not STORE_ID.fullmatch(store_id):
        raise ValueError("Choose the full store ID from journal stores")
    folder = _owner_home() / store_id
    if not os.path.lexists(folder):
        raise ValueError("The selected local journal store is unavailable")
    _secure(folder, directory=True)
    with _folder_lock(folder, exclusive=True):
        file = folder / "journal.sqlite3"
        if not os.path.lexists(file):
            return {"store_id": store_id, "status": "absent"}
        if erase:
            # The lock also covers live hooks. Erasure does not depend on a readable SQLite schema.
            files = [file.with_name(file.name + suffix) for suffix in ("-journal", "-wal", "-shm", "")]
            existing = [path for path in files if os.path.lexists(path)]
            for path in existing:
                _secure(path, directory=False)
            for path in existing:
                path.unlink()
        else:
            with _database(folder):
                pass  # Opening this one store applies its own retention period.
    return {"store_id": store_id, "status": "deleted" if erase else "pruned"}


def register(commands):
    journal = commands.add_parser("journal", help="Control private local session continuity")
    ops = journal.add_subparsers(dest="operation", required=True)
    for name in ("status", "enable", "disable", "stores", "delete-all"):
        ops.add_parser(name)
    ops.add_parser("prune").add_argument("--store", metavar="ID", help="Expire old turns in this local store")
    ops.add_parser("delete-store").add_argument("store", metavar="ID", help="Erase this store and its consent")
    ops.add_parser("retention").add_argument("days", type=int)
    for name in ("show", "reference", "attach", "pause", "resume", "delete"):
        action = ops.add_parser(name)
        action.add_argument("--client", choices=CLIENTS, required=True)
        action.add_argument("--session", required=True)
        if name == "attach":
            action.add_argument("--event", required=True)
            action.add_argument("--approved", action="store_true")
        if name in ("reference", "attach"):
            action.add_argument("--scope", required=True)
        if name == "show":
            action.add_argument("--limit", type=int, default=20)


def run(private, args):
    op = args.operation
    if owner_operation(args):
        return stores() if op == "stores" else maintain_store(args.store, erase=op == "delete-store")
    if op in ("status", "prune"):
        return status(private)
    if op in ("enable", "disable"):
        return configure(private, enabled=op == "enable")
    if op == "retention":
        return configure(private, days=args.days)
    if op in ("pause", "resume"):
        return set_off_record(private, args.client, args.session, op == "pause")
    if op == "attach":
        return attach(private, args.client, args.session, args.event, args.scope, approved=args.approved)
    if op == "reference":
        return latest_reference(private, args.client, args.session, scope=args.scope)
    if op == "show":
        return read_session(private, args.client, args.session, limit=args.limit)
    return delete(private) if op == "delete-all" else delete(private, client=args.client, session_id=args.session)
