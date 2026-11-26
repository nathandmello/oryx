"""Prepare a private workspace before starting a protected session."""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import git_ops
import storage
import workspace


def github(*args):
    return subprocess.check_output(
        ["gh", *args], text=True, env=dict(os.environ, GH_HOST="github.com")
    ).strip()


def origin_urls(path):
    urls = []
    for options in (("--all",), ("--push", "--all")):
        result = subprocess.run(
            ["git", "-C", str(path), "remote", "get-url", *options, "origin"],
            capture_output=True, text=True,
        )
        if result.returncode == 2:
            continue
        result.check_returncode()
        urls.extend(result.stdout.splitlines())
    return urls


def confirm(question):
    return input(question + " [y/N] ").strip().lower() in {"y", "yes"}


def github_target(root, private, create):
    name = input("GitHub repository (owner/name): ").strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9_.-]+", name):
        raise ValueError("Enter a GitHub repository as owner/name")
    url = f"https://github.com/{name}.git"
    settings = workspace.settings(root, compatible=False) if private else None
    system_urls = origin_urls(root)
    existing = origin_urls(private) if private else []
    if settings:
        system_urls.append(settings["remotes"]["system"])
        existing.append(settings["remotes"]["workspace"])
    if any(git_ops.identity(item) == git_ops.identity(url) for item in system_urls if item):
        raise ValueError("Choose a private repository separate from the shared Oryx repository")
    if any(git_ops.identity(item) != git_ops.identity(url) for item in existing if item):
        raise ValueError("The workspace already has a different destination. Review it before reconnecting.")
    if not shutil.which("gh"):
        raise ValueError("Install GitHub CLI (gh) to connect GitHub, or continue locally")
    auth = subprocess.run(["gh", "auth", "status", "--hostname", "github.com"])
    if auth.returncode:
        if not confirm("Sign in to GitHub now?"):
            return None
        subprocess.run(["gh", "auth", "login", "--hostname", "github.com", "--web"], check=True)
    if create:
        if not confirm(f"Create private repository {name} on GitHub?"):
            return None
        github("repo", "create", name, "--private")
    metadata = json.loads(github(
        "repo", "view", url, "--json", "nameWithOwner,visibility,viewerPermission,isEmpty"
    ))
    if (metadata["nameWithOwner"].casefold() != name.casefold()
            or metadata["visibility"] != "PRIVATE"
            or metadata["viewerPermission"] not in {"WRITE", "MAINTAIN", "ADMIN"}):
        raise ValueError("Choose a private GitHub repository you can write to")
    return url, metadata["isEmpty"]


CREDENTIAL = "credential.https://github.com.helper"


def restore(root, url):
    workspace.require_studio_boundary(root)
    target = workspace.private_root(root)
    staging = root / ".state"
    if staging.is_symlink():
        raise ValueError("Workspace restore needs a local staging directory")
    workspace.git(root, "check-ignore", "--", ".state/first-run")
    staging.mkdir(mode=0o700, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=staging) as temporary:
        checkout = Path(temporary) / "restore"
        subprocess.run(
            ["git", "-c", CREDENTIAL + "=!gh auth git-credential", "clone", "--", url, str(checkout)],
            check=True,
        )
        settings_file = checkout / "settings.json"
        if settings_file.is_symlink() or not settings_file.is_file():
            raise ValueError("The selected repository does not contain Oryx workspace settings")
        metadata = workspace.read_settings(settings_file)
        saved = metadata["remotes"]["workspace"]
        if saved and git_ops.identity(saved) != git_ops.identity(url):
            raise ValueError("The remote workspace records a different sync destination")
        storage.rename_exclusive(checkout, target)
    return target


