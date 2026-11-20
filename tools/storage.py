"""Serialize local Hub writers and publish complete files atomically."""

from contextlib import contextmanager
from contextvars import ContextVar
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
from tempfile import NamedTemporaryFile

SHARED_GROUP = "PM_HUB_SHARED_GROUP"
STUDIO = "studio"
PRIVATE_ROOTS = (STUDIO, "private", "workspace")
PRIVATE_PATHSPECS = tuple(f":(icase,literal){name}" for name in PRIVATE_ROOTS)


def initiative_mode(path, *, draft):
    """Opt in only on deliberately provisioned group directories for governed files."""
    group = os.environ.get(SHARED_GROUP)
    if not group:
        return None
    if os.name != "posix":
        raise ValueError(f"{SHARED_GROUP} needs a POSIX filesystem with group permissions")
    import grp
    try:
        gid = grp.getgrnam(group).gr_gid
    except KeyError as exc:
        raise ValueError(f"{SHARED_GROUP} must name an existing group") from exc
    mode = 0o2770 if draft else 0o2750
    parent = path.parent
    if parent.resolve() != parent or not parent.is_dir():
        raise ValueError(f"Provision {parent} for group {group} with mode {mode:04o}")
    info = parent.stat()
    if info.st_gid != gid or stat.S_IMODE(info.st_mode) != mode:
        raise ValueError(f"Provision {parent} for group {group} with mode {mode:04o}")
    return 0o660 if draft else 0o640


def unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def json_input(value):
    def reject(constant):
        raise ValueError(f"Invalid JSON number: {constant}")
    return json.loads(value, object_pairs_hook=unique_keys, parse_constant=reject)


# Windows permits reading a locked range through the lock owner’s file handle.
# Keep that handle available only during the context that acquired it.
_repository_handles = ContextVar("pm_hub_repository_handles", default=())


def private_root(root):
    """Choose one physical private checkout, including installations awaiting conversion."""
    if not root.is_dir():
        return root / STUDIO
    found = sorted(path for path in root.iterdir() if path.name.casefold() in PRIVATE_ROOTS)
    if len(found) > 1:
        paths = ", ".join(path.name + "/" for path in found)
        raise ValueError(f"Multiple PM repository roots exist ({paths}). Identify the active repository before alignment")
    if not found:
        return root / STUDIO
    path = found[0]
    if not os.path.lexists(root / path.name.casefold()):
        raise ValueError(f"PM repository {path.name}/ needs its lowercase name {path.name.casefold()}/ on this filesystem")
    return path


def rename_exclusive(previous, target):
    """Atomically move a file or directory only if the destination is absent."""
    if os.name == "nt":
        os.rename(previous, target)  # Windows refuses an existing destination.
        return
    import ctypes
    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform.startswith("linux") and hasattr(libc, "renameat2"):
        result = libc.renameat2(-100, os.fsencode(previous), -100, os.fsencode(target), 1)
    elif sys.platform == "darwin" and hasattr(libc, "renamex_np"):
        result = libc.renamex_np(os.fsencode(previous), os.fsencode(target), 4)
    else:
        raise ValueError("This filesystem needs an exclusive rename. Preserve both paths for review")
    if result:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code), str(target))


@contextmanager
def repository_lock(private):
    # A stable inode in Git metadata survives replacement of the document being edited.
    lock = private / ".git" / "pm-hub-writer.lock"
    if lock.resolve() != lock or not lock.parent.is_dir():
        raise ValueError("Expected a lock inside the private repository")
    shared = os.name == "posix" and os.environ.get(SHARED_GROUP)
    if shared and not lock.is_file():
        raise ValueError("Provision a group-readable oryx writer lock before enabling group sharing")
    # POSIX flock can take an exclusive lock on a read-only descriptor.
    # The launcher provisions this inode before entering the protected session.
    readonly = shared or os.name == "posix" and lock.is_file()
    with lock.open("rb" if readonly else "a+b") as stream:
        if os.name == "nt":
            import msvcrt
            if stream.tell() == 0:
                stream.write(b"0")
                stream.flush()
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(stream, fcntl.LOCK_EX)
        token = _repository_handles.set((*_repository_handles.get(), (lock, stream)))
        try:
            yield
        finally:
            _repository_handles.reset(token)  # Closing the descriptor releases its lock.


@contextmanager
def snapshot_reader(path):
    """Read the exact bytes of a held lock without reopening its mandatory Windows range."""
    for locked_path, stream in _repository_handles.get():
        if locked_path == path:
            if not os.path.samestat(os.fstat(stream.fileno()), path.lstat()):
                raise ValueError(f"The held repository lock was replaced during backup: {path}")
            position = stream.tell()
            try:
                stream.seek(0)
                yield stream
            finally:
                stream.seek(position)
            return
    with path.open("rb") as source:
        yield source


@contextmanager
def writer_lock(private):
    root = private.parent
    if private.name.casefold() in PRIVATE_ROOTS and (root / "playbook/release.json").is_file():
        # The outer inode remains in place when the private checkout changes its name.
        with repository_lock(root):
            if private_root(root) != private:
                raise ValueError("The private repository moved. Retry with its current location")
            with repository_lock(private):
                yield
    else:
        with repository_lock(private):
            yield


def require_visible(private, relative):
    """Prevent active writes that the private repository would omit from a save."""
    check = subprocess.run(["git", "-C", str(private), "check-ignore", "--", str(relative)],
                           capture_output=True, text=True)
    if check.returncode == 0:
        raise ValueError(f"The private repository ignores {relative}. Review its ignore rules before filing")
    if check.returncode != 1:
        raise ValueError(f"Cannot verify the private Git status of {relative}")


def replace_text(target, original, candidate, *, mode=None):
    """Call under writer_lock. Reject stale or redirected paths before publishing."""
    if target.resolve() != target:
        raise ValueError("Use a regular workspace file")
    if isinstance(original, bytes):
        matches = target.is_file() and target.read_bytes() == original
    else:
        current = target.read_text(encoding="utf-8") if target.is_file() else None
        matches = current == original or (original is not None and target.is_file()
                                          and target.read_bytes() == original.encode("utf-8"))
    if not matches:
        raise ValueError(f"{target.name} changed since it was read; retry with the current file")
    target.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=target.parent, delete=False) as stream:
        tmp = Path(stream.name)
        try:
            stream.write(candidate.encode("utf-8"))
            if mode is not None:
                os.fchmod(stream.fileno(), mode)
            stream.close()
            if original is None:
                os.link(tmp, target)
            else:
                if mode is None:
                    os.chmod(tmp, stat.S_IMODE(target.stat().st_mode))
                os.replace(tmp, target)
        finally:
            tmp.unlink(missing_ok=True)


SKIP_DIRS = {".git", "__pycache__", ".venv", "node_modules", ".state", ".generated", "worktrees"}


def inventory(root: Path) -> list[Path]:
    """Respect Git ignore rules. The fallback supports disposable test fixtures."""
    if (root / ".git").exists():
        result = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            capture_output=True, check=True,
        )
        return sorted({root / os.fsdecode(name) for name in result.stdout.split(b"\0") if name})
    paths = []
    for directory, dirs, names in os.walk(root, followlinks=False):
        for name in list(dirs):
            path = Path(directory) / name
            if path.is_symlink():
                paths.append(path)
                dirs.remove(name)
            elif name in SKIP_DIRS or name == "secrets" or (path.parent == root and path.name.casefold() in PRIVATE_ROOTS and (root / "tools/pm.py").is_file()):
                dirs.remove(name)
        paths.extend(Path(directory) / name for name in names)
    return sorted(paths)
