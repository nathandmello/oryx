"""Inventory, archive and restore an offline Linux Workspace without activating it."""

from contextlib import contextmanager, nullcontext
import ctypes
import errno
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
import tempfile
import zipfile


FORMAT = "oryx-local-workspace-backup-v1"
MANIFEST = "inventory.json"
BLOCK = 1024 * 1024


def require_pm_terminal():
    if "PM_HUB_PROTECTED_ROOT" in os.environ:
        raise ValueError("Use the PM terminal for offline Workspace recovery")


def local(path):
    require_pm_terminal()
    if sys.platform != "linux":
        raise ValueError("Local recovery currently requires Linux")
    path = Path(os.path.abspath(path))
    if path != path.resolve():
        raise ValueError("Use an unredirected local path")
    return path


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("ascii")


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def verified(value, expected):
    if not re.fullmatch(r"[0-9a-f]{64}", expected) or digest(value) != expected:
        raise ValueError("Inventory differs from the previously reviewed digest")


def copy_bytes(reader, writer=None):
    checksum = hashlib.sha256()
    count = 0
    for block in iter(lambda: reader.read(BLOCK), b""):
        checksum.update(block)
        count += len(block)
        if writer is not None:
            writer.write(block)
    return count, checksum.hexdigest()


def stamp(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns, info.st_uid, info.st_gid)


def mounted_below(root):
    with open("/proc/self/mountinfo", encoding="utf-8", errors="surrogateescape") as mounts:
        for line in mounts:
            name = re.sub(r"\\([0-7]{3})", lambda m: chr(int(m[1], 8)), line.split()[4])
            if root in Path(name).parents:
                raise ValueError("Nested mounts require a separate recovery plan")


def machine_scope():
    machine = Path("/etc/machine-id").read_bytes().strip()
    if not re.fullmatch(b"[0-9a-f]{32}", machine):
        raise ValueError("A stable local machine identity is required for local recovery")
    return {"machine": hashlib.sha256(b"oryx-local-recovery\0" + machine).hexdigest(),
            "uid": os.geteuid(), "gid": os.getegid()}


@contextmanager
def idle_writer(source):
    """Share an existing Oryx writer lock without creating anything in the source."""
    import fcntl
    path = source / ".git/pm-hub-writer.lock"
    if not os.path.lexists(path):
        yield
        return
    if path.resolve() != path or not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError("Expected a regular Oryx writer lock")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_NOATIME)
    try:
        fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)


def inventory(source, archive=None):
    """Walk regular files, directories and internal symlinks using anchored descriptors."""
    root = local(source)
    mounted_below(root)
    entries = []
    stamps = {}
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NOATIME | os.O_NONBLOCK
    root_fd = os.open(root, flags | os.O_DIRECTORY)
    device = os.fstat(root_fd).st_dev

    def visit(parent_fd, name, path):
        before = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        if before.st_dev != device or before.st_uid != os.geteuid() or before.st_gid != os.getegid():
            raise ValueError(f"Unsupported filesystem or ownership at {path}")
        mode = stat.S_IMODE(before.st_mode)
        if mode & 0o7000 or os.listxattr(f"/proc/self/fd/{parent_fd}/{name}", follow_symlinks=False):
            raise ValueError(f"Special permissions or extended attributes require separate handling at {path}")
        record = {"path": str(path), "mode": mode, "mtime_ns": before.st_mtime_ns}
        index = len(entries)
        entries.append(record)
        stamps[str(path)] = stamp(before)
        if stat.S_ISLNK(before.st_mode):
            target = os.readlink(name, dir_fd=parent_fd)
            if path.parts[:1] == (".git",) or os.path.isabs(target) or ".." in Path(target).parts:
                raise ValueError(f"Unsupported link destination at {path}")
            record.update(kind="link", target=target)
        elif stat.S_ISDIR(before.st_mode):
            record["kind"] = "directory"
            fd = os.open(name, flags | os.O_DIRECTORY, dir_fd=parent_fd)
            try:
                if stamp(os.fstat(fd)) != stamp(before):
                    raise ValueError(f"Directory changed during inventory: {path}")
                for child in sorted(os.listdir(fd)):
                    if child == ".git" and path != PurePosixPath("."):
                        raise ValueError(f"Nested Git repository at {path}")
                    visit(fd, child, path / child)
            finally:
                os.close(fd)
        elif stat.S_ISREG(before.st_mode) and before.st_nlink == 1:
            fd = os.open(name, flags, dir_fd=parent_fd)
            with os.fdopen(fd, "rb") as reader:
                if stamp(os.fstat(fd)) != stamp(before):
                    raise ValueError(f"File changed during inventory: {path}")
                output = archive.open(str(index), "w", force_zip64=True) if archive else nullcontext(None)
                with output as writer:
                    size, sha = copy_bytes(reader, writer)
            record.update(kind="file", size=size, sha256=sha)
        else:
            raise ValueError(f"Unsupported file type or hard link at {path}")
        if stamp(before) != stamp(os.stat(name, dir_fd=parent_fd, follow_symlinks=False)):
            raise ValueError(f"Source changed during inventory: {path}")

    try:
        visit(root_fd, ".", PurePosixPath("."))
        if stamp(root.lstat()) != stamps["."]:
            raise ValueError("Selected Workspace changed during inventory")
    finally:
        os.close(root_fd)
    manifest = {"format": FORMAT, "local_scope": machine_scope(), "entries": entries}
    validate_layout(entries)
    return manifest, stamps


