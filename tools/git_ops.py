"""Route a small set of Git operations to one explicit repository."""

import json
import os
from pathlib import Path
import re
import subprocess
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit

import workspace
import upgrades
import conversion
import storage
import snapshots


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
        raise ValueError(f"{role}: confirm the repository URL, then set private/settings.json remotes.{role}")
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


HANDOFF = "pm-hub-private-pull.json"
KEEP_CHANGES = ("workspace: preserve local changes before pull. Keep this checkout intact, clone the confirmed private "
                "remote into a separate directory, and compare the working files and staged diff before reconciling them.")


def index_matches(path, revision):
    result = subprocess.run(["git", "-C", str(path), "diff", "--no-ext-diff", "--cached", "--ita-visible-in-index",
                             "--quiet", revision, "--"], capture_output=True)
    return result.returncode == 0


def matches_private_tree(path, head, incoming):
    """Compare with Git's checkout rules, without staging or checking out a working file."""
    # A deletion must really be absent, even when local ignore rules would hide it from the incoming index.
    deleted = subprocess.run(["git", "-C", str(path), "diff", "--no-renames", "--name-only", "--diff-filter=D", "-z",
                              head, incoming, "--"], capture_output=True, check=True).stdout
    if any(os.path.lexists(path / os.fsdecode(name)) for name in deleted.split(b"\0") if name):
        return False
    added = subprocess.run(["git", "-C", str(path), "diff", "--no-renames", "--name-only", "--diff-filter=AT", "-z",
                            head, incoming, "--"], capture_output=True, check=True).stdout
    if added:
        ignored = subprocess.run(["git", "-C", str(path), "check-ignore", "--no-index", "-z", "--stdin"],
                                 input=added, capture_output=True)
        if ignored.returncode != 1:
            return False
    with TemporaryDirectory(dir=path / ".git") as directory:
        env = dict(os.environ, GIT_INDEX_FILE=str(Path(directory) / "index"))
        def git(*args):
            return subprocess.run(["git", "-c", "core.sparseCheckout=false", "-C", str(path), *args],
                                  env=env, capture_output=True, check=True).stdout
        git("read-tree", incoming)
        # The temporary index describes the fetched commit. Also check unrelated untracked files.
        return (not git("diff", "--no-ext-diff", "--no-textconv", "--ignore-submodules=none", "--name-only", "-z", incoming, "--")
                and not git("ls-files", "--others", "--exclude-standard", "-z"))


