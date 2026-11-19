"""Serialize local Hub writers and publish complete files atomically."""

from contextlib import contextmanager
import os
from pathlib import Path
import stat
import subprocess
from tempfile import NamedTemporaryFile


def private_root(root):
    """Choose one physical private checkout, including installations awaiting conversion."""
    current, previous = root / "private", root / "workspace"
    if os.path.lexists(current) and os.path.lexists(previous):
        raise ValueError("Both private/ and workspace/ exist. Identify the private repository before alignment")
    return previous if os.path.lexists(previous) else current


@contextmanager
def repository_lock(private):
    # A stable inode in Git metadata survives replacement of the document being edited.
    lock = private / ".git" / "pm-hub-writer.lock"
    if lock.resolve() != lock or not lock.parent.is_dir():
        raise ValueError("Expected a lock inside the private repository")
    with lock.open("a+b") as stream:
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
        yield  # Closing the descriptor also releases the lock after exceptions.


@contextmanager
def writer_lock(private):
    root = private.parent
    if private.name in {"private", "workspace"} and (root / "playbook/release.json").is_file():
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


def replace_text(target, original, candidate):
    """Call under writer_lock. Reject stale or redirected paths before publishing."""
    if target.resolve() != target:
        raise ValueError("Use a regular workspace file")
    current = target.read_text(encoding="utf-8") if target.is_file() else None
    if current != original and not (original is not None and target.is_file() and target.read_bytes() == original.encode("utf-8")):
        raise ValueError(f"{target.name} changed since it was read; retry with the current file")
    target.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=target.parent, delete=False) as stream:
        tmp = Path(stream.name)
        try:
            stream.write(candidate.encode("utf-8"))
            stream.close()
            if original is None:
                os.link(tmp, target)
            else:
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
            capture_output=True, text=True, check=True,
        )
        return sorted({root / p for p in result.stdout.split("\0") if p})
    paths = []
    for directory, dirs, names in os.walk(root, followlinks=False):
        for name in list(dirs):
            path = Path(directory) / name
            if path.is_symlink():
                paths.append(path)
                dirs.remove(name)
            elif name in SKIP_DIRS or name == "secrets" or (path.parent == root and path.name in {"workspace", "private"} and (root / "tools/pm.py").is_file()):
                dirs.remove(name)
        paths.extend(Path(directory) / name for name in names)
    return sorted(paths)