def inspect(source):
    source = local(source)
    with idle_writer(source):
        manifest, before = inventory(source)
        confirmed, after = inventory(source)
    if before != after or manifest != confirmed:
        raise ValueError("Source changed during inspection; stop writers and retry")
    return manifest


def validate_layout(entries):
    by_path = {r["path"]: r["kind"] for r in entries}
    if by_path.get("settings.json") != "file" and by_path.get(".oryx/workspace.json") != "file":
        raise ValueError("Expected Oryx Workspace settings or a Workspace identity")
    for path, kind in {".git": "directory", ".git/HEAD": "file", ".git/config": "file",
                       ".git/objects": "directory", ".git/refs": "directory"}.items():
        if by_path.get(path) != kind:
            raise ValueError("Recovery requires a complete standalone Git Workspace")
    unsupported = {".git/commondir", ".git/gitdir", ".git/worktrees", ".git/modules",
                   ".git/shallow", ".git/info/grafts", ".git/config.worktree",
                   ".git/objects/info/alternates", ".git/objects/info/http-alternates"}
    for name in by_path:
        if (name in unsupported or name.startswith(".git/") and name != ".git/pm-hub-writer.lock"
                and name.endswith((".lock", ".promisor"))):
            raise ValueError(f"External, partial or in-flight Git state requires separate recovery: {name}")
        if name.startswith(".git/hooks/") and not name.endswith(".sample"):
            raise ValueError(f"Active Git hook requires separate recovery: {name}")


def git_output(tree, *args):
    env = {"PATH": os.defpath, "LC_ALL": "C", "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_CONFIG_GLOBAL": os.devnull, "GIT_ALLOW_PROTOCOL": "", "GIT_NO_LAZY_FETCH": "1",
           "GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0"}
    result = subprocess.run(["git", "-C", str(tree), "-c", "core.hooksPath=/dev/null", *args],
                            env=env, stdin=subprocess.DEVNULL, capture_output=True, timeout=180)
    if result.returncode:
        raise ValueError("Git metadata, index or object connectivity could not be verified")
    return result.stdout


def check_repository(tree):
    """Only inspect self-contained ordinary repos. Never execute imported Git helpers or hooks."""
    config = git_output(tree, "config", "--no-includes", "--file", str(tree / ".git/config"),
                        "--null", "--list")
    allowed = re.compile(rb"(core\.(repositoryformatversion|filemode|bare|logallrefupdates|ignorecase|"
                         rb"precomposeunicode|symlinks)|user\.(name|email)|remote\..+\.(url|fetch|pushurl)|"
                         rb"branch\..+\.(remote|merge))")
    for item in config.split(b"\0"):
        if not item:
            continue
        key, _, value = item.partition(b"\n")
        if (not allowed.fullmatch(key) or key == b"core.bare" and value.lower() != b"false"
                or key == b"core.repositoryformatversion" and value != b"0"):
            raise ValueError("Unsupported local Git configuration requires separate recovery")
    index = git_output(tree, "ls-files", "--stage", "-z").split(b"\0")
    if any(entry.startswith(b"160000 ") for entry in index):
        raise ValueError("Submodule state requires separate recovery")
    git_output(tree, "fsck", "--full", "--strict", "--no-progress")


def check_destination(source, destination):
    destination = local(destination)
    if (destination == source or source in destination.parents or destination in source.parents
            or os.path.lexists(destination)):
        raise ValueError("Choose a new side-by-side destination outside the source")
    core = Path(__file__).resolve().parents[3]
    installation = core
    if core.name == "core" and core.parent.parent.name == "generations" and re.fullmatch("[0-9a-f]{32}", core.parent.name):
        installation = core.parent.parent.parent
    if destination.is_relative_to(installation):
        raise ValueError("Place recovery output outside the Oryx Core installation")
    for parent in destination.parents:
        if ((parent / "oryx-release-manifest.json").is_file()
                or (parent / ".install.lock").is_file() and (parent / "generations").is_dir()):
            raise ValueError("Place recovery output outside all Oryx Core installations")
    if any((parent / ".git/HEAD").is_file() or (parent / ".git").is_file() for parent in destination.parents):
        raise ValueError("Place recovery output outside existing Git workspaces")
    info = destination.parent.stat()
    if info.st_uid != os.geteuid() or info.st_mode & 0o077:
        raise ValueError("Choose a destination in a directory private to the current user")
    return destination


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def publish_new(source, destination):
    """renameat2 with RENAME_NOREPLACE makes the publication atomic even under contention."""
    libc = ctypes.CDLL(None, use_errno=True)
    rename = getattr(libc, "renameat2", None)
    if rename is None:
        raise ValueError("This filesystem needs a qualified no-replace publication operation")
    if rename(-100, os.fsencode(source), -100, os.fsencode(destination), 1) != 0:
        error = ctypes.get_errno()
        if error == errno.EEXIST:
            raise ValueError("Destination is occupied")
        raise OSError(error, os.strerror(error))
    sync_directory(destination.parent)


