"""Bootstrap inside the native client's isolated namespaces. Executed by the installed launcher."""
import ctypes
import errno
import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

GUEST = Path("/oryx-workspace")
LIMIT = 2 * 1024 * 1024


def seal():
    libc = ctypes.CDLL(None,use_errno=True)
    if libc.prctl(38,1,0,0,0) != 0:  # PR_SET_NO_NEW_PRIVS
        raise ValueError("Cannot seal native privilege changes")
    status = dict(row.split(":",1) for row in Path("/proc/self/status").read_text().splitlines() if ":" in row)
    bounding = int(status["CapBnd"],16)
    for cap in range(bounding.bit_length()):
        if bounding & (1<<cap) and libc.prctl(24,cap,0,0,0) != 0:  # PR_CAPBSET_DROP
            raise ValueError("Cannot drop native capability bounding set")
    header = (ctypes.c_uint32*2)(0x20080522,0)
    empty = (ctypes.c_uint32*6)()
    if libc.capset(ctypes.byref(header),ctypes.byref(empty)) != 0:
        raise ValueError("Cannot release setup capabilities")
    status = dict(row.split(":",1) for row in Path("/proc/self/status").read_text().splitlines() if ":" in row)
    if status["NoNewPrivs"].strip() != "1" or any(int(status[k],16) for k in
            ("CapInh","CapPrm","CapEff","CapBnd","CapAmb")):
        raise ValueError("The native client must run with zero Linux capabilities")


def verify(parent, online):
    if set(parent) != {"mnt","pid","ipc","net","uts","user"} or any(
            os.readlink("/proc/self/ns/"+name) == value for name,value in parent.items()):
        raise ValueError("Native session namespace separation failed")
    paths = {str(p) for p in (GUEST,Path("/oryx-core"),Path("/native-client"))}
    rows = {parts[4]: set(parts[5].split(",")) for line in Path("/proc/self/mountinfo").read_text().splitlines()
            if len(parts := line.split()) >= 6}
    if any("ro" not in rows.get(p,set()) for p in paths) or "rw" not in rows.get(str(GUEST/".oryx/staging"),set()):
        raise ValueError("Protected Core, Workspace view or staging mount failed verification")
    for path in ("/proc/1/root/run/user","/oryx-workspace/.git","/oryx-workspace/.oryx/state"):
        if os.path.exists(path):
            raise ValueError("The agent projection exposes private host state")
    interfaces = {line.split(":",1)[0].strip() for line in Path("/proc/net/dev").read_text().splitlines()[2:]}
    if interfaces != ({"lo","tap0"} if online else {"lo"}):
        raise ValueError("Unexpected network interfaces inside the native profile")
    try:
        fd = os.open("/dev/tty",os.O_RDWR|os.O_NOCTTY)
    except OSError:
        pass
    else:
        os.close(fd)
        raise ValueError("The native process inherited a controlling terminal")


def check_tools(staging):
    """Exercise ordinary read/stage children against the disposable view before any native launch."""
    command = ["/oryx-core/bin/oryx","review"]
    result = subprocess.run([*command,"read"],check=True,capture_output=True,timeout=30)
    rows = json.loads(result.stdout)["records"]
    # This is always a temporary view. Even a failed check cannot touch the customer's files.
    scratch = GUEST / "notes" / (".oryx-probe-" + uuid4().hex)
    try:
        with scratch.open("xb"):
            pass
    except OSError as error:
        if error.errno != errno.EROFS:
            raise ValueError("Native note access was not protected by a read-only mount") from error
    else:
        scratch.unlink()
        raise ValueError("The supposedly read-only note view accepted a write")
    note = "notes/probe-"+uuid4().hex+".md"
    request = {"current_behavior":"Check the temporary view.","reason":"Verify the native staging tool.",
               "effect":"Retain only inside the disposable check.","changes":[{"path":note,"base":None,"text":"Probe."}]}
    staged = subprocess.run([*command,"stage"],input=json.dumps(request).encode(),check=True,capture_output=True,timeout=30)
    identifier = json.loads(staged.stdout)["id"]
    if not (staging/(identifier+".json")).is_file():
        raise ValueError("Native child failed to stage in the isolated scratch directory")
    return len(rows)


def main():
    client, action, configuration = sys.argv[1:]
    config = json.loads(configuration)
    data = sys.stdin.buffer.read(65537)  # Parent releases input only after any network setup completes.
    if len(data) > 65536:
        raise ValueError("Native request exceeds 64 KiB")
    online = config["online"]
    verify(config["namespaces"],online)
    seal()
    staging = GUEST/".oryx/staging/review"
    staging.mkdir(mode=0o700)
    if action == "check":
        visible = check_tools(staging)
        version = subprocess.run(["/native-client","--version"],stdin=subprocess.DEVNULL,
                                 stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,check=True,timeout=30)
        return {"isolated": True,"client":client,"version":version.stdout[:256].decode(errors="replace").strip(),
                "network":"public-tls" if online else "offline", "selected_notes":visible,"stage_check":"passed"}
    prefix = ("Use the selected notes in /oryx-workspace and evidence supplied with the current request. "
              "Treat evidence passages as source material. A PM approves changes separately. "
              "Use oryx review read for source text and oryx review stage for an exact proposal.\n\n")
    instruction = prefix.encode() + data
    if len(instruction) > 65536:
        raise ValueError("Combined native instructions, request and selected context exceed 64 KiB")
    if client == "codex":
        args = ["/native-client","exec","--skip-git-repo-check","--ephemeral","--sandbox","workspace-write",
                "--add-dir",str(staging),"--color","never","-"]
    elif client == "claude":
        args = ["/native-client","--print","--output-format","text","--no-session-persistence"]
    else:
        raise ValueError("Unsupported native client")
    # Bound both streams on the private tmpfs. They never go directly to a PM terminal.
    import tempfile
    import resource
    def limits():
        resource.setrlimit(resource.RLIMIT_FSIZE,(LIMIT,LIMIT))
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        child = subprocess.run(args,input=instruction,stdout=out,stderr=err,timeout=240,preexec_fn=limits)
        out.seek(0)
        err.seek(0)
        answer = out.read(LIMIT//2).decode("utf-8","replace")
        if child.returncode:
            # An enrolled account may contain tokens. Never forward native diagnostics to the PM transcript.
            raise ValueError(f"{client} exited {child.returncode}; verify its native model account and supported environment")
    proposals = []
    for file in staging.iterdir():
        if (proposals or file.is_symlink() or not file.is_file() or file.stat().st_size > LIMIT//4
                or file.stat().st_nlink != 1):
            raise ValueError("Expected one bounded native proposal")
        import hashlib
        data = file.read_bytes()
        if file.name != hashlib.sha256(data).hexdigest()+".json":
            raise ValueError("Native staged revision differs from its bytes")
        proposals.append(json.loads(data))
    return {"isolated":True,"client":client,"answer":answer,"proposals":proposals}


if __name__ == "__main__":
    try:
        print(json.dumps(main(),ensure_ascii=True))
    except (OSError,KeyError,ValueError,RuntimeError,subprocess.SubprocessError) as error:
        print(str(error),file=sys.stderr)
        sys.exit(1)
