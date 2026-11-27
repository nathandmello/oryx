"""Private scoped state, written by atomic replacement without following links."""
import fcntl
import os
from pathlib import Path
import tempfile

from .common import canonical, decode


def directory(workspace, relative, create=False):
    root = Path(workspace).absolute()
    if root.resolve() != root or not root.is_dir():
        raise ValueError("Select an existing canonical Workspace")
    current = root
    for part in Path(relative).parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("Private state cannot follow links")
        if create:
            current.mkdir(mode=0o700, exist_ok=True)
        if current.exists() and not current.is_dir():
            raise ValueError("Private state directory is invalid")
    return current


def read(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_nlink != 1:
        raise ValueError("Private state is missing or redirected")
    return decode(path.read_bytes())


def save(path, value, *, expected=None):
    with DirLock(path.parent):
        previous = read(path) if os.path.lexists(path) else None
        if previous == value:
            return
        if previous != expected:
            raise ValueError("Private sharing state changed; refresh the current revision")
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".pending-", delete=False) as out:
            temp = Path(out.name)
            try:
                out.write(canonical(value))
                out.flush()
                os.fsync(out.fileno())
            except BaseException:
                temp.unlink(missing_ok=True)
                raise
        try:
            os.replace(temp, path)
            fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        finally:
            temp.unlink(missing_ok=True)


class DirLock:
    def __init__(self, parent):
        self.parent = parent

    def __enter__(self):
        self.fd = os.open(self.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        fcntl.flock(self.fd, fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc):
        os.close(self.fd)