def connect(root, private, url):
    settings = workspace.settings(root, compatible=False)
    existing = origin_urls(private)
    if existing and (len(existing) != 2 or any(
        git_ops.identity(item) != git_ops.identity(url) for item in existing
    )):
        raise ValueError("Review the workspace origin before connecting GitHub")
    saved = settings["remotes"]["workspace"]
    if saved and git_ops.identity(saved) != git_ops.identity(url):
        raise ValueError("The workspace records a different sync destination")
    if not existing:
        workspace.git(private, "remote", "add", "origin", url)
    if all(item.startswith("https://github.com/") for item in origin_urls(private)):
        workspace.git(private, "config", "--local", "--replace-all", CREDENTIAL, "!gh auth git-credential")
    settings["remotes"]["workspace"] = saved or url
    git_ops.destination(root, "workspace", settings)
    workspace.git(private, "fetch", "origin")
    if not saved:
        save_settings(private, settings)
    print(f"Connected your workspace to {url}.", flush=True)


def save_settings(private, settings):
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=private, delete=False) as output:
        pending = output.name
        json.dump(settings, output, indent=2)
        output.write("\n")
    try:
        os.replace(pending, private / "settings.json")
    finally:
        if os.path.exists(pending):
            os.unlink(pending)


def prepare(root, *, explicit=False):
    path = workspace.private_root(root)
    exists = path.exists() or path.is_symlink()
    if exists and not explicit:
        return
    if not sys.stdin.isatty():
        raise ValueError("Run pm.py agent in a terminal for Step 0, or initialise the workspace first")
    workspace.repo(root, "system")
    if not exists:
        workspace.require_studio_boundary(root)
    private = workspace.repo(root, "workspace") if exists else None
    print("Step 0 — Set up your workspace")
    print("Sign in to your client if prompted. Review and trust the Oryx project hooks when prompted.")
    choice = input("Workspace storage: [L]ocal, [C]onnect private GitHub, [N]ew private GitHub: ").strip().lower()
    if choice not in {"", "l", "c", "n"}:
        raise ValueError("Choose local, connect, or new")
    target = github_target(root, private, choice == "n") if choice in {"c", "n"} else None
    if choice in {"c", "n"} and target is None:
        print("Continuing with local workspace setup.")
    if target and not target[1]:
        if private:
            settings = workspace.settings(root, compatible=False)
            if not settings["remotes"]["workspace"] or not origin_urls(private):
                raise ValueError("This repository contains history. Restore it in a separate checkout before reconciling local work.")
        else:
            private = restore(root, target[0])
    fresh = private is None
    if fresh:
        owner = input("Workspace owner: ").strip()
        if not owner or "|" in owner:
            raise ValueError("Enter an owner name without a table separator")
        delivery = input("Delivery tool (optional): ").strip() or "Delivery workspace"
        private = workspace.initialise(root, owner, delivery)
    if target:
        connect(root, private, target[0])
        if target[1]:
            if fresh:
                first_sync(root, private, target[0])
            else:
                print("Review your local Git history before making the first push.")
    print("Workspace setup complete. Your first request starts or resumes onboarding.", flush=True)


def first_sync(root, private, url):
    listing = subprocess.check_output(
        ["git", "-C", str(private), "ls-files", "-z", "--others", "--exclude-standard"]
    )
    files = os.fsdecode(listing).split("\0")[:-1]
    print("Files available for the first commit:")
    for name in files:
        print(f"  {name!r}")
    if not confirm(f"Commit these files and push to {url}?"):
        return
    try:
        workspace.git(private, "var", "GIT_AUTHOR_IDENT")
        workspace.git(private, "var", "GIT_COMMITTER_IDENT")
    except ValueError:
        if not confirm("Set a Git author name and email for this workspace?"):
            return
        name = input("Git author name: ").strip()
        email = input("Git author email: ").strip()
        if not name or not email:
            raise ValueError("Enter a Git author name and email before committing")
        workspace.git(private, "config", "--local", "user.name", name)
        workspace.git(private, "config", "--local", "user.email", email)
    workspace.git(private, "--literal-pathspecs", "add", "--", *files)
    workspace.git(private, "commit", "-m", "Initialize Oryx workspace")
    subprocess.run(
        [sys.executable, str(root / "tools/pm.py"), "git", "workspace", "push"],
        cwd=root, check=True,
    )
