"""Classify Workspace citations and read the exact bounded bytes of an eligible local source."""
import os
from pathlib import PurePosixPath
import re
import stat
from urllib.parse import unquote, urlsplit

LIMIT = 128 * 1024
_COMPONENT = re.compile(r"[\w -]+(?:\.[\w-]+)*")
_LINK = re.compile(r"\[[^\]\n]+\]\((<[^>\n]+>|[^\s)]+)\)")
_EXCLUDED = {"secrets", "customizations", "profiles"}


def target(reference):
    match = _LINK.fullmatch(reference)
    return match[1].strip("<>") if match else reference


def local_name(reference):
    """Return a safe Workspace path, None for external citations, or reject a malformed file reference."""
    value = target(reference)
    parsed = urlsplit(value)
    if parsed.scheme in ("https", "http"):
        return None
    if parsed.scheme and parsed.scheme != "file" and not re.match(r"^[a-zA-Z]:[/\\]", value):
        if "/" in value or "\\" in value:
            raise ValueError("Use a supported source reference")
        return None
    name = unquote(parsed.path)
    path = PurePosixPath(name)
    file_like = ("/" in name or "\\" in name or path.suffix.lower() in {".md", ".txt", ".json"}
                 or bool(re.fullmatch(r"[^\s/]+\.[a-zA-Z][a-zA-Z0-9]{0,15}", name))
                 or bool(parsed.netloc) or parsed.scheme == "file" or bool(_LINK.fullmatch(reference)))
    if not file_like:
        return None
    if (parsed.scheme or parsed.netloc or parsed.query or path.as_posix() != name or path.is_absolute()
            or len(path.parts) < 2 or path.suffix.lower() not in (".md", ".txt")
            or path.parts[0] in {"handoffs", "onboarding"}
            or path.parts[:2] in {("workspace", "handoffs"), ("workspace", "onboarding")}
            or any(part.casefold() in _EXCLUDED or not _COMPONENT.fullmatch(part) for part in path.parts)):
        raise ValueError("Use an eligible private evidence document")
    return path.as_posix()


def transferred_paths(private):
    """Historical private bytes cannot answer for an owner whose transfer has begun."""
    from oryx.workspace import identity
    directory = identity.local_file(private, ".oryx/state/transfers")
    if not directory.exists():
        return set()
    if not directory.is_dir():
        raise ValueError("Invalid transfer record directory")
    registry = identity.load(private)
    blocked = set()
    for rid, row in registry["records"].items():
        if (identity.transfer_status(private, rid) or {}).get("status") in {"pending", "transferred"}:
            blocked.update(row["aliases"])
    return blocked


def _stamp(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def read(private, name, coverage, offset, supplied=None, length=None):
    """Use anchored file descriptors to keep the authoritative read inside this Workspace."""
    if local_name(name) != name or coverage not in ("read", "partial"):
        raise ValueError("Use an available local evidence document")
    if type(offset) is not int or not 0 <= offset <= 2**40 or coverage == "read" and offset:
        raise ValueError("Check the UTF-8 byte offset")
    if supplied is not None and (not isinstance(supplied, str) or len(supplied) > LIMIT):
        raise ValueError("Use a bounded inspected passage")
    supplied_bytes = None if supplied is None else supplied.encode()
    if length is None and supplied_bytes is not None:
        length = len(supplied_bytes)
    if coverage == "partial" and (type(length) is not int or not 0 < length <= LIMIT):
        raise ValueError("A partial local read needs a bounded passage")
    if supplied_bytes is not None and len(supplied_bytes) > LIMIT:
        raise ValueError("The supplied passage exceeds the read limit")
    if name in transferred_paths(private):
        raise ValueError("Obtain current permission from the authoritative record owner")
    flags = os.O_RDONLY | os.O_NOFOLLOW
    parts = PurePosixPath(name).parts
    directory = os.open(private, flags | os.O_DIRECTORY)
    try:
        for part in parts[:-1]:
            child = os.open(part, flags | os.O_DIRECTORY, dir_fd=directory)
            os.close(directory)
            directory = child
        fd = os.open(parts[-1], flags | os.O_NONBLOCK, dir_fd=directory)
        with os.fdopen(fd, "rb") as stream:
            before = os.fstat(fd)
            if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
                raise ValueError("Use an independent regular source document")
            stream.seek(offset)
            raw = stream.read(length if coverage == "partial" else LIMIT + 1)
            after = os.fstat(fd)
            named = os.stat(parts[-1], dir_fd=directory, follow_symlinks=False)
            if _stamp(before) != _stamp(after) or _stamp(named) != _stamp(after):
                raise ValueError("The original changed during its authorized read")
    finally:
        os.close(directory)
    if not raw or len(raw) > LIMIT or (coverage == "partial" and len(raw) != length):
        raise ValueError("The authorized original passage is missing or too large")
    if supplied_bytes is not None and raw != supplied_bytes:
        raise ValueError("The supplied passage differs from the authorized original")
    if name in transferred_paths(private):
        raise ValueError("Record authority changed during its read")
    raw.decode("utf-8")
    return raw, after, offset + len(raw) == after.st_size
