"""Start a local PM agent with core protected for the client and its children."""

import json
import os
import shlex
import shutil
import subprocess
import sys

import first_run
from initiative_store import APPROVAL_HOME
import session_journal
import workspace


def launch(root, client, *, context_statusline=False, setup=False):
    if context_statusline and client != "claude":
        raise ValueError("The optional native status line requires Claude Code")
    binary = shutil.which(client)
    if not binary:
        raise ValueError(f"Install {client} before starting a protected session")
    if sys.platform != "darwin" and not sys.platform.startswith("linux"):
        raise ValueError("Use Linux, WSL2, or macOS for protected PM sessions")
    sandbox = "sandbox-exec" if sys.platform == "darwin" else "bwrap"
    if not shutil.which(sandbox):
        raise ValueError(f"Install {sandbox} to run a protected PM session")
    try:
        first_run.prepare(root, explicit=setup)
    except EOFError as exc:
        raise ValueError("Workspace setup ended. Run the launcher again to resume.") from exc
    # Upgrade and acquire the shared lock once before making core read-only.
    subprocess.run([sys.executable, str(root / "tools/pm.py"), "align"], cwd=root, check=True)
    private = workspace.repo(root, "workspace")
    approvals = private / APPROVAL_HOME
    if approvals.resolve() != approvals or approvals.exists() and not approvals.is_dir():
        raise ValueError("Use a regular Studio directory for PM approval receipts")
    if not approvals.exists():
        if os.environ.get("PM_HUB_SHARED_GROUP"):
            raise ValueError("Provision the shared PM approval directory before starting the agent")
        if session_journal.read_only_mount(private):
            raise ValueError("Provision the PM approval directory before launching an agent from read-only Studio")
        approvals.mkdir(mode=0o700, exist_ok=True)
    if approvals.resolve() != approvals or not approvals.is_dir():
        raise ValueError("The PM approval directory must exist before starting the protected agent")
    journals = session_journal.protected_home(private)
    journal = None
    if journals is not None and not session_journal.read_only_mount(journals):
        try:
            # Reserve this checkout's directory. Recording still needs explicit consent.
            journal = session_journal.location(private, provision=True)
        except (OSError, ValueError):
            pass  # A verified namespace with an unverified checkout gets a complete mask.
    if sys.platform == "darwin":
        # A path filter is inherited by the shell and by scripts it starts.
        core_path = json.dumps(str(root), ensure_ascii=False)
        work_path = json.dumps(str(private), ensure_ascii=False)
        profile = ('(version 1)(allow default)(deny file-write* '
                   f'(require-all (subpath {core_path}) (require-not (subpath {work_path}))))'
                   f'(deny file-write-unlink (literal {work_path}))')
        approval_path = json.dumps(str(approvals), ensure_ascii=False)
        profile += f"(deny file-write* (subpath {approval_path}))"
        if journals is not None:
            journals_path = json.dumps(str(journals), ensure_ascii=False)
        if journal:
            journal_path = json.dumps(str(journal), ensure_ascii=False)
            profile += (f"(deny file-read* file-write* (require-all (subpath {journals_path}) "
                        f"(require-not (literal {journals_path})) (require-not (subpath {journal_path}))))"
                        f"(deny file-write* (literal {journals_path}))"
                        f"(deny file-write-unlink (literal {journal_path}))")
        elif journals is not None:
            profile += f"(deny file-read* file-write* (subpath {journals_path}))"
        command = ["sandbox-exec", "-p", profile, binary]
    else:
        command = ["bwrap", "--die-with-parent", "--unshare-pid", "--bind", "/", "/",
                   "--dev", "/dev", "--proc", "/proc", "--ro-bind", str(root), str(root),
                   "--bind", str(private), str(private)]
        command.extend(["--ro-bind", str(approvals), str(approvals)])
        # Expose a verified checkout directory only. A failed identity check leaves the empty mask in place.
        if journals is not None:
            command.extend(["--perms", "0700", "--tmpfs", str(journals)])
            if journal:
                command.extend(["--bind", str(journal), str(journal)])
            command.extend(["--remount-ro", str(journals)])
        command.extend(["--chdir", str(root), "--", binary])
    if client == "codex":
        # A generic workspace-write profile tries to create protected mount
        # points inside the outer checkout. Scope Codex's own writer to studio/.
        extra = ', ' + json.dumps(str(journal), ensure_ascii=False) + '="write"' if journal else ""
        policy = ('permissions.pm_hub.filesystem={":root"="read", ":tmpdir"="write", '
                  '":slash_tmp"="write", ' + json.dumps(str(private), ensure_ascii=False) + '="write"' + extra + "}")
        command.extend(["-c", 'default_permissions="pm_hub"', "-c", policy])
    if context_statusline:
        collector = shlex.join([sys.executable, str(root / "tools/context_advice.py"), "claude-statusline"])
        settings = {"statusLine": {"type": "command", "command": collector}}
        command.extend(["--settings", json.dumps(settings)])
    env = dict(os.environ, PM_HUB_PROTECTED_ROOT=str(root), PM_HUB_CLIENT=client,
               ORYX_JOURNAL_CLIENT=client, PYTHONDONTWRITEBYTECODE="1")
    os.chdir(root)
    os.execvpe(command[0], command, env)
