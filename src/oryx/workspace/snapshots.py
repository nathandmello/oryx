"""Create and verify a local recovery point before a Hub update changes an installation."""

from contextlib import nullcontext
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tarfile
import tempfile
from uuid import uuid4

import storage


def checksum(stream):
    result = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        result.update(chunk)
    return result.hexdigest()


def entries(root, exclude):
    """Do not follow directory links. Refuse nodes a portable archive cannot restore."""
    inventory = {}
    def visit(path):
        if path == exclude:
            return
        info = path.lstat()
        if not any(test(info.st_mode) for test in (stat.S_ISREG, stat.S_ISDIR, stat.S_ISLNK)):
            raise ValueError(f"Cannot back up special file: {path.relative_to(root)}")
        if getattr(info, "st_file_attributes", 0) & 1024 and not stat.S_ISLNK(info.st_mode):
            raise ValueError(f"Cannot safely traverse reparse point: {path.relative_to(root)}")
        inventory[path.relative_to(root).as_posix()] = (
            info.st_mode, info.st_size, info.st_dev, info.st_ino, info.st_mtime_ns, info.st_ctime_ns)
        if stat.S_ISDIR(info.st_mode):
            for child in sorted(path.iterdir()):
                visit(child)
    visit(root)
    return inventory


def attributes(path):
    if not hasattr(os, "listxattr"):
        return {}
    return {"SCHILY.xattr." + key: os.fsdecode(os.getxattr(path, key, follow_symlinks=False))
            for key in os.listxattr(path, follow_symlinks=False)}


def protect(path):
    if path.resolve() != path:
        raise ValueError("Unsafe backup location")
    if os.name == "posix" and (path.stat().st_uid != os.geteuid() or stat.S_IMODE(path.stat().st_mode) & 0o077):
        raise ValueError(f"Restrict the backup to its owner: {path}")


def local_git(root):
    for git in (root / ".git", storage.private_root(root) / ".git"):
        alternates = git / "objects/info/alternates"
        if ((alternates.exists() and alternates.read_bytes().strip()) or (git / "commondir").exists()
                or (git / "objects").resolve() != git / "objects" or os.environ.get("GIT_ALTERNATE_OBJECT_DIRECTORIES")):
            raise ValueError("Back up a self-contained Git repository; materialise external object stores before upgrading")


def create(root, store, archive):
    before = entries(root, store)
    with tarfile.open(archive, "x:gz", compresslevel=1) as out:
        os.chmod(archive, 0o600)
        for name, info in before.items():
            path = root / name
            member = out.gettarinfo(str(path), arcname=name)
            if member is None:
                raise ValueError(f"Unsupported backup entry: {name}")
            member.pax_headers.update(attributes(path))
            with storage.snapshot_reader(path) if member.isfile() and stat.S_ISREG(info[0]) else nullcontext() as source:
                out.addfile(member, source)
    seen = set()
    # Independently read back the archive and compare every file against the installation.
    with tarfile.open(archive, "r|gz") as saved:
        for member in saved:
            name = member.name
            path = root / name
            if name not in before or name in seen:
                raise ValueError("Unexpected backup entry")
            mode = before[name][0]
            if stat.S_ISLNK(mode):
                matches = member.issym() and member.linkname == os.readlink(path)
            elif stat.S_ISDIR(mode):
                matches = member.isdir()
            elif member.islnk():
                matches = member.linkname in seen and os.path.samefile(path, root / member.linkname)
            elif member.isfile():
                with storage.snapshot_reader(path) as source, saved.extractfile(member) as copy:
                    matches = checksum(source) == checksum(copy)
            else:
                matches = False
            recorded = {k: v for k, v in member.pax_headers.items() if k.startswith("SCHILY.xattr.")}
            if not matches or stat.S_IMODE(mode) != member.mode or recorded != attributes(path):
                raise ValueError(f"Backup verification failed for {name}")
            seen.add(name)
    if seen != before.keys() or entries(root, store) != before:
        raise ValueError("The checkout changed during backup; retry after other writers finish")


def ensure(root, version, *, layout_change=False, studio_change=False):
    """Caller holds the private writer lock. A receipt belongs to this checkout and release."""
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError("Invalid snapshot release")
    label = f"{version}-layout-2" if layout_change else version
    if studio_change:
        label = f"{version}-studio"
    receipt = storage.private_root(root) / ".git" / f"pm-hub-backup-{label}.json"
    store = root / ".git" / "pm-hub-backups"
    if receipt.resolve() != receipt or store.resolve() != store:
        raise ValueError("Unsafe backup location")
    if not store.exists():
        store.mkdir(mode=0o700)
    protect(store)
    original = receipt.read_text() if receipt.exists() else None
    if original is None:
        original = json.dumps({"id": uuid4().hex}) + "\n"
        storage.replace_text(receipt, None, original)
    data = json.loads(original)
    if not isinstance(data, dict) or not re.fullmatch(r"[0-9a-f]{32}", str(data.get("id", ""))):
        raise ValueError("Invalid backup receipt")
    target = store / data["id"]
    archive = target / "hub.tar.gz"
    sums = target / "SHA256SUMS"
    if target.exists():
        for path in (target, archive, sums):
            protect(path)
        with archive.open("rb") as stream:
            digest = checksum(stream)
        if (sums.read_text(encoding="ascii") != f"{digest}  hub.tar.gz\n"
                or ("sha256" in data and data["sha256"] != digest)):
            raise ValueError("The existing upgrade backup failed its checksum")
    else:
        if "sha256" in data:
            raise ValueError("The existing upgrade backup is missing")
        local_git(root)
        with tempfile.TemporaryDirectory(dir=store) as temp:
            staged = Path(temp) / "snapshot"
            staged.mkdir(mode=0o700)
            candidate = staged / "hub.tar.gz"
            create(root, store, candidate)
            with candidate.open("rb") as stream:
                digest = checksum(stream)
            signature = staged / "SHA256SUMS"
            signature.write_text(f"{digest}  hub.tar.gz\n", encoding="ascii")
            signature.chmod(0o600)
            staged.rename(target)
    if "sha256" not in data:
        data["sha256"] = digest
        storage.replace_text(receipt, original, json.dumps(data) + "\n")
    return archive