def unpack(archive, tree, expected):
    with zipfile.ZipFile(archive) as z:
        if any(member.compress_type != zipfile.ZIP_STORED for member in z.infolist()):
            raise ValueError("Unsupported backup compression format")
        if z.getinfo(MANIFEST).file_size > 64 * 1024 * 1024:
            raise ValueError("Inventory exceeds the supported 64 MiB limit")
        manifest = json.loads(z.read(MANIFEST))
        verified(manifest, expected)
        if manifest.get("format") != FORMAT:
            raise ValueError("Unknown recovery format")
        if manifest.get("local_scope") != machine_scope():
            raise ValueError("This full local backup belongs to a different machine or account")
        entries = manifest["entries"]
        validate_layout(entries)
        names = [MANIFEST] + [str(i) for i, row in enumerate(entries) if row["kind"] == "file"]
        if sorted(z.namelist()) != sorted(names):
            raise ValueError("Incomplete snapshot or unexpected archive members")
        directories = []
        seen = set()
        for index, row in enumerate(entries):
            name = row["path"]
            relative = PurePosixPath(name)
            if (relative.is_absolute() or ".." in relative.parts or str(relative) != name
                    or name in seen or index == 0 and name != "."
                    or index > 0 and str(relative.parent) not in seen):
                raise ValueError("Invalid inventory path or order")
            path = tree / relative
            if path.parent.resolve() != path.parent:
                raise ValueError("Archive entry traverses a link")
            kind = row["kind"]
            if kind == "directory":
                path.mkdir(mode=0o700)
                directories.append((path, row))
            elif kind == "file":
                if z.getinfo(str(index)).file_size != row["size"]:
                    raise ValueError("Archived member length differs from inventory")
                with z.open(str(index)) as reader, path.open("xb") as writer:
                    size, sha = copy_bytes(reader, writer)
                    if (size, sha) != (row["size"], row["sha256"]):
                        raise ValueError("Archived bytes differ from inventory")
                    writer.flush()
                    os.fchmod(writer.fileno(), row["mode"])
                    os.utime(writer.fileno(), ns=(row["mtime_ns"], row["mtime_ns"]))
                    os.fsync(writer.fileno())
            elif kind == "link":
                target = row["target"]
                if relative.parts[:1] == (".git",) or os.path.isabs(target) or ".." in Path(target).parts:
                    raise ValueError("Unsupported archived link")
                path.symlink_to(target)
                os.utime(path, ns=(row["mtime_ns"], row["mtime_ns"]), follow_symlinks=False)
            else:
                raise ValueError("Unknown archived file type")
            seen.add(name)
        for path, row in reversed(directories):
            path.chmod(row["mode"])
            os.utime(path, ns=(row["mtime_ns"], row["mtime_ns"]))
            sync_directory(path)
    check_repository(tree)
    restored, _ = inventory(tree)
    verified(restored, expected)
    return len(entries)


def backup(source, destination, expected):
    source = local(source)
    destination = check_destination(source, destination)
    with idle_writer(source):
        return create_backup(source, destination, expected)


def create_backup(source, destination, expected):
    initial, before = inventory(source)
    verified(initial, expected)
    with tempfile.TemporaryDirectory(prefix=".oryx-backup-", dir=destination.parent) as temporary:
        folder = Path(temporary)
        archive = folder / "snapshot.zip"
        with archive.open("xb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            with zipfile.ZipFile(stream, "w") as z:
                manifest, captured = inventory(source, z)
                verified(manifest, expected)
                z.writestr(MANIFEST, canonical(manifest))
            stream.flush()
            os.fsync(stream.fileno())
        count = unpack(archive, folder / "verification", expected)
        end, after = inventory(source)
        verified(end, expected)
        if before != captured or before != after:
            raise ValueError("Source changed during backup; stop writers and retry")
        publish_new(archive, destination)
    return {"result": "verified-local-backup", "digest": expected, "entries": count}


def restore(archive, destination, expected):
    archive = local(archive)
    destination = check_destination(archive, destination)
    if not stat.S_ISREG(archive.lstat().st_mode):
        raise ValueError("Use a regular local backup file")
    with tempfile.TemporaryDirectory(prefix=".oryx-restore-", dir=destination.parent) as temporary:
        tree = Path(temporary) / "recovered"
        fd = os.open(archive, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_NOATIME)
        with os.fdopen(fd, "rb") as reader:
            if not stat.S_ISREG(os.fstat(reader.fileno()).st_mode):
                raise ValueError("Use a regular local backup file")
            before = stamp(os.fstat(reader.fileno()))
            count = unpack(reader, tree, expected)
            if before != stamp(os.fstat(reader.fileno())) or before != stamp(archive.lstat()):
                raise ValueError("Backup changed during restore")
        publish_new(tree, destination)
    return {"result": "restored-separate-copy", "digest": expected, "entries": count}
