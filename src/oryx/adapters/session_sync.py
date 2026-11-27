"""Refresh verified customer connections during a foreground PM session only."""
from contextlib import contextmanager
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading


INTERVAL = 300


def guarded_cli(fd, argv):
    # The writer end belongs only to the PM session. Even an abrupt parent exit
    # closes it, terminating the entire worker group including provider helpers.
    def watch_session():
        os.read(fd, 1)
        os.killpg(os.getpgrp(), signal.SIGKILL)
    import runpy
    import select
    if os.getpid() != os.getpgrp():
        raise ValueError("The connection worker requires an isolated process group")
    if select.select([fd], [], [], 0)[0]:
        return
    threading.Thread(target=watch_session, daemon=True).start()
    sys.argv = argv
    runpy.run_path(argv[0], run_name="__main__")


def refresh(core, private, entry, stopped):
    read_fd, session_fd = os.pipe()
    try:
        args = [sys.executable, "-I", "-B", str(Path(__file__).resolve()), str(read_fd),
                str(core/"bin/oryx"), "valet", "scope", "sync", entry["scope"]]
        if entry["provider"] == "github":
            args.append("--github")
        environment = dict(os.environ, ORYX_WORKSPACE=str(private), ORYX_WORKSPACE_ID=entry["workspace"])
        with subprocess.Popen(args, cwd=core, env=environment, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, start_new_session=True, pass_fds=(read_fd,)) as process:
            try:
                while process.poll() is None and not stopped.wait(0.2):
                    pass
            finally:
                # EOF also handles kernels/shells that terminate the browser without running this finally.
                os.close(session_fd)
                session_fd = None
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
    finally:
        if session_fd is not None:
            os.close(session_fd)
        os.close(read_fd)


def entries(private):
    from oryx.workspace import connections
    from oryx.governance.files import directory, read
    folder = directory(private, connections.HOME)
    if folder.exists():
        for path in sorted(folder.glob("*.json")):
            try:
                entry = connections.validate(private, read(path), path.name)
            except (OSError, KeyError, TypeError, ValueError):
                continue
            if "actor" in entry and (entry["provider"] != "github" or "branch" in entry):
                yield entry


def run(core, private, wid, original, stopped, interval, worker):
    from oryx.workspace.location import selected_path, workspace_id
    while not stopped.is_set():
        try:
            status = private.stat()
            if ((status.st_dev, status.st_ino) != original or selected_path(core) != private
                    or workspace_id(private) != wid):
                return
            connections = list(entries(private))
            if not connections:
                return
            for entry in connections:
                if stopped.is_set():
                    return
                try:
                    worker(core, private, entry, stopped)
                except (OSError, ValueError, subprocess.SubprocessError):
                    continue
        except (OSError, KeyError, ValueError, TypeError):
            return
        stopped.wait(interval)


@contextmanager
def active(core, private, *, interval=INTERVAL, worker=refresh):
    # Unconnected local sessions start no worker, create no state, and access no provider.
    if (not os.environ.get("ORYX_WORKSPACE") or "PM_HUB_PROTECTED_ROOT" in os.environ
            or "ORYX_PROPOSAL_HOST" in os.environ):
        yield
        return
    from oryx.workspace import connections
    from oryx.workspace.location import selected_path, workspace_id
    try:
        eligible = ((private/connections.HOME).is_dir() and selected_path(core) == private
                    and next(entries(private), None) is not None)
        if eligible:
            wid = workspace_id(private)
            info = private.stat()
    except (ValueError, OSError, TypeError, KeyError):
        eligible = False
    if not eligible:
        yield
        return
    stopped = threading.Event()
    thread = threading.Thread(target=run, args=(core, private, wid, (info.st_dev, info.st_ino),
                                                stopped, interval, worker), daemon=True)
    thread.start()
    try:
        yield
    finally:
        stopped.set()
        thread.join()


if __name__ == "__main__":
    guarded_cli(int(sys.argv[1]), sys.argv[2:])
