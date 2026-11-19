"""Own the private workspace boundary, settings, and first-run setup."""

import json
import os
import sys
from pathlib import Path
import re
import subprocess
from urllib.parse import urlsplit

import records
import upgrades
from storage import private_root


def git(path, *args):
    result = subprocess.run(["git", "-C", str(path), *args], capture_output=True, text=True)
    if result.returncode:
        raise ValueError(result.stderr.strip() or "Git command failed")
    return result.stdout.strip()


def repo(root, role):
    if role not in {"system", "workspace"}:
        raise ValueError("Choose system or workspace")
    root = root.resolve()
    path = root if role == "system" else private_root(root)
    if path.is_symlink() or not (path / ".git").is_dir() or (path / ".git").is_symlink():
        raise ValueError(f"{role}: expected its own local Git repository")
    if Path(git(path, "rev-parse", "--show-toplevel")).resolve() != path:
        raise ValueError(f"{role}: Git root does not match the selected repository")
    return path


def validate_release(value):
    if (not isinstance(value, dict) or set(value) != {"system_version", "workspace_format"}
            or not re.fullmatch(r"\d+\.\d+\.\d+", str(value["system_version"]))
            or type(value["workspace_format"]) is not int or value["workspace_format"] < 1):
        raise ValueError("Invalid system release metadata")
    return value


FORMAT_FILE = "playbook/workspace-format.json"


def installed_release(wire, descriptor):
    """Old updaters read the wire format before they can fetch migration code."""
    validate_release(wire)
    if descriptor is None:
        return wire
    if (not isinstance(descriptor, dict) or set(descriptor) != {"workspace_format", "migrate_from"}
            or type(descriptor["workspace_format"]) is not int or descriptor["workspace_format"] < 2
            or not isinstance(descriptor["migrate_from"], list)
            or not all(type(v) is int and 0 < v < descriptor["workspace_format"] for v in descriptor["migrate_from"])
            or wire["workspace_format"] not in descriptor["migrate_from"]):
        raise ValueError("Invalid private workspace format metadata")
    return dict(wire, workspace_format=descriptor["workspace_format"])


def version(release):
    return tuple(map(int, release["system_version"].split(".")))


def supports_update(settings, incoming):
    previous = version(settings)
    if incoming["workspace_format"] != 2 or version(incoming) < max((0, 3, 0), previous):
        return False
    if settings["workspace_format"] == 2:
        return previous >= (0, 3, 0)
    # The two released wrappers stamp the fetched 0.3.x version before the new migrator runs.
    return settings["workspace_format"] == 1 and (previous in {(0, 1, 0), (0, 2, 0)} or previous[:2] == (0, 3))


def check_relocation(root, previous):
    """Check fixed worktree bindings and the outer Git boundary before any conversion."""
    if previous != root / "workspace" or private_root(root) != previous or previous.resolve() != previous:
        raise ValueError("The private repository location changed. Inspect both directories")
    if git(root, "ls-files", "--", "private", "workspace"):
        raise ValueError("Remove private data from the shared Git index before moving either repository")
    if not git(root, "check-ignore", "--no-index", "private/"):
        raise ValueError("The system must ignore private/ before moving the private repository")
    if (previous / ".git/worktrees").exists() or "core.worktree=" in git(previous, "config", "--local", "--list").lower():
        raise ValueError("Resolve private Git worktree bindings before moving the repository")
    if os.name != "nt" and not (sys.platform.startswith("linux") or sys.platform == "darwin"):
        raise ValueError("This platform needs a supported exclusive directory rename")


def relocate_private(root, previous):
    """Move the whole repository without replacing an existing path or rebuilding Git history."""
    check_relocation(root, previous)
    target = root / "private"
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
        raise ValueError("This filesystem needs an exclusive directory rename. Preserve both paths for review")
    if result:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code), str(target))


def release(root):
    path = root / "playbook/release.json"
    if path.resolve() != path:
        raise ValueError("System release metadata must be a regular file inside PM Hub")
    descriptor = root / FORMAT_FILE
    if descriptor.resolve() != descriptor:
        raise ValueError("Use regular private format metadata")
    return installed_release(json.loads(path.read_text(encoding="utf-8")),
                             json.loads(descriptor.read_text(encoding="utf-8")))


def settings(root, compatible=True):
    path = private_root(root) / "settings.json"
    if path.resolve() != path or not path.is_file():
        raise ValueError("Run python3 tools/pm.py init-workspace before PM work")
    value = json.loads(path.read_text(encoding="utf-8"))
    expected = {"owner", "delivery_system", "system_version", "workspace_format", "remotes"}
    if (not isinstance(value, dict) or set(value) != expected
            or not isinstance(value["owner"], str)
            or not isinstance(value["delivery_system"], str)
            or not isinstance(value["remotes"], dict)
            or set(value["remotes"]) != {"system", "workspace"}
            or any(url is not None and (not isinstance(url, str) or not url.strip())
                   for url in value["remotes"].values())):
        raise ValueError("Invalid workspace settings; use the documented settings fields")
    if any(char in value["owner"] for char in "\n\r|"):
        raise ValueError("Workspace owner must be a single line without table separators")
    for url in value["remotes"].values():
        parsed = urlsplit(url or "")
        if parsed.password or (parsed.scheme in {"http", "https"} and parsed.username):
            raise ValueError("Keep remote credentials in the credential manager, outside private settings")
    validate_release({name: value[name] for name in ("system_version", "workspace_format")})
    current = release(root)
    if compatible and value["workspace_format"] != current["workspace_format"]:
        raise ValueError("Workspace format is incompatible; use the release's migration instructions")
    if compatible and value["system_version"] != current["system_version"]:
        raise ValueError("Workspace system_version differs; review the release and record the accepted version")
    return value


def initialise(root, owner="", delivery_system="Delivery workspace"):
    root = root.resolve()
    repo(root, "system")
    path = private_root(root)
    if path.exists() or path.is_symlink():
        raise ValueError("The private directory already exists; preserve it and inspect its repository before setup")
    if not git(root, "check-ignore", "private/"):
        raise ValueError("Add /private/ to the system .gitignore before setup")
    path.mkdir()
    git(path, "init", "--initial-branch=main")
    metadata = dict(release(root), owner=owner, delivery_system=delivery_system,
                    remotes={"system": None, "workspace": None})
    (path / "settings.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    seed = root / "tools/workspace-seed"
    sources = sorted(seed.rglob("*"))
    copies = {source.resolve(): path / source.relative_to(seed)
              for source in sources if source.is_file() and not source.is_symlink()}
    for source in sources:
        if source.is_symlink():
            raise ValueError("Workspace seeds must use regular files")
        if not source.is_file():
            continue
        target = path / source.relative_to(seed)
        target.parent.mkdir(parents=True, exist_ok=True)
        text = records.retarget_links(source.read_text(encoding="utf-8"), source, target, root, copies)
        with target.open("x", encoding="utf-8") as output:
            output.write(text)
    upgrades.fresh(path)
    import layout_upgrade
    layout_upgrade.mark_fresh(path)
    return path
