"""Record and selectively reverse the version field changed by a Core update."""
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile

from oryx.workspace.location import workspace_id
from . import archive


class ConcurrentEdit(ValueError):
    """The PM's displaced settings need explicit reconciliation."""


FIELD = re.compile(rb'("system_version"\s*:\s*)"([0-9]+\.[0-9]+\.[0-9]+)"')


def git(folder, *arguments, data=None):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_AUTHOR_NAME="Oryx update", GIT_AUTHOR_EMAIL="oryx@localhost",
               GIT_COMMITTER_NAME="Oryx update", GIT_COMMITTER_EMAIL="oryx@localhost")
    result = subprocess.run(["git", "--no-replace-objects", "-C", str(folder), "-c", "core.hooksPath=/dev/null",
                             *arguments], env=env, input=data, capture_output=True, timeout=25)
    if result.returncode:
        raise ValueError("Cannot verify private Workspace update history")
    return result.stdout


def validate(folder, identifier=None):
    if "PM_HUB_PROTECTED_ROOT" in os.environ:
        raise ValueError("Run release changes from the PM terminal")
    folder = archive.local_path(folder)
    marker = archive.regular(archive.local_path(folder / ".oryx/workspace.json"))
    if marker.stat().st_size > 1024:
        raise ValueError("Invalid Workspace identity")
    actual = workspace_id(folder)
    if identifier and actual != identifier:
        raise ValueError("Selected Workspace identity changed")
    metadata = folder / ".git"
    if metadata.resolve() != metadata or not metadata.is_dir():
        raise ValueError("Use the selected personal Git Workspace")
    if Path(os.fsdecode(git(folder, "rev-parse", "--show-toplevel").strip())) != folder:
        raise ValueError("Workspace Git root changed")
    return folder, actual


@contextmanager
def writer(folder):
    path = folder / ".git/pm-hub-writer.lock"
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "rb+") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        yield


def read_settings(folder):
    path = archive.regular(archive.local_path(folder / "settings.json"))
    if path.stat().st_nlink != 1 or path.stat().st_size > 1024 * 1024:
        raise ValueError("Unrecognized Workspace settings file")
    return path, path.read_bytes()


def version_change(raw, previous, desired):
    doc = json.loads(raw, object_pairs_hook=archive.unique_object)
    if (not isinstance(doc, dict) or doc.get("system_version") != previous
            or type(doc.get("workspace_format")) is not int or doc["workspace_format"] != 2):
        raise ValueError("Unsupported Workspace format or Core revision. Keep the original for reconciliation")
    changes = list(FIELD.finditer(raw))
    if len(changes) != 1 or changes[0][2].decode() != previous:
        raise ValueError("Cannot isolate the Workspace version field")
    target = raw[:changes[0].start(2)] + desired.encode() + raw[changes[0].end(2):]
    if json.loads(target, object_pairs_hook=archive.unique_object) != {**doc, "system_version": desired}:
        raise ValueError("Unexpected Workspace change")
    return target


def prepare(folder, incident, previous, desired):
    folder, identifier = validate(folder)
    with writer(folder):
        _, before = read_settings(folder)
        if previous is None:
            previous = desired
        after = version_change(before, previous, desired)
        if before == after:
            return None
        blobs = [git(folder, "hash-object", "-w", "--stdin", data=content).strip() for content in (before, after)]
        lines = b"".join(b"100644 blob " + oid + b"\t" + name + b"\n" for oid, name in zip(blobs, (b"before", b"after")))
        tree = git(folder, "mktree", data=lines).decode().strip()
        commit = git(folder, "commit-tree", tree, "-m", "Oryx version transition " + incident).decode().strip()
        ref = "refs/oryx/updates/" + incident
        git(folder, "update-ref", ref, commit, "0" * len(commit))
        return {"path": str(folder), "id": identifier, "ref": ref, "commit": commit, "from": previous, "to": desired}


def apply(plan, *, reverse=False):
    if plan is None:
        return "unchanged"
    folder, _ = validate(plan["path"], plan["id"])
    ref = plan["ref"]
    if not re.fullmatch(r"refs/oryx/updates/[0-9a-f]{32}", ref):
        raise ValueError("Invalid Workspace update reference")
    with writer(folder):
        if git(folder, "rev-parse", "--verify", ref).decode().strip() != plan["commit"]:
            raise ValueError("Workspace update history changed")
        before = git(folder, "show", ref + ":before")
        after = git(folder, "show", ref + ":after")
        if version_change(before, plan["from"], plan["to"]) != after:
            raise ValueError("Workspace transaction contains unexplained changes")
        path, live = read_settings(folder)
        source, target = (after, before) if reverse else (before, after)
        if live == target:
            return "unchanged"
        if live != source:
            initial, final = (plan["to"], plan["from"]) if reverse else (plan["from"], plan["to"])
            version = json.loads(live, object_pairs_hook=archive.unique_object).get("system_version")
            if version == final:
                return "unchanged"
            target = version_change(live, initial, final)
        mode = stat.S_IMODE(path.stat().st_mode)
        # Keep the actual displaced inode in Git metadata. An editor can
        # replace a path between its last checksum check and our atomic swap,
        # or finish editing through an already-open descriptor after the swap.
        from oryx.workspace.publication import swap
        backup = archive.local_path(folder / ".git/oryx-update-settings" / ref.rsplit("/", 1)[1])
        backup.parent.mkdir(mode=0o700, exist_ok=True)
        archive.check_private_dir(backup.parent)
        backup.mkdir(mode=0o700, exist_ok=True)
        archive.check_private_dir(backup)
        archive.sync_directory(backup.parent.parent)
        archive.sync_directory(backup.parent)
        with tempfile.NamedTemporaryFile(dir=backup, prefix="settings-", delete=False) as stage:
            temp = Path(stage.name)
            os.fchmod(stage.fileno(), mode)
            stage.write(target)
            stage.flush()
            os.fsync(stage.fileno())
            if read_settings(folder)[1] != live:
                raise ValueError("Concurrent Workspace edit needs reconciliation")
            swap(temp, path)
            archive.sync_directory(folder)
            archive.sync_directory(backup)
            # A changed preimage stays available for reconciliation.
            info = temp.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size != len(live):
                raise ConcurrentEdit("Concurrent Workspace settings edit preserved in the update preimages")
            with archive.regular(temp).open("rb") as displaced:
                if displaced.read(len(live) + 1) != live:
                    raise ConcurrentEdit("Concurrent Workspace settings edit preserved in the update preimages")
    return "reverted" if reverse else "updated"
