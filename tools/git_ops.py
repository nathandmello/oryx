"""Route a small set of Git operations to one explicit repository."""

import json
from pathlib import Path
import re
import subprocess
from urllib.parse import urlsplit

import workspace


def identity(url):
    """Compare SSH and HTTPS forms of a GitHub repository without credentials."""
    scp = re.fullmatch(r"[^/@]+@([^:]+):(.+)", url)
    if scp:
        host, path = scp.groups()
    else:
        parsed = urlsplit(url)
        host, path = parsed.hostname, parsed.path
    if host:
        return host.casefold() + "/" + path.strip("/").removesuffix(".git").casefold()
    if not scp and parsed.scheme == "file":
        return str(Path(parsed.path).resolve())
    return str(Path(url).resolve())


def config(path, key):
    result = subprocess.run(["git", "-C", str(path), "config", "--get", key], capture_output=True, text=True)
    if result.returncode not in (0, 1):
        raise ValueError("Cannot read repository configuration")
    return result.stdout.strip()


def destination(root, role, settings):
    path = workspace.repo(root, role)
    expected = settings["remotes"][role]
    if not expected:
        raise ValueError(f"{role}: confirm the repository URL, then set workspace/settings.json remotes.{role}")
    urls = []
    for options in (("--all",), ("--push", "--all")):
        values = workspace.git(path, "remote", "get-url", *options, "origin").splitlines()
        if len(values) != 1 or identity(values[0]) != identity(expected):
            raise ValueError(f"{role}: origin differs from its confirmed destination; inspect fetch and push URLs")
        urls.extend(values)
    other = "workspace" if role == "system" else "system"
    other_path = workspace.repo(root, other)
    actual_other = subprocess.run(["git", "-C", str(other_path), "remote", "get-url", "--all", "origin"],
                                  capture_output=True, text=True)
    other_urls = actual_other.stdout.splitlines() + [settings["remotes"][other] or ""]
    if any(identity(url) == identity(other_url) for url in urls for other_url in other_urls if other_url):
        raise ValueError("System and workspace must use different remote repositories")
    if config(path, "remote.origin.mirror").casefold() == "true":
        raise ValueError("Mirror remotes are outside the supported workflow")
    return path


def run(root, role, operation):
    path = workspace.repo(root, role)
    if operation == "status":
        return f"{role}: {path}\n" + workspace.git(path, "status", "--short", "--branch")
    if operation not in {"fetch", "pull", "push"}:
        raise ValueError("Use status, fetch, pull, or push")
    settings = workspace.settings(root, compatible=False)
    path = destination(root, role, settings)
    if operation == "fetch":
        workspace.git(path, "fetch", "origin")
        return f"Fetched {role} origin. Working files are unchanged."
    if workspace.git(path, "status", "--porcelain"):
        raise ValueError(f"{role}: commit or preserve local changes before {operation}")
    branch = workspace.git(path, "symbolic-ref", "--quiet", "--short", "HEAD")
    workspace.git(path, "rev-parse", "--verify", "HEAD")
    tracking = config(path, f"branch.{branch}.remote")
    tracked_branch = config(path, f"branch.{branch}.merge")
    if tracking and (tracking != "origin" or tracked_branch != f"refs/heads/{branch}"):
        raise ValueError(f"{role}: branch tracks another destination; inspect it before synchronisation")
    if operation == "push":
        workspace.git(path, "-c", "push.followTags=false", "push", "--set-upstream", "origin",
                      f"HEAD:refs/heads/{branch}")
        return f"Pushed {role} branch {branch} to its confirmed origin."
    workspace.git(path, "fetch", "origin", f"refs/heads/{branch}")
    metadata_path = "playbook/release.json" if role == "system" else "settings.json"
    incoming = json.loads(workspace.git(path, "show", f"FETCH_HEAD:{metadata_path}"))
    if role == "system":
        workspace.validate_release(incoming)
    if not isinstance(incoming, dict):
        raise ValueError("Incoming workspace settings must be a JSON object")
    if incoming.get("workspace_format") != settings["workspace_format"]:
        raise ValueError("Incoming workspace format differs; review a migration before updating")
    if role == "workspace" and (incoming.get("system_version") != settings["system_version"]
                                or incoming.get("remotes") != settings["remotes"]):
        raise ValueError("Incoming workspace changes its system version or destinations; review them before updating")
    workspace.git(path, "merge", "--ff-only", "FETCH_HEAD")
    if role == "system":
        settings["system_version"] = workspace.release(root)["system_version"]
        target = root / "workspace/settings.json"
        target.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    return f"Updated {role} branch {branch}. Run the checks before further work."
