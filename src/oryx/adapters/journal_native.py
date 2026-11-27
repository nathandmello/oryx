"""Read a bounded, admitted turn from a client-owned transcript after a missed stop."""

from contextlib import contextmanager
from datetime import datetime
import json
import os
from pathlib import Path
import re
import stat

import storage

# A recovery can give up. It must never import a native history or save raw records.
MAX_SCAN = 8 * 1024 * 1024
MAX_LINE = 1024 * 1024


def _path(client, session, raw):
    if not isinstance(raw, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", session):
        return None
    path = Path(raw)
    if not path.is_absolute() or path.resolve() != path:
        return None
    if client == "claude":
        base = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude")) / "projects"
        if path.parent.parent != base or path.name != session + ".jsonl":
            return None
    elif client == "codex":
        base = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")) / "sessions"
        if not path.is_relative_to(base):
            return None
        pieces = path.relative_to(base).parts
        if (len(pieces) != 4 or not re.fullmatch(r"\d{4}/\d{2}/\d{2}", "/".join(pieces[:3]))
                or not re.fullmatch(r"rollout-[0-9T:-]+-" + re.escape(session) + r"\.jsonl", path.name)):
            return None
    else:
        return None
    return path


@contextmanager
def _open(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.geteuid()
                or info.st_mode & 0o022):
            raise ValueError("Unsafe client transcript")
        yield stream, info


def _row(line):
    if not line or not line.endswith(b"\n") or len(line) > MAX_LINE:
        raise ValueError("Incomplete client record")
    data = json.loads(line)
    if not isinstance(data, dict):
        raise ValueError("Invalid client record")
    return data


def _time(value):
    date = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if date.tzinfo is None:
        raise ValueError("Client record has no timezone")
    return date.timestamp()


def _cwd(private, value):
    if not isinstance(value, str) or not Path(value).is_absolute():
        return False
    cwd = Path(value).resolve()
    return cwd.is_relative_to(private) or cwd.is_relative_to(storage.core_for(private))


def _claude_user(row):
    message = row.get("message", {})
    origin = row.get("origin")
    if (row.get("type") != "user" or message.get("role") != "user" or row.get("isMeta")
            or row.get("userType") == "external_tool" or row.get("turnOrigin") not in (None, "human")
            or origin is not None and (not isinstance(origin, dict) or origin.get("kind") != "human")):
        return None
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list) and len(content) == 1 and content[0].get("type") == "text":
        return content[0].get("text")
    return None


def _claude_scope(private, session, row):
    return (row.get("sessionId") == session and _cwd(private, row.get("cwd")) and
            not row.get("isSidechain") and not row.get("agentId") and not row.get("isMeta"))


def checkpoint(private, client, session, payload, now):
    """Keep the native inode and current end position only when this client identifies it."""
    try:
        path = _path(client, session, payload.get("transcript_path"))
        if path is None or _cwd(private, str(path)):
            return None
        if client == "claude" and not os.path.lexists(path):
            # Claude can supply its future session filename before creating the first transcript.
            # Pin its nearest existing directory. Later require a new file and this exact human prompt.
            parent = next(directory for directory in path.parents if directory.exists())
            info = parent.stat()
            if parent == Path("/") or not parent.is_dir() or info.st_uid != os.geteuid() or info.st_mode & 0o022:
                return None
            return {"path": str(path), "parent": str(parent), "dev": info.st_dev, "ino": info.st_ino,
                    "offset": 0, "anchor": None}
        with _open(path) as (stream, info):
            anchor = None
            if client == "codex":
                meta = _row(stream.readline(MAX_LINE + 1))
                data = meta.get("payload", {})
                if (meta.get("type") != "session_meta" or data.get("id") != session
                        or not _cwd(private, data.get("cwd")) or isinstance(data.get("source"), dict)):
                    return None
            elif info.st_size:
                # Claude can append the submitted message before invoking its prompt hook.
                stream.seek(max(0, info.st_size - MAX_LINE))
                tail = stream.read(MAX_LINE).splitlines(keepends=True)
                if tail:
                    try:
                        row = _row(tail[-1])
                        if (_claude_scope(private, session, row) and _claude_user(row) == payload["prompt"]
                                and abs(_time(row["timestamp"]) - now) < 5):
                            anchor = row.get("uuid")
                    except (ValueError, KeyError, TypeError, AttributeError):
                        pass
            return {"path": str(path), "dev": info.st_dev, "ino": info.st_ino,
                    "offset": info.st_size, "anchor": anchor}
    except (OSError, ValueError, KeyError, TypeError, AttributeError, RecursionError):
        return None


