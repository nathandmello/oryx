"""Disposable verified GitHub generations. The Workspace connection selects one digest."""
import os
from pathlib import Path
import re
import stat
import tempfile

from oryx.governance.common import LIMIT, SHA, canonical, decode, digest
from oryx.governance.files import directory, read, save
from oryx.recovery.snapshot import git_output


HOME = ".oryx/cache/github"
MAX_RECORDS = 256


def local_meta(private, binding, create=False):
    from .connections import key
    return directory(private, ".git/oryx-scope-sync/" + key("github", binding["scope"]) + "/cache-location", create)


def cache_folder(private, binding, base, create=False):
    from .connections import key
    from .location import workspace_id
    core = Path(__file__).resolve().parents[3]
    install = core.parents[2] if core.parents[1].name == "generations" else core
    if not base.is_absolute() or base.resolve() != base or any(base.is_relative_to(p) for p in (private, install)):
        raise ValueError("Choose an absolute cache directory outside the Workspace and Core, without links")
    node = private.stat()
    workspace = workspace_id(private)
    if workspace != binding["workspace"]:
        raise ValueError("The replica belongs to a different Workspace")
    bucket = digest(canonical([workspace, node.st_dev, node.st_ino]))
    folder = base / "oryx" / "github-replicas" / bucket / key("github", binding["scope"])
    if any(p.is_relative_to(folder) or folder.is_relative_to(p) for p in (private, install)):
        raise ValueError("The replica cache must be physically separate from the Workspace and Core")
    system_owner = Path(folder.anchor).stat().st_uid
    for part in [*reversed(folder.parents), folder]:
        git = part/".git"
        if part.is_symlink() or git.is_file() or git.is_symlink() or (git/"HEAD").is_file():
            raise ValueError("The replica cache cannot follow links or live in a Git worktree")
        if not part.exists():
            if not create:
                continue
            part.mkdir(mode=0o700, exist_ok=True)
        info = part.lstat()
        if not stat.S_ISDIR(info.st_mode):
            raise ValueError("Unsafe replica cache path")
        if part.is_relative_to(base/"oryx"):
            if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
                raise ValueError("Shared replicas require PM-owned private directories")
        elif info.st_uid not in (system_owner,os.geteuid()) or (info.st_mode & 0o022 and not info.st_mode & stat.S_ISVTX):
            raise ValueError("Unsafe writable ancestor of the replica cache")
    return folder


def location(private, binding, *, create=False, cleanup=False):
    base = Path(os.environ.get("XDG_CACHE_HOME") or (Path.home()/".cache"))
    pin = local_meta(private, binding) / "root.json"
    if os.path.lexists(pin):
        recorded = read(pin)
        if (set(recorded) != {"workspace","scope","base"} or recorded["workspace"] != binding["workspace"]
                or recorded["scope"] != binding["scope"]):
            raise ValueError("Unverified replica cache location")
        pinned = Path(recorded["base"])
        if base != pinned and not cleanup:
            raise ValueError("Disconnect this scope before selecting a different personal cache")
        base = pinned
    folder = cache_folder(private, binding, base, create=create)
    if create and not pin.exists():
        local_meta(private, binding, True)
        save(pin, {"workspace":binding["workspace"],"scope":binding["scope"],"base":str(base)})
    return folder


def forget(private, binding):
    prune(private, binding)
    (local_meta(private, binding)/"root.json").unlink(missing_ok=True)


def envelope(binding, revision, records):
    return {"schema":1, "scope":binding["scope"], "actor":binding["actor"], "authority":binding["authority"],
            "branch":binding["branch"], "workspace":binding["workspace"], "revision":revision, "records":records}


def inspect(path):
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_nlink != 1
            or stat.S_IMODE(info.st_mode) != 0o400 or info.st_size > LIMIT):
        raise ValueError("Unverified shared replica file")
    contents = path.read_bytes()
    if path.name != digest(contents) + ".json":
        raise ValueError("Shared replica bytes do not match their verified generation")
    return decode(contents)


def build_journal(private, binding):
    return location(private, binding) / "in-progress.json"


