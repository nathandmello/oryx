"""Verify and activate signed Oryx Core archives. This installer can run standalone."""
import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import tempfile
from uuid import uuid4
import zipfile


MANIFEST = "oryx-release-manifest.json"
STATE = "active.json"
MAX_ARCHIVE = 128 * 1024 * 1024
MAX_MEMBER = 32 * 1024 * 1024
MAX_EXPANDED = 256 * 1024 * 1024
HEX = re.compile(r"[0-9a-f]{64}")
REQUIRED = {
    "LICENSE.md", "bin/oryx", "playbook/release.json", "playbook/workspace-format.json",
    "playbook/commands.json", "tools/pm.py", "tools/search_model/potion.bin",
    "tools/search_model/LICENSE", "tools/search_model/LICENSE.potion-base-8M",
    "tools/workspace-seed/README.md", ".agents/skills/summarize-meeting/LICENSE",
}


def unique_object(pairs):
    result = {}
    for name, value in pairs:
        if name in result:
            raise ValueError("Duplicate key in release metadata")
        result[name] = value
    return result


def file_digest(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def regular(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Expected a regular file: {path.name}")
    return path


def local_path(path):
    path = Path(os.path.abspath(os.fspath(path)))
    if path != path.resolve():
        raise ValueError("Use an unredirected local path")
    return path


def copy_limited(source, destination, limit):
    regular(source)
    total = 0
    with source.open("rb") as reader, destination.open("xb") as writer:
        for block in iter(lambda: reader.read(1024 * 1024), b""):
            total += len(block)
            if total > limit:
                raise ValueError("Release input exceeds size limit")
            writer.write(block)
        writer.flush()
        os.fsync(writer.fileno())


def verify_signature(archive, signature, public_key):
    # The caller supplies an independently provisioned PEM trust anchor.
    result = subprocess.run(
        ["openssl", "dgst", "-sha256", "-verify", str(public_key),
         "-signature", str(signature), str(archive)],
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        timeout=90, check=False,
    )
    if result.returncode != 0:
        raise ValueError("Archive publisher signature verification failed")


def valid_name(name):
    parts = PurePosixPath(name).parts
    return (parts and name == "/".join(parts) and len(name) <= 512
            and all(re.fullmatch(r"[A-Za-z0-9_.-]+", part)
                    and part not in {".", ".."} and not part.endswith(".")
                    and part.casefold().split(".")[0] not in {
                        "con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)),
                        *(f"lpt{i}" for i in range(1, 10)),
                    } for part in parts))


def check_descriptors(version, release, workspace):
    """This bootstrap has qualified the 1-on-the-wire, effective-format-2 contract."""
    if (not isinstance(release, dict) or set(release) != {"system_version", "workspace_format"}
            or release["system_version"] != version or type(release["workspace_format"]) is not int
            or release["workspace_format"] != 1):
        raise ValueError("Invalid or unsupported Core wire release descriptor")
    if (not isinstance(workspace, dict) or set(workspace) != {"workspace_format", "migrate_from"}
            or type(workspace["workspace_format"]) is not int or workspace["workspace_format"] != 2
            or not isinstance(workspace["migrate_from"], list) or len(workspace["migrate_from"]) != 1
            or type(workspace["migrate_from"][0]) is not int or workspace["migrate_from"][0] != release["workspace_format"]):
        raise ValueError("Invalid or unsupported Workspace format descriptor")


def manifest_for(archive):
    entries = archive.infolist()
    if not entries or len(entries) > 4096:
        raise ValueError("Invalid number of release files")
    names = set()
    prefixes = {}
    total = 0
    for entry in entries:
        name = entry.filename
        if (not valid_name(name) or name != entry.orig_filename or name in names
                or entry.flag_bits & 1 or not stat.S_ISREG(entry.external_attr >> 16)
                or entry.file_size > MAX_MEMBER
                or entry.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}):
            raise ValueError("Invalid release member")
        total += entry.file_size
        parts = name.split("/")
        for index in range(1, len(parts) + 1):
            path = "/".join(parts[:index])
            identity = (path, index == len(parts))
            if prefixes.setdefault(path.casefold(), identity) != identity:
                raise ValueError("Conflicting archive paths")
        names.add(name)
    if total > MAX_EXPANDED or not (REQUIRED | {MANIFEST}).issubset(names):
        raise ValueError("Incomplete release or expanded size exceeds limit")
    if archive.getinfo(MANIFEST).file_size > 1024 * 1024:
        raise ValueError("Invalid release manifest size")
    manifest = json.loads(archive.read(MANIFEST), object_pairs_hook=unique_object)
    if (not isinstance(manifest, dict) or set(manifest) != {"schema", "version", "files"}
            or type(manifest["schema"]) is not int or manifest["schema"] != 1
            or not isinstance(manifest["version"], str)
            or not re.fullmatch(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)", manifest["version"])
            or not isinstance(manifest["files"], dict) or set(manifest["files"]) != names - {MANIFEST}
            or any(not isinstance(value, str) or not HEX.fullmatch(value) for value in manifest["files"].values())):
        raise ValueError("Invalid release manifest or member inventory")
    release = json.loads(archive.read("playbook/release.json"), object_pairs_hook=unique_object)
    workspace = json.loads(archive.read("playbook/workspace-format.json"), object_pairs_hook=unique_object)
    check_descriptors(manifest["version"], release, workspace)
    return manifest


def unpack(path, destination):
    with zipfile.ZipFile(path) as archive:
        manifest = manifest_for(archive)
        for name in [MANIFEST, *manifest["files"]]:
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            digest = hashlib.sha256()
            with archive.open(name) as source, target.open("xb") as output:
                for block in iter(lambda: source.read(1024 * 1024), b""):
                    digest.update(block)
                    output.write(block)
                output.flush()
                os.fsync(output.fileno())
            if name == "bin/oryx":
                target.chmod(0o755)
            if name != MANIFEST and digest.hexdigest() != manifest["files"][name]:
                raise ValueError("Release member digest mismatch")
        for directory, _, _ in os.walk(destination, topdown=False):
            sync_directory(directory)
        return manifest


def check_runtime(core):
    """Check installed payload against its local manifest. Admission authenticates the archive."""
    core = local_path(core)
    path = regular(core / MANIFEST)
    if path.stat().st_size > 1024 * 1024:
        raise ValueError("Invalid installed release manifest size")
    manifest = json.loads(path.read_bytes(), object_pairs_hook=unique_object)
    if (not isinstance(manifest, dict) or set(manifest) != {"schema", "version", "files"}
            or type(manifest["schema"]) is not int or manifest["schema"] != 1
            or not isinstance(manifest["version"], str)
            or not re.fullmatch(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)", manifest["version"])):
        raise ValueError("Invalid installed release manifest")
    files = manifest.get("files")
    if not isinstance(files, dict) or not REQUIRED <= set(files) or len(files) > 4095:
        raise ValueError("Incomplete installed Core resource inventory")
    directories = set()
    for name, expected in files.items():
        if not valid_name(name) or not isinstance(expected, str) or not HEX.fullmatch(expected):
            raise ValueError("Invalid installed resource name or digest")
        directories.update(str(parent) for parent in PurePosixPath(name).parents if str(parent) != ".")
    remaining = set(files) | {MANIFEST}
    pending = [core]
    while pending:
        with os.scandir(pending.pop()) as entries:
            for entry in entries:
                resource = Path(entry.path)
                name = resource.relative_to(core).as_posix()
                if name in directories and entry.is_dir(follow_symlinks=False):
                    pending.append(resource)
                    continue
                if name not in remaining or not entry.is_file(follow_symlinks=False):
                    raise ValueError(f"Unexpected installed resource: {name}")
                info = entry.stat(follow_symlinks=False)
                if info.st_nlink != 1:
                    raise ValueError(f"Redirected installed resource: {name}")
                if info.st_size > MAX_MEMBER:
                    raise ValueError(f"Installed resource exceeds the release size limit: {name}")
                if (name == "bin/oryx" and not info.st_mode & stat.S_IXUSR
                        or name != "bin/oryx" and info.st_mode & 0o111):
                    raise ValueError(f"Installed executable permission differs from release: {name}")
                if name != MANIFEST and file_digest(resource) != files[name]:
                    raise ValueError(f"Installed resource differs from release: {name}")
                remaining.remove(name)
    if remaining:
        raise ValueError(f"Missing installed resource: {min(remaining)}")
    check_descriptors(manifest.get("version"),
                      json.loads((core / "playbook/release.json").read_bytes(), object_pairs_hook=unique_object),
                      json.loads((core / "playbook/workspace-format.json").read_bytes(), object_pairs_hook=unique_object))
    return manifest


def read_state(store):
    path = store / STATE
    if not path.exists() and not path.is_symlink():
        return {"active": None, "previous": None}
    state = json.loads(regular(path).read_bytes(), object_pairs_hook=unique_object)
    if (not isinstance(state, dict) or set(state) != {"active", "previous"}
            or state["active"] is None):
        raise ValueError("Invalid Core activation state")
    for item in state.values():
        if item is not None and (not isinstance(item, dict) or set(item) != {"generation", "digest", "version"}
                or not isinstance(item["generation"], str) or not re.fullmatch(r"[0-9a-f]{32}", item["generation"])
                or not isinstance(item["digest"], str) or not HEX.fullmatch(item["digest"])
                or not isinstance(item["version"], str)):
            raise ValueError("Invalid Core generation")
    return state


def store_root(path):
    store = local_path(path)
    selected = os.environ.get("ORYX_WORKSPACE")
    if selected:
        workspace = Path(selected).resolve()
        if workspace == store or workspace in store.parents or store in workspace.parents:
            raise ValueError("Select a Core store separate from the selected Workspace")
    for parent in (store, *store.parents):
        git = parent / ".git"
        if (parent.name == ".git" or git.is_symlink() or git.is_file() or (git / "HEAD").exists()
                or (parent / ".oryx/workspace.json").exists()
                or ((parent / "HEAD").is_file() and (parent / "objects").is_dir() and (parent / "refs").is_dir())):
            raise ValueError("Select a Core store outside all Workspaces and Git repositories")
    if store.exists():
        check_private_dir(store)
    return store


def check_private_dir(path):
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError("Use a dedicated, owner-private Core installation directory")


@contextmanager
def locked(store):
    store.mkdir(mode=0o700, exist_ok=True)
    check_private_dir(store)
    if any(p.name not in {".install.lock", STATE, "generations"} for p in store.iterdir()):
        raise ValueError("Core installation directory contains unrelated files")
    descriptor = os.open(store / ".install.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "rb+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        generations = store / "generations"
        generations.mkdir(mode=0o700, exist_ok=True)
        check_private_dir(generations)
        yield generations


def activate(store, active, previous):
    """Readers observe the entire old or new history by one same-directory rename."""
    content = json.dumps({"active": active, "previous": previous}, sort_keys=True).encode() + b"\n"
    with tempfile.NamedTemporaryFile(dir=store / "generations", delete=False) as staged:
        name = Path(staged.name)
        try:
            staged.write(content)
            staged.flush()
            os.fsync(staged.fileno())
            os.replace(name, store / STATE)
            sync_directory(store)
        finally:
            name.unlink(missing_ok=True)


def install_locked(store, generations, archive, signature, key, previous, expected=None):
    identifier = uuid4().hex
    with tempfile.TemporaryDirectory(prefix=".prepare-", dir=generations) as temporary:
        prepared = Path(temporary)
        bundle = prepared / "generation"
        bundle.mkdir(mode=0o700)
        signed = bundle / "archive.zip"
        detached = bundle / "archive.sig"
        copy_limited(archive, signed, MAX_ARCHIVE)
        copy_limited(signature, detached, 64 * 1024)
        anchor = prepared / "publisher.pem"
        copy_limited(key, anchor, 64 * 1024)
        verify_signature(signed, detached, anchor)
        digest = file_digest(signed)
        if expected and expected["digest"] != digest:
            raise ValueError("Recovery archive differs from recorded generation")
        core = bundle / "core"
        core.mkdir(mode=0o700)
        manifest = unpack(signed, core)
        if previous and previous["digest"] == digest:
            # A retry reuses healthy bytes. A new generation repairs local drift without touching a Workspace.
            existing = local_path(generations / previous["generation"] / "core")
            try:
                cached_archive = regular(existing.parent / "archive.zip")
                cached_signature = regular(existing.parent / "archive.sig")
                if (cached_archive.stat().st_size == signed.stat().st_size
                        and cached_signature.stat().st_size == detached.stat().st_size
                        and cached_signature.read_bytes() == detached.read_bytes()
                        and file_digest(cached_archive) == digest
                        and regular(existing / MANIFEST).read_bytes() == (core / MANIFEST).read_bytes()
                        and check_runtime(existing) == manifest):
                    return existing
            except (OSError, ValueError):
                pass
            previous = read_state(store)["previous"]
        active = {"generation": identifier, "digest": digest, "version": manifest["version"]}
        sync_directory(bundle)
        bundle.rename(generations / identifier)
        sync_directory(generations)
        activate(store, active, previous)
    return generations / identifier / "core"


def trusted_key(path, store):
    key = regular(local_path(path))
    if key == store or store in key.parents:
        raise ValueError("Provision the trusted publisher public key separately from the Core store")
    return key


def install(store, archive, signature, public_key):
    store = store_root(store)
    key = trusted_key(public_key, store)
    with locked(store) as generations:
        previous = read_state(store)["active"]
        return install_locked(store, generations, Path(archive), Path(signature), key, previous)


def rollback(store, public_key):
    store = store_root(store)
    key = trusted_key(public_key, store)
    with locked(store) as generations:
        state = read_state(store)
        previous = state["previous"]
        if previous is None:
            raise ValueError("No previous verified Core release")
        source = local_path(generations / previous["generation"])
        check_private_dir(source)
        return install_locked(store, generations, source / "archive.zip", source / "archive.sig",
                              key, state["active"], expected=previous)


def current(store):
    store = store_root(store)
    active = read_state(store)["active"]
    if active is None:
        raise ValueError("No active Core release")
    core = local_path(store / "generations" / active["generation"] / "core")
    check_private_dir(core)
    return core


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("install", "rollback", "current"):
        sub = commands.add_parser(name)
        sub.add_argument("--store", type=Path, required=True)
        if name != "current":
            sub.add_argument("--public-key", type=Path, required=True)
        if name == "install":
            sub.add_argument("--archive", type=Path, required=True)
            sub.add_argument("--signature", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "install":
            result = install(args.store, args.archive, args.signature, args.public_key)
        elif args.command == "rollback":
            result = rollback(args.store, args.public_key)
        else:
            result = current(args.store)
    except (OSError, ValueError, zipfile.BadZipFile, subprocess.SubprocessError) as exc:
        parser.exit(1, f"Oryx Core: {exc}\n")
    print(result)


if __name__ == "__main__":
    main()
