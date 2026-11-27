"""Run an external Workspace client with a bounded read-only projection and private scratch."""
from contextlib import contextmanager, ExitStack
import fcntl
import ipaddress
import json
import os
from pathlib import Path
import platform
import selectors
import shutil
import select
import signal
import stat
import subprocess
import sys
from tempfile import TemporaryDirectory
import time

from oryx.release import archive
from oryx.review import store

NAMESPACES = ("user", "mnt", "pid", "ipc", "net", "uts")
LIMIT = 2 * 1024 * 1024
HOLD = "External Workspace needs a qualified OS-isolated client adapter"
GUEST = "/oryx-workspace"


def native_binary(client):
    found = shutil.which(client)
    if not found:
        raise ValueError(f"{HOLD}. Install native {client} first")
    binary = Path(found).resolve(strict=True)
    if client == "codex" and binary.name == "codex.js":
        # Official npm entry points delegate to this native binary.
        machine = {"x86_64": ("x64", "x86_64"), "aarch64": ("arm64", "aarch64")}.get(platform.machine())
        if machine is None or binary.parent.parent.name != "codex" or binary.parents[2].name != "@openai":
            raise ValueError(f"{HOLD}. Select the standalone native Codex executable")
        arch, triple = machine
        binary = binary.parents[2] / ("codex-linux-" + arch) / "vendor" / (triple + "-unknown-linux-musl") / "bin/codex"
    if not binary.is_file() or not os.access(binary, os.X_OK):
        raise ValueError(f"{HOLD}. Select an executable native {client} binary")
    with binary.open("rb") as stream:
        if stream.read(4) != b"\x7fELF":
            raise ValueError(f"{HOLD}. The Linux profile requires the native {client} executable")
    return binary


def project(ws, directory, selected):
    if len(selected) != len(set(selected)) or len(selected) > 32 or any(not store.NOTE.fullmatch(p) for p in selected):
        raise ValueError("Select up to 32 distinct managed notes by their notes/name.md paths")
    head, texts = ws.snapshot() if selected else ({"files": {}, "governing": []}, {})
    selection = {p.split("/")[1] for p in selected}
    official = directory / "notes"
    official.mkdir(mode=0o700)
    metadata = directory / ".oryx"
    metadata.mkdir(mode=0o700)
    (metadata / "workspace.json").write_bytes(store.encoded({"id": ws.identity}))
    narrowed = {"schema": 1, "workspace": ws.identity, "receipts": {},
                "governing": sorted(selection.intersection(head.get("governing", []))),
                "files": {k: v for k, v in head["files"].items() if k in selection}}
    store.Workspace.write_generation(official, narrowed, {k: v for k,v in texts.items() if k in selection})
    # Native skill discovery needs only release-owned guides, never the real customer checkout.
    (directory / ".claude").mkdir(mode=0o700)
    # The checkout hooks expect their working directory to be inside Core. Only project
    # skill discovery applies to a separately mounted, selected-note Workspace.
    for resource in ("AGENTS.md", ".agents", ".claude/skills", "playbook", "templates", "tools"):
        (directory/resource).symlink_to("/oryx-core/"+resource)
    return narrowed