def recover_build(binding, folder, journal):
    if os.path.lexists(journal):
        job = read(journal)
        if (job.get("workspace") != binding["workspace"] or job.get("scope") != binding["scope"]
                or not re.fullmatch(r"\.building-[a-zA-Z0-9_-]+", job.get("name", ""))):
            raise ValueError("Unverified interrupted shared replica publication")
        scratch = folder / job["name"]
        if os.path.lexists(scratch):
            info = scratch.lstat()
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.geteuid()
                    or [info.st_dev, info.st_ino] != job.get("inode")):
                raise ValueError("Interrupted shared replica scratch identity changed")
            scratch.unlink()
        journal.unlink()


def publish(private, binding, revision, records):
    data = canonical(envelope(binding, revision, records))
    if len(data) > LIMIT or len(records) > MAX_RECORDS:
        raise ValueError("Shared replica exceeds the bounded registered inventory")
    checksum = digest(data)
    retire_internal(private, binding)
    folder = location(private, binding, create=True)
    journal = folder / "in-progress.json"
    recover_build(binding, folder, journal)
    target = folder / (checksum + ".json")
    if os.path.lexists(target):
        inspect(target)
        return checksum
    with tempfile.NamedTemporaryFile(dir=folder, prefix=".building-", delete=False) as output:
        scratch = Path(output.name)
        try:
            info = os.fstat(output.fileno())
            save(journal,
                 {"workspace":binding["workspace"], "scope":binding["scope"], "name":scratch.name,
                  "inode":[info.st_dev, info.st_ino]})
            output.write(data)
            output.flush()
            os.fchmod(output.fileno(), 0o400)
            os.fsync(output.fileno())
        except BaseException:
            scratch.unlink(missing_ok=True)
            raise
    try:
        os.replace(scratch, target)
        fd = os.open(folder, os.O_DIRECTORY | os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        recover_build(binding, folder, journal)
    return checksum


def record(private, binding, rid, filename, authoritative):
    checksum = binding.get("replica")
    if not checksum:
        return authoritative
    if not SHA.fullmatch(checksum):
        raise ValueError("Invalid replica pointer")
    retire_internal(private, binding)
    path = location(private, binding) / (checksum + ".json")
    if not path.exists():
        return authoritative
    data = inspect(path)
    if not isinstance(data,dict) or not isinstance(data.get("records"),dict):
        raise ValueError("Invalid shared replica generation")
    records = data["records"]
    if data != envelope(binding, binding["revision"], records):
        raise ValueError("Shared replica authority or official revision changed")
    row = records.get(rid)
    if row != {"path":filename, "record":authoritative}:
        raise ValueError("Shared replica differs from the current governed record")
    return row["record"]


def remove_generations(folder, binding, keep):
    for path in folder.glob("*.json"):
        if path.name != f"{keep}.json" and re.fullmatch(r"[a-f0-9]{64}\.json", path.name):
            doc = inspect(path)
            if (not isinstance(doc,dict) or doc.get("schema") != 1 or doc.get("scope") != binding["scope"]
                    or doc.get("workspace") != binding.get("workspace")):
                raise ValueError("Unrecognized file at a shared replica address")
            path.unlink()


def retire_internal(private, binding):
    from .connections import key
    name = key("github", binding["scope"])
    folder = directory(private, HOME + "/" + name)
    if folder.is_dir():
        if git_output(private, "ls-files", "--cached", "--", HOME):
            raise ValueError("Preserve and review tracked legacy cache paths before synchronization")
        old_journal = directory(private, ".git/oryx-scope-sync/" + name + "/build") / "receipt.json"
        recover_build(binding, folder, old_journal)
        remove_generations(folder, binding, None)


def prune(private, binding, keep=None):
    pin = local_meta(private, binding) / "root.json"
    if os.path.lexists(pin):
        folder = location(private, binding, cleanup=True)
        if folder.is_dir():
            recover_build(binding, folder, folder / "in-progress.json")
            remove_generations(folder, binding, keep)
    retire_internal(private, binding)