def _codex_reply(rows, prompt, turn):
    active = turn
    matched = bool(turn)
    for row in rows:
        if row.get("type") == "session_meta":
            return None
        if row.get("type") != "event_msg":
            continue
        data = row.get("payload", {})
        kind = data.get("type")
        if kind == "task_started":
            if active and active != data.get("turn_id"):
                return None
            active = data.get("turn_id")
        elif kind == "user_message":
            if data.get("message") != prompt:
                return None
            matched = True
        elif kind == "turn_aborted":
            return None
        elif kind == "task_complete":
            if active and matched and data.get("turn_id") == active:
                return data.get("last_agent_message"), _time(row["timestamp"])
            return None
    return None


def _claude_reply(rows, private, session, prompt, anchor):
    parent = anchor
    for row in rows:
        if row.get("type") not in {"user", "assistant", "attachment"}:
            continue
        if not _claude_scope(private, session, row):
            return None
        if row.get("type") == "attachment":
            # Only the chain pointer bridges a client-added attachment. Its contents have no journal role.
            if not parent:
                continue
            if parent != row.get("parentUuid"):
                return None
        elif row.get("type") == "user":
            human = _claude_user(row)
            if human is not None:
                if parent or human != prompt:
                    return None
            else:
                # A tool result can bridge this exchange. It supplies no visible PM text.
                content = row.get("message", {}).get("content")
                if not (parent and isinstance(content, list) and content and
                        all(part.get("type") == "tool_result" for part in content)
                        and row.get("parentUuid") == parent):
                    return None
        else:
            if not parent or row.get("parentUuid") != parent:
                return None
            msg = row.get("message", {})
            if msg.get("role") != "assistant":
                return None
            if msg.get("stop_reason") in {"end_turn", "stop_sequence"}:
                blocks = msg.get("content")
                if not isinstance(blocks, list) or any(block.get("type") == "tool_use" for block in blocks):
                    return None
                text = "\n".join(block["text"] for block in blocks if block.get("type") == "text")
                return text, _time(row["timestamp"])
        parent = row.get("uuid")
        if not isinstance(parent, str) or not parent:
            return None
    return None


def recover(private, client, session, cursor, prompt, turn_id, submitted_at):
    """Return the verified final reply and its native timestamp, or leave an explicit gap."""
    try:
        if not cursor:
            return None
        path = _path(client, session, cursor["path"])
        if path is None or _cwd(private, str(path)):
            return None
        with _open(path) as (stream, info):
            offset = cursor["offset"]
            bound = info
            if "parent" in cursor:
                parent = Path(cursor["parent"])
                if (client != "claude" or parent not in path.parents or parent.resolve() != parent
                        or offset != 0):
                    return None
                bound = parent.stat()
            if ((bound.st_dev, bound.st_ino) != (cursor["dev"], cursor["ino"])
                    or not 0 <= offset <= info.st_size):
                return None
            stream.seek(offset)

            def rows():
                while stream.tell() - offset < MAX_SCAN:
                    line = stream.readline(MAX_LINE + 1)
                    if not line:
                        break
                    row = _row(line)
                    if client == "claude" and row.get("type") not in {"user", "assistant", "attachment"}:
                        continue
                    timestamp = _time(row["timestamp"])
                    if timestamp < submitted_at - 0.001:
                        # Clients timestamp the submitted human text before invoking the hook.
                        # Its exact echo can identify the start. A reply must postdate admission.
                        is_prompt_metadata = row.get("type") == "attachment" or _claude_user(row) == prompt
                        if not (client == "claude" and is_prompt_metadata and timestamp >= submitted_at - 5):
                            raise ValueError("Client record predates admission")
                    yield row

            if client == "codex":
                return _codex_reply(rows(), prompt, turn_id)
            return _claude_reply(rows(), private, session, prompt, cursor.get("anchor"))
    except (OSError, ValueError, KeyError, TypeError, AttributeError, RecursionError):
        return None
