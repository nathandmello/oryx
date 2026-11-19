"""Own the private workspace boundary, settings, and first-run setup."""

import json
from pathlib import Path
import re
import subprocess
from urllib.parse import urlsplit

import records


def git(path, *args):
    result = subprocess.run(["git", "-C", str(path), *args], capture_output=True, text=True)
    if result.returncode:
        raise ValueError(result.stderr.strip() or "Git command failed")
    return result.stdout.strip()


def repo(root, role):
    if role not in {"system", "workspace"}:
        raise ValueError("Choose system or workspace")
    root = root.resolve()
    path = root if role == "system" else root / "workspace"
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


def release(root):
    path = root / "playbook/release.json"
    if path.resolve() != path:
        raise ValueError("System release metadata must be a regular file inside PM Hub")
    return validate_release(json.loads(path.read_text(encoding="utf-8")))


def settings(root, compatible=True):
    path = root / "workspace/settings.json"
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
            raise ValueError("Keep remote credentials in the credential manager, outside workspace settings")
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
    path = root / "workspace"
    if path.exists() or path.is_symlink():
        raise ValueError("workspace/ already exists; preserve it and inspect its repository before setup")
    if not git(root, "check-ignore", "workspace/"):
        raise ValueError("Add /workspace/ to the system .gitignore before setup")
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
    return path
