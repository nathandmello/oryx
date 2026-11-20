"""Start a local PM agent with core protected for the client and its children."""

import json
import os
import shutil
import subprocess
import sys

import workspace


def launch(root, client):
    # Upgrade and acquire the shared lock once before making core read-only.
    subprocess.run([sys.executable, str(root / "tools/pm.py"), "align"], cwd=root, check=True)
    private = workspace.repo(root, "workspace")
    binary = shutil.which(client)
    if not binary:
        raise ValueError(f"Install {client} before starting a protected session")
    if sys.platform == "darwin":
        # A path filter is inherited by the shell and by scripts it starts.
        core_path = json.dumps(str(root), ensure_ascii=False)
        work_path = json.dumps(str(private), ensure_ascii=False)
        profile = ('(version 1)(allow default)(deny file-write* '
                   f'(require-all (subpath {core_path}) (require-not (subpath {work_path}))))'
                   f'(deny file-write-unlink (literal {work_path}))')
        command = ["sandbox-exec", "-p", profile, binary]
    elif sys.platform.startswith("linux"):
        command = ["bwrap", "--die-with-parent", "--unshare-pid", "--bind", "/", "/",
                   "--dev", "/dev", "--proc", "/proc", "--ro-bind", str(root), str(root),
                   "--bind", str(private), str(private), "--chdir", str(root), "--", binary]
    else:
        raise ValueError("Use Linux, WSL2, or macOS for protected PM sessions")
    if not shutil.which(command[0]):
        raise ValueError(f"Install {command[0]} to run a protected PM session")
    if client == "codex":
        # A generic workspace-write profile tries to create protected mount
        # points inside the outer checkout. Scope Codex's own writer to studio/.
        policy = ('permissions.pm_hub.filesystem={":root"="read", ":tmpdir"="write", '
                  '":slash_tmp"="write", ' + json.dumps(str(private), ensure_ascii=False) + '="write"}')
        command.extend(["-c", 'default_permissions="pm_hub"', "-c", policy])
    env = dict(os.environ, PM_HUB_PROTECTED_ROOT=str(root), PYTHONDONTWRITEBYTECODE="1")
    os.chdir(root)
    os.execvpe(command[0], command, env)