@contextmanager
def account(path, ws, core, client):
    if path is None:
        yield None
        return
    path = Path(path)
    install = core.parents[2] if core.parents[1].name == "generations" else core
    if (not path.is_absolute() or path.resolve() != path or path == Path.home()
            or Path.home().is_relative_to(path) or any(path.is_relative_to(p) or p.is_relative_to(path)
              for p in (ws.root, install)) or not path.parent.is_dir()):
        raise ValueError("Choose a dedicated absolute native client home outside the installation and Workspace")
    if not path.exists():
        path.mkdir(mode=0o700)
    store.checked_directory(path,private=True)
    # Lock the directory itself, keeping the account-selection lock out of the native files.
    fd = os.open(path,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:
        fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        marker = path/".oryx-native-home"
        expected = store.encoded({"client":client,"version":1})
        if not list(path.iterdir()):
            store.publish_file(marker,expected)
        if marker.is_symlink() or not marker.is_file() or marker.stat().st_size != len(expected) or marker.read_bytes()!=expected:
            raise ValueError("Choose an empty dedicated directory or a home already provisioned for this client")
        from oryx.recovery.snapshot import mounted_below
        mounted_below(path)
        count = 0
        for base, dirs, files in os.walk(path, followlinks=False):
            for name in [*dirs,*files]:
                node = Path(base)/name
                info = node.lstat()
                count += 1
                if (count > 50000 or info.st_uid != os.geteuid() or info.st_mode & 0o7022
                        or not (stat.S_ISDIR(info.st_mode) or
                                stat.S_ISREG(info.st_mode) and info.st_nlink == 1)):
                    raise ValueError("Dedicated agent homes require bounded, individually owned directories and regular files")
        yield path
    finally:
        os.close(fd)


def network_addresses():
    data = subprocess.run(["/usr/sbin/ip","-j","address","show"], env={"PATH":os.defpath},
                          stdin=subprocess.DEVNULL,capture_output=True,check=True,timeout=5)
    rows = json.loads(data.stdout)
    addresses = sorted({a["local"] for row in rows for a in row["addr_info"] if a["family"]=="inet"})
    if not addresses:
        raise ValueError("Cannot establish the PM host's network addresses")
    return addresses


# Only public IPv4 TLS may leave the configured interface. DNS uses slirp's dedicated resolver.
RESERVED = ("0.0.0.0/8","10.0.0.0/8","100.64.0.0/10","127.0.0.0/8","169.254.0.0/16",
            "172.16.0.0/12","192.0.0.0/24","192.0.2.0/24","192.88.99.0/24","192.168.0.0/16",
            "198.18.0.0/15","198.51.100.0/24","203.0.113.0/24","224.0.0.0/4","240.0.0.0/4")


def namespace_descriptors(stack, pid, status):
    # NS_GET_USERNS returns the owner of the new network namespace. Bubblewrap may
    # place the final client inside a further user namespace to disable nesting.
    net = os.open(f"/proc/{pid}/ns/net", os.O_RDONLY | os.O_CLOEXEC)
    stack.callback(os.close, net)
    user = fcntl.ioctl(net, 0xb701)
    stack.callback(os.close, user)
    if (os.fstat(net).st_ino == os.stat("/proc/self/ns/net").st_ino
            or os.fstat(user).st_ino == os.stat("/proc/self/ns/user").st_ino
            or status.get("net-namespace", os.fstat(net).st_ino) != os.fstat(net).st_ino):
        raise ValueError("Refusing to configure networking outside a new child namespace")
    return user, net


def install_policy(user, net):
    public_exclusions = [str(ipaddress.IPv4Address(addr)) for addr in network_addresses()]
    rules = ["*filter",":INPUT DROP [0:0]",":FORWARD DROP [0:0]",":OUTPUT DROP [0:0]",
             "-A INPUT -i lo -j ACCEPT","-A INPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT",
             "-A OUTPUT -o lo -j ACCEPT"]
    rules += [f"-A OUTPUT -o tap0 -d 10.0.2.3 -p {protocol} --dport 53 -j ACCEPT" for protocol in ("udp","tcp")]
    rules += [f"-A OUTPUT -d {address} -j DROP" for address in (*RESERVED,*public_exclusions)]
    rules += ["-A OUTPUT -o tap0 -p tcp --dport 443 -j ACCEPT","COMMIT"]
    v6 = ["*filter",":INPUT DROP [0:0]",":FORWARD DROP [0:0]",":OUTPUT DROP [0:0]","COMMIT"]
    # Only the trusted rule loader enters these namespaces. It inherits no account
    # files, model prompt, client descriptors, or host network administration rights.
    ns = ["/usr/bin/nsenter", "--user=/proc/self/fd/"+str(user), "--net=/proc/self/fd/"+str(net),
          "--preserve-credentials", "--keep-caps", "--"]
    with TemporaryDirectory(prefix="oryx-firewall-") as directory:
        env = {"PATH": os.defpath, "LC_ALL": "C", "XTABLES_LOCKFILE": str(Path(directory)/"lock")}
        for binary, policy in [("iptables-restore", rules), ("ip6tables-restore", v6)]:
            result = subprocess.run([*ns, "/usr/sbin/"+binary], input=("\n".join(policy)+"\n").encode(),
                                    capture_output=True, pass_fds=(user, net), env=env, timeout=15)
            if result.returncode:
                diagnostic = result.stderr[:400].decode("ascii", "replace")
                raise ValueError(f"{HOLD}. Could not install child network policy: {diagnostic!r}")


def command(core, directory, binary, client, check, home=None):
    bwrap = "/usr/bin/bwrap"
    if sys.platform != "linux" or not os.path.isfile(bwrap) or os.geteuid() == 0:
        raise ValueError(f"{HOLD}. This profile requires an unprivileged Linux user and system bubblewrap")
    parent_ns = {name: os.readlink("/proc/self/ns/" + name) for name in NAMESPACES}
    cmd = [bwrap, "--unshare-user", "--unshare-pid", "--unshare-ipc", "--unshare-net", "--unshare-uts",
           "--new-session", "--die-with-parent", "--disable-userns", "--cap-drop", "ALL",
           "--cap-add", "CAP_SETPCAP", "--clearenv",
           "--proc", "/proc", "--dev", "/dev", "--dir", "/usr"]
    for path in ("/usr/bin", "/usr/lib", "/usr/lib64"):
        if Path(path).is_dir():
            cmd += ["--ro-bind", path, path]
    for path in ("/bin", "/lib", "/lib64"):
        if Path(path).is_symlink():
            cmd += ["--symlink", os.readlink(path), path]
        elif Path(path).is_dir():
            cmd += ["--ro-bind", path, path]
    if home is not None:
        # Rootless slirp's own sandbox enters the owning user namespace as UID/GID 0.
        # Only the unprivileged PM's IDs are mapped. seal() drops every capability
        # before a native executable or a tool sees the account or prompt.
        cmd += ["--uid", "0", "--gid", "0", "--ro-bind","/etc/ssl/certs/ca-certificates.crt","/etc/ssl/certs/ca-certificates.crt",
                "--ro-bind",str(directory.parent/"resolv.conf"),"/etc/resolv.conf",
                "--size","1048576","--tmpfs","/run"]
    cmd += ["--ro-bind", str(core), "/oryx-core", "--ro-bind", str(binary), "/native-client",
            "--ro-bind", str(directory), GUEST, "--size", str(LIMIT * 2), "--tmpfs", GUEST+"/.oryx/staging",
            "--size", str(64*1024*1024), "--tmpfs", "/tmp", "--dir", "/home"]
    cmd += ["--bind",str(home),"/home/client"] if home else ["--size",str(64*1024*1024),"--tmpfs","/home/client"]
    cmd += ["--remount-ro", "/", "--chdir", GUEST,
            "--setenv", "HOME", "/home/client", "--setenv", "PATH", "/oryx-core/bin:/usr/bin:/bin",
            "--setenv", "PM_HUB_PROTECTED_ROOT", "/oryx-core", "--setenv", "ORYX_PROPOSAL_HOST", "1",
            "--setenv", "PYTHONDONTWRITEBYTECODE", "1", "--setenv", "LC_ALL", "C.UTF-8",
            "--", "/usr/bin/python3", "-IB", "/oryx-core/src/oryx/adapters/host_runner.py",
            client, "check" if check else "run", json.dumps({"namespaces":parent_ns,"online":home is not None})]
    return cmd


def notice(fd, process, limit, *, json_record=False):
    end = time.monotonic()+12
    data = b""
    while len(data) <= limit and time.monotonic() < end:
        if process.poll() is not None:
            break
        active,_,_ = select.select([fd],[],[],min(0.3,max(0,end-time.monotonic())))
        if not active:
            continue
        block = os.read(fd,limit+1-len(data))
        if not block:
            break
        data += block
        if not json_record:
            return data
        try:
            return json.loads(data)
        except ValueError:
            pass
    raise ValueError(f"{HOLD}. Namespace or restricted networking setup did not report readiness")


def stop(process):
    if process.poll() is None:
        try:
            os.killpg(process.pid,signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=10)


@contextmanager
def processes(command, online):
    with ExitStack() as stack:
        info = os.pipe() if online else ()
        for fd in info:
            stack.callback(os.close, fd)
        cmd = [command[0],"--info-fd",str(info[1]),*command[1:]] if online else command
        child = stack.enter_context(subprocess.Popen(cmd,stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE,env={"PATH":os.defpath,"LC_ALL":"C"},close_fds=True,
                             pass_fds=info[1:],start_new_session=True))
        stack.callback(stop,child)
        if online:
            try:
                status = notice(info[0], child, 4096, json_record=True)
            except ValueError as error:
                stop(child)
                message = child.stderr.read(400).decode("ascii", "replace")
                raise ValueError(f"{HOLD}. Network namespace did not start: {message!r}") from error
            pid = status.get("child-pid")
            if type(pid) is not int or pid < 1 or child.poll() is not None:
                raise ValueError("Native network namespace vanished during setup")
            ready = os.pipe()
            lifetime = os.pipe()
            for fd in (*ready,*lifetime):
                stack.callback(os.close,fd)
            user, net = namespace_descriptors(stack, pid, status)
            install_policy(user, net)
            # Use PID addressing so the slirp process can enter the client's user
            # namespace for its own sandbox. Its TAP helper uses the netns owner.
            # Native bootstrap waits on stdin until both policy and transport are ready.
            network = stack.enter_context(subprocess.Popen(["/usr/bin/slirp4netns", "--configure",
                  "--disable-host-loopback", "--enable-sandbox", "--enable-seccomp", "--ready-fd", str(ready[1]),
                  "--exit-fd", str(lifetime[0]), "--userns-path=/proc/self/fd/"+str(user),
                  str(pid), "tap0"], env={"PATH":os.defpath,"LC_ALL":"C"},
                  stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                  start_new_session=True, pass_fds=(user, net, ready[1], lifetime[0])))
            stack.callback(stop, network)
            try:
                ready_byte = notice(ready[0], network, 8)
            except ValueError as error:
                # This system helper has no access to native input or account credentials.
                stop(network)
                message = network.stderr.read(400).decode("ascii", "replace")
                raise ValueError(f"{HOLD}. Network transport did not start: {message!r}") from error
            if len(ready_byte) != 1 or network.poll() is not None:
                raise ValueError("Restricted user-mode networking is unavailable")
        yield child


def bounded(command, data, timeout, *, online=False):
    # Use a new session and pipes. No native client can inherit the PM's terminal.
    with processes(command,online) as child:
        buffers = {child.stdout: bytearray(), child.stderr: bytearray()}
        try:
            with selectors.DefaultSelector() as streams:
                streams.register(child.stdin,selectors.EVENT_WRITE)
                for source in buffers:
                    streams.register(source,selectors.EVENT_READ)
                deadline = time.monotonic() + timeout
                while streams.get_map():
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise ValueError("Protected client timed out")
                    for key, _ in streams.select(min(remaining, 1)):
                        source = key.fileobj
                        if source is child.stdin:
                            if data:
                                try:
                                    count = os.write(source.fileno(), data[:4096])
                                    data = data[count:]
                                except BrokenPipeError:
                                    data = b""
                            if not data:
                                streams.unregister(source)
                                source.close()
                        else:
                            block = os.read(source.fileno(),65536)
                            if block:
                                buffers[source].extend(block)
                                if len(buffers[source]) > LIMIT:
                                    raise ValueError("Protected client output exceeds the local limit")
                            else:
                                streams.unregister(source)
            return child.wait(timeout=max(1,deadline-time.monotonic())), *(bytes(buffers[s]) for s in (child.stdout,child.stderr))
        finally:
            if child.poll() is None:
                os.killpg(child.pid,signal.SIGKILL)
                child.wait()


def import_proposals(ws, selected, frozen, proposals, *, records=()):
    if not isinstance(proposals, list) or len(proposals) > 1:
        raise ValueError("Submit at most one atomic local note group per protected turn")
    staged = []
    for draft in proposals:
        if not isinstance(draft,dict) or set(draft) != {"workspace","request"} or draft["workspace"] != ws.identity:
            raise ValueError("Native proposal belongs to a different Workspace")
        req = draft["request"]
        if not isinstance(req,dict) or not isinstance(req.get("changes"),list):
            raise ValueError("Expected a complete native note proposal")
        for change in req["changes"]:
            if not isinstance(change,dict) or change.get("path") not in selected:
                raise ValueError("Native proposal exceeds this session's selected notes")
            if change.get("base") != frozen["files"].get(change["path"].split("/")[1]):
                raise ValueError("Native proposal does not use the session's reviewed base")
        staged.append(ws.stage(req, evidence=records) if records else ws.stage(req))
    return staged


def launch(core, client, *, selected=(), records=(), check=False, client_home=None):
    from oryx.adapters import selected_evidence
    from oryx.workspace import storage
    store.pm_only()
    if client not in {"codex","claude"}:
        raise ValueError("Choose Codex or Claude")
    if not (core / archive.MANIFEST).is_file():
        raise ValueError(f"{HOLD}. Use a verified installed Core for external launch")
    archive.check_runtime(core)
    ws = store.Workspace()
    binary = native_binary(client)
    with TemporaryDirectory(prefix="oryx-native-") as name:
        view = Path(name)/"view"
        view.mkdir(mode=0o700)
        (Path(name)/"resolv.conf").write_text("nameserver 10.0.2.3\n")
        frozen = project(ws,view,selected)
        (view / ".oryx/staging").mkdir(mode=0o700)
        cmd = command(core,view,binary,client,True)
        version = invoke(cmd,b"",100)
        with account(client_home,ws,core,client) as home:
            if home is not None:
                version = invoke(command(core,view,binary,client,True,home),b"",110,online=True)
            if check:
                if records:
                    version["selected_sections"] = len(selected_evidence.snapshot(ws.root, records))
                print(json.dumps(version,ensure_ascii=True))
                return
            from oryx.adapters import session_sync
            with session_sync.active(core, ws.root):
                if sys.stdin.isatty():
                    print("Enter one request for the isolated native client.",flush=True)
                    prompt = sys.stdin.readline(65537)
                else:
                    prompt = sys.stdin.read(65537)
                if not prompt.strip() or len(prompt.encode()) > 65536:
                    raise ValueError("Provide one nonempty request of at most 64 KiB")
                evidence = selected_evidence.snapshot(ws.root, records)
                payload = selected_evidence.request(prompt, evidence)
                try:
                    result = invoke(command(core,view,binary,client,False,home),payload,300,online=home is not None)
                except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
                    if records:
                        # Native stderr may contain the submitted passage even when a turn fails.
                        raise ValueError("The native evidence turn did not complete") from None
                    raise
                if records:
                    with storage.writer_lock(ws.root):
                        if selected_evidence.snapshot(ws.root, records) != evidence:
                            raise ValueError("Record authority or revision changed during the native turn")
                        staged = import_proposals(ws,set(selected),frozen,result.pop("proposals"),records=records)
                        print(json.dumps({**result, "staged":staged}, ensure_ascii=True))
                else:
                    staged = import_proposals(ws,set(selected),frozen,result.pop("proposals"))
                    print(json.dumps({**result, "staged":staged}, ensure_ascii=True))


def invoke(cmd, prompt, timeout, *, online=False):
    code, out, err = bounded(cmd,prompt,timeout,online=online)
    if code:
        reason = (err or out).decode("utf-8","replace")[:1200]
        raise ValueError(f"{HOLD}: {json.dumps(reason,ensure_ascii=True)}")
    result = json.loads(out)
    if not isinstance(result,dict) or result.get("isolated") is not True:
        raise ValueError("Native process did not verify its OS boundary")
    return result
