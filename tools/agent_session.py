"""Start a local PM agent with core protected for the client and its children."""

import json
import os
import shlex
import shutil
import subprocess
import sys

import session_journal
import workspace


def launch(root, client, *, context_statusline=False):
    if context_statusline and client != "claude":
        raise ValueError("The optional native status line requires Claude Code")
    # Upgrade and acquire the shared lock once before making core read-only.
    subprocess.run([sys.executable, str(root / "tools/pm.py"), "align"], cwd=root, check=True)
    private = workspace.repo(root, "workspace")
    binary = shutil.which(client)
    if not binary:
        raise ValueError(f"Install {client} before starting a protected session")
    try:
        # Reserve only this checkout's directory. The journal itself needs explicit consent.
        journal = session_journal.location(private, provision=True)
        journals = journal.parent
    except (OSError, ValueError):
        journal = None
        # Mask the entire owner namespace if this checkout cannot prove its own identity.
        # If the namespace itself is redirected or unsafe, abort before starting the client.
        journals = session_journal.protected_home(private)
    if sys.platform == "darwin":
        # A path filter is inherited by the shell and by scripts it starts.
        core_path = json.dumps(str(root), ensure_ascii=False)
        work_path = json.dumps(str(private), ensure_ascii=False)
        profile = ('(version 1)(allow default)(deny file-write* '
                   f'(require-all (subpath {core_path}) (require-not (subpath {work_path}))))'
                   f'(deny file-write-unlink (literal {work_path}))')
        journals_path = json.dumps(str(journals), ensure_ascii=False)
        if journal:
            journal_path = json.dumps(str(journal), ensure_ascii=False)
            profile += (f"(deny file-read* file-write* (require-all (subpath {journals_path}) "
                        f"(require-not (literal {journals_path})) (require-not (subpath {journal_path}))))"
                        f"(deny file-write* (literal {journals_path}))"
                        f"(deny file-write-unlink (literal {journal_path}))")
        else:
            profile += f"(deny file-read* file-write* (subpath {journals_path}))"
        command = ["sandbox-exec", "-p", profile, binary]
    elif sys.platform.startswith("linux"):
        command = ["bwrap", "--die-with-parent", "--unshare-pid", "--bind", "/", "/",
                   "--dev", "/dev", "--proc", "/proc", "--ro-bind", str(root), str(root),
                   "--bind", str(private), str(private)]
        # Expose a verified checkout directory only. A failed identity check leaves the empty mask in place.
        command.extend(["--perms", "0700", "--tmpfs", str(journals)])
        if journal:
            command.extend(["--bind", str(journal), str(journal)])
        command.extend(["--remount-ro", str(journals)])
        command.extend(["--chdir", str(root), "--", binary])
    else:
        raise ValueError("Use Linux, WSL2, or macOS for protected PM sessions")
    if not shutil.which(command[0]):
        raise ValueError(f"Install {command[0]} to run a protected PM session")
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