def adopt_private_migration(path, branch, incoming, settings):
    """Advance a second migrated installation without ever writing its working files."""
    with storage.writer_lock(path):
        journal = path / ".git" / HANDOFF
        if journal.resolve() != journal or (journal.exists() and not journal.is_file()):
            raise ValueError("Inspect the private migration pull receipt")
        saved = journal.read_text(encoding="utf-8") if journal.exists() else None
        head = workspace.git(path, "rev-parse", "HEAD")
        ref = "refs/heads/" + branch
        if workspace.git(path, "symbolic-ref", "HEAD") != ref:
            raise ValueError("The private branch changed during pull")
        receipt = json.loads(saved) if saved is not None else {"branch": ref, "before": head, "after": incoming}
        if (not isinstance(receipt, dict) or receipt.get("branch") != ref or
                any(not isinstance(receipt.get(k), str) or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", receipt[k])
                    for k in ("before", "after"))):
            raise ValueError("Inspect the private migration pull receipt before retrying")
        old, target = receipt["before"], receipt["after"]
        if saved is not None and head == target:
            journal.unlink()  # The ref advanced before the previous process could remove its receipt.
            return
        if (old != head or target == head or settings["workspace_format"] != 2 or
                json.loads(workspace.git(path, "show", head + ":settings.json")).get("workspace_format") != 1):
            raise ValueError(KEEP_CHANGES)
        for ancestor, descendant in ((old, target), (target, incoming)):
            if subprocess.run(["git", "-C", str(path), "merge-base", "--is-ancestor", ancestor, descendant],
                              capture_output=True).returncode:
                raise ValueError(KEEP_CHANGES)
        if json.loads(workspace.git(path, "show", target + ":settings.json")) != settings:
            raise ValueError(KEEP_CHANGES)
        resume = saved is not None and index_matches(path, target)
        if (not resume and not index_matches(path, head)) or not matches_private_tree(path, head, target):
            raise ValueError(KEEP_CHANGES)
        if saved is None:
            storage.replace_text(journal, None, json.dumps(receipt) + "\n")
        if not resume:
            # Git locks the actual index and refuses conflicting staged entries. Without -u, it never checks out files.
            workspace.git(path, "read-tree", "-i", "-m", head, target)
        if not index_matches(path, target) or workspace.git(path, "symbolic-ref", "HEAD") != ref:
            raise ValueError(KEEP_CHANGES)
        # A competing ref change fails this compare-and-swap. A later retry can finish the staged handoff.
        workspace.git(path, "update-ref", "-m", "pull: adopt identical private layout migration", ref, target, head)
        journal.unlink()


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
    dirty = bool(workspace.git(path, "status", "--porcelain"))
    handoff = role == "workspace" and operation == "pull" and (dirty or (path / ".git" / HANDOFF).exists())
    if dirty and not handoff:
        raise ValueError(f"{role}: commit or preserve local changes before {operation}")
    branch = workspace.git(path, "symbolic-ref", "--quiet", "--short", "HEAD")
    workspace.git(path, "rev-parse", "--verify", "HEAD")
    tracking = config(path, f"branch.{branch}.remote")
    tracked_branch = config(path, f"branch.{branch}.merge")
    if tracking and (tracking != "origin" or tracked_branch != f"refs/heads/{branch}"):
        raise ValueError(f"{role}: branch tracks another destination; inspect it before synchronisation")
    if operation == "push":
        if role == "workspace":
            committed = subprocess.run(["git", "-C", str(path), "show", f"HEAD:{upgrades.LEDGER}"], capture_output=True)
            local = upgrades.read_state(path)[1]
            published = {} if committed.returncode else json.loads(committed.stdout)
            if (upgrades.TRANSACTIONS in published or upgrades.TRANSACTIONS in local) and published != local:
                raise ValueError("Save the current private filing ledger before sharing it")
            for identifier, expected in published.get(upgrades.TRANSACTIONS, {}).items():
                rel = conversion.archive_path(path, identifier).relative_to(path).as_posix()
                blob = subprocess.run(["git", "-C", str(path), "cat-file", "blob", f"HEAD:{rel}"], capture_output=True)
                if blob.returncode or conversion.digest(blob.stdout) != expected:
                    raise ValueError(f"Save the verified recovery archive in the private commit: {rel}")
        workspace.git(path, "-c", "push.followTags=false", "push", "--set-upstream", "origin",
                      f"HEAD:refs/heads/{branch}")
        return f"Pushed {role} branch {branch} to its confirmed origin."
    workspace.git(path, "fetch", "origin", f"refs/heads/{branch}")
    fetched = workspace.git(path, "rev-parse", "FETCH_HEAD^{commit}")
    metadata_path = "playbook/release.json" if role == "system" else "settings.json"
    incoming = json.loads(workspace.git(path, "show", f"{fetched}:{metadata_path}"))
    if role == "system":
        for revision in ("HEAD", "FETCH_HEAD"):
            if workspace.git(path, "ls-tree", revision, "--", "workspace", "private"):
                raise ValueError("Shared Git history tracks the private workspace; stopped before merging")
        descriptor = None
        if workspace.git(path, "ls-tree", "FETCH_HEAD", "--", workspace.FORMAT_FILE):
            descriptor = json.loads(workspace.git(path, "show", "FETCH_HEAD:" + workspace.FORMAT_FILE))
        incoming = workspace.installed_release(incoming, descriptor)
        if tuple(map(int, incoming["system_version"].split("."))) < tuple(map(int, settings["system_version"].split("."))):
            raise ValueError("Incoming Hub predates this private workspace; use the documented recovery procedure")
    if not isinstance(incoming, dict):
        raise ValueError("Incoming workspace settings must be a JSON object")
    supported_upgrade = (role == "system" and settings["workspace_format"] == 1
                         and incoming.get("workspace_format") == 2 and incoming["system_version"] == "0.3.0")
    if incoming.get("workspace_format") != settings["workspace_format"] and not supported_upgrade:
        raise ValueError("Incoming workspace format differs; review a migration before updating")
    if role == "workspace" and (incoming.get("system_version") != settings["system_version"]
                                or incoming.get("remotes") != settings["remotes"]):
        raise ValueError("Incoming workspace changes its system version or destinations; review them before updating")
    if role == "system":
        private = workspace.private_root(root)
        with storage.writer_lock(private):
            target = private / "settings.json"
            if target.resolve() != target:
                raise ValueError("Use regular private settings inside PM Hub")
            original = target.read_text(encoding="utf-8")
            latest = workspace.settings(root, compatible=False)
            if latest["workspace_format"] != settings["workspace_format"] or latest["system_version"] != settings["system_version"]:
                raise ValueError("Workspace version changed during the update; recheck alignment")
            if latest["system_version"] != incoming["system_version"]:
                snapshots.ensure(root, incoming["system_version"])
            workspace.git(path, "merge", "--ff-only", "--no-overwrite-ignore", "FETCH_HEAD")
            if not supported_upgrade and latest["system_version"] != incoming["system_version"]:
                latest["system_version"] = incoming["system_version"]
                storage.replace_text(target, original, json.dumps(latest, indent=2) + "\n")
    else:
        if handoff:
            adopt_private_migration(path, branch, fetched, settings)
        if workspace.git(path, "rev-parse", "HEAD") != fetched:
            if handoff and workspace.git(path, "status", "--porcelain"):
                raise ValueError(KEEP_CHANGES)
            workspace.git(path, "merge", "--ff-only", "--no-overwrite-ignore", fetched)
    return f"Updated {role} branch {branch}. Run the checks before further work."
