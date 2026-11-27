"""Stage proposals and atomically publish one reviewed group of Markdown records on Linux."""

from contextlib import contextmanager
import ctypes
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
from uuid import uuid4


HEAD = ".oryx-review.json"
MAX_NOTE = 256 * 1024
MAX_METADATA = 8 * 1024 * 1024
HEX = re.compile(r"[0-9a-f]{64}")
NOTE = re.compile(r"notes/[a-z0-9][a-z0-9-]{0,95}\.md")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def encoded(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def unique(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("Duplicate JSON field")
        result[key] = value
    return result


def read_fd(parent, name, maximum):
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    with os.fdopen(fd, "rb") as file:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > maximum:
            raise ValueError("Expected one bounded regular file")
        data = file.read(maximum + 1)
        if len(data) > maximum:
            raise ValueError("File exceeds supported size")
        return data


def checked_directory(path, *, private=False):
    if path.resolve() != path:
        raise ValueError("Use an unredirected directory")
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode):
        raise ValueError("Expected a regular directory")
    if private and (info.st_uid != os.geteuid() or info.st_mode & 0o077):
        raise ValueError("The PM must own this private directory")
    return path


def sync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def publish_file(path, contents, mode=0o600):
    """Expose complete bytes once, even if two agents stage identical proposals."""
    temporary = path.parent / (".write-" + uuid4().hex)
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        with os.fdopen(fd, "wb") as file:
            file.write(contents)
            file.flush()
            os.fchmod(file.fileno(), mode)
            os.fsync(file.fileno())
        rename_dir(temporary, path, exchange=False)
    finally:
        temporary.unlink(missing_ok=True)
        sync_dir(path.parent)


def rename_dir(source, dest, *, exchange):
    function = getattr(ctypes.CDLL(None, use_errno=True), "renameat2", None)
    if sys.platform != "linux" or function is None:
        raise ValueError("Protected group publication requires Linux atomic directory exchange")
    if function(-100, os.fsencode(source), -100, os.fsencode(dest), 2 if exchange else 1):
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))
    sync_dir(source.parent)
    if source.parent != dest.parent:
        sync_dir(dest.parent)


def pm_only():
    if "PM_HUB_PROTECTED_ROOT" in os.environ or "ORYX_PROPOSAL_HOST" in os.environ:
        raise ValueError("Only the PM's local review session can perform this operation")


class Workspace:
    def __init__(self):
        from oryx.workspace.location import selected_path, workspace_id
        core = Path(__file__).resolve().parents[3]
        isolated = os.environ.get("ORYX_PROPOSAL_HOST") == "1"
        if isolated:
            self.root = Path("/oryx-workspace")
            checked_directory(self.root)
        else:
            self.root = selected_path(core)
            if self.root is None:
                raise ValueError("Select the external Workspace before using protected review")
            checked_directory(self.root, private=True)
        self.identity = workspace_id(self.root)
        self.official = self.root / "notes"
        self.staging = self.root / ".oryx/staging/review"
        self.state = self.root / ".oryx/state/review"

    def setup_state(self):
        pm_only()
        checked_directory(self.root / ".oryx", private=True)
        for path in (self.state.parent, self.state, self.staging.parent, self.staging,
                     self.state / "generations", self.state / "discarded", self.state / "transactions"):
            path.mkdir(mode=0o700, exist_ok=True)
            checked_directory(path, private=True)
            sync_dir(path.parent)
    def init(self):
        self.setup_state()
        with self.lock():
            if os.path.lexists(self.official):
                self.snapshot()
            else:
                folder = self.generation()
                head = {"schema": 1, "workspace": self.identity, "files": {}, "receipts": {}}
                self.write_generation(folder, head, {})
                rename_dir(folder, self.official, exchange=False)
        return {"workspace": self.identity, "domain": "notes"}

    def generation(self):
        directory = self.state / "generations" / uuid4().hex
        directory.mkdir(mode=0o700)
        sync_dir(directory.parent)
        return directory

    @contextmanager
    def lock(self):
        pm_only()
        checked_directory(self.state, private=True)
        fd = os.open(self.state / "writer.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.geteuid() or info.st_mode & 0o077:
                raise ValueError("Unsafe protected writer lock")
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            os.close(fd)

    def snapshot(self, directory=None):
        directory = self.official if directory is None else directory
        checked_directory(directory)
        fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            head = json.loads(read_fd(fd, HEAD, MAX_METADATA), object_pairs_hook=unique)
            if (not isinstance(head, dict) or set(head) - {"governing"} != {"schema", "workspace", "files", "receipts"}
                    or head["schema"] != 1 or head["workspace"] != self.identity
                    or not isinstance(head["files"], dict) or not isinstance(head["receipts"], dict)):
                raise ValueError("Unmanaged or incompatible notes directory")
            governed = head.get("governing", [])
            if (not isinstance(governed, list) or not all(isinstance(name, str) and NOTE.fullmatch("notes/"+name)
                                                          for name in governed) or len(set(governed)) != len(governed)):
                raise ValueError("Invalid protected decision record classification")
            for identifier, receipt in head["receipts"].items():
                if (not HEX.fullmatch(identifier) or not isinstance(receipt, dict)
                        or set(receipt) != {"workspace", "id", "actor", "review", "paths"}
                        or receipt["workspace"] != self.identity or receipt["id"] != identifier
                        or receipt["actor"] not in {"pm-local-review", "pm-local-editor"}
                        or not isinstance(receipt["review"],str) or not HEX.fullmatch(receipt["review"])
                        or not isinstance(receipt["paths"],list) or not 1 <= len(receipt["paths"]) <= 32
                        or not all(isinstance(path,str) and NOTE.fullmatch(path) for path in receipt["paths"])):
                    raise ValueError("Invalid protected note receipt")
            names = set(os.listdir(fd))
            if set(head["files"]) | {HEAD} != names:
                raise ValueError("An unmanaged file appeared in notes. Existing work was preserved")
            texts = {}
            for name, checksum in head["files"].items():
                if not NOTE.fullmatch("notes/" + name):
                    raise ValueError("Invalid protected note path")
                data = read_fd(fd, name, MAX_NOTE)
                if sha(data) != checksum:
                    raise ValueError("A note changed outside review. Preserve the human edit and reconcile")
                texts[name] = data.decode("utf-8")
            return head, texts
        finally:
            os.close(fd)

    @staticmethod
    def write_generation(path, head, texts, *, unchanged=None):
        metadata = encoded(head)
        if len(metadata) > MAX_METADATA:
            raise ValueError("Review metadata exceeds the supported limit")
        for name, value in texts.items():
            target = path / name
            publish_file(target, value.encode("utf-8"), mode=0o400)
            if unchanged and name in unchanged:
                info = unchanged[name]
                os.utime(target, ns=(info.st_atime_ns, info.st_mtime_ns), follow_symlinks=False)
                with target.open("rb") as stream:
                    os.fsync(stream.fileno())
        publish_file(path / HEAD, metadata, mode=0o400)
        # Linux needs directory write permission to move its parent entry across directories.
        # The private PM directory and restricted host mounts are the access boundary.
        path.chmod(0o700)
        sync_dir(path)

    def proposal(self, identifier):
        if not HEX.fullmatch(identifier):
            raise ValueError("Expected the staged proposal digest")
        checked_directory(self.staging)
        fd = os.open(self.staging, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            data = read_fd(fd, identifier + ".json", MAX_METADATA)
        finally:
            os.close(fd)
        if sha(data) != identifier:
            raise ValueError("The staged proposal changed. Stage and review the new revision")
        result = json.loads(data, object_pairs_hook=unique)
        if result.get("workspace") != self.identity or set(result) != {"workspace", "request"}:
            raise ValueError("Proposal does not belong to the selected Workspace")
        return result["request"]

    def stage(self, request):
        head, texts = self.snapshot()
        materialize(request, head, texts)
        return self.stage_request(request)

    def stage_request(self, request):
        data = encoded({"workspace": self.identity, "request": request})
        if len(data) > MAX_METADATA:
            raise ValueError("Proposal exceeds the supported group size")
        identifier = sha(data)
        checked_directory(self.staging)
        try:
            publish_file(self.staging / (identifier + ".json"), data)
        except FileExistsError:
            self.proposal(identifier)
        return {"id": identifier, "workspace": self.identity, "state": "staged"}

    def inspect(self, identifier):
        request = self.proposal(identifier)
        if request.get("operation") in {"initiative-work", "customization"}:
            from . import work
            return work.inspect(self, identifier, request)
        if request.get("operation") == "handoff-save":
            from . import handoff
            return handoff.inspect(self, identifier, request)
        head, texts = self.snapshot()
        if identifier in head["receipts"]:
            return {"state": "applied", "receipt": head["receipts"][identifier]}
        if (self.state / "discarded" / identifier).is_file():
            return {"state": "discarded", "id": identifier}
        request = self.proposal(identifier)
        _, pairs = materialize(request, head, texts)
        return {"id": identifier, "state": "pending", "workspace": self.identity,
                **{name: request[name] for name in ("current_behavior", "reason", "effect")},
                "changes": pairs}

    def decide(self, identifier, reviewed, choice, *, actor="pm-local-review"):
        pm_only()
        with self.lock():
            shown = self.inspect(identifier)
            if shown["state"] == "recovering":
                from . import work
                return work.commit(self, identifier, reviewed, self.proposal(identifier), actor)
            if shown["state"] != "pending":
                return shown
            if encoded(shown) != reviewed:
                raise ValueError("Review is stale. Inspect the current wording and destination again")
            if choice == "discard":
                if (self.state / "transactions" / identifier).exists():
                    raise ValueError("A saved decision is awaiting recovery. Resume the approved change")
                publish_file(self.state / "discarded" / identifier, encoded({"id": identifier, "actor": actor}))
                return {"id": identifier, "state": "discarded"}
            if choice != "save":
                raise ValueError("Expected a PM save or discard decision")
            request = self.proposal(identifier)
            if request.get("operation") in {"initiative-work", "customization"}:
                from . import work
                return work.commit(self, identifier, reviewed, request, actor)
            if request.get("operation") == "handoff-save":
                from . import handoff
                return handoff.commit(self, identifier, reviewed, request, actor)
            head, texts = self.snapshot()
            updated, _ = materialize(request, head, texts)
            receipt = {"id": identifier, "workspace": self.identity, "actor": actor, "review": sha(reviewed),
                       "paths": [item["path"] for item in request["changes"]]}
            governed = set(head.get("governing", []))
            governed.update(item["path"].split("/")[1] for item in request["changes"] if "decisions" in item)
            next_head = {**head, "governing": sorted(governed), "files": {k: sha(v.encode()) for k, v in updated.items()},
                         "receipts": {**head["receipts"], identifier: receipt}}
            generation = self.generation()
            unchanged = {name: (self.official / name).lstat()
                         for name, value in updated.items() if name in texts and value == texts[name]}
            self.write_generation(generation, next_head, updated, unchanged=unchanged)
            if self.proposal(identifier) != request or self.snapshot() != (head, texts):
                raise ValueError("A draft or official record changed during preparation")
            for name, previous in unchanged.items():
                latest = (self.official / name).lstat()
                if not os.path.samestat(previous, latest) or latest.st_mtime_ns != previous.st_mtime_ns:
                    raise ValueError("An unchanged sibling was edited during review. Review its current revision")
            rename_dir(generation, self.official, exchange=True)
            return {"state": "applied", "receipt": receipt}


def text(value, label, limit=4096):
    if not isinstance(value, str) or len(value.encode("utf-8")) > limit:
        raise ValueError(f"Invalid or oversized {label}")
    if any(ord(char) < 32 and char not in "\t\n" or ord(char) == 127 for char in value):
        raise ValueError(f"Unsupported control characters in {label}")
    return value


def governing(edits, old, new):
    if not isinstance(edits, list) or not 1 <= len(edits) <= 100:
        raise ValueError("List every governing addition, replacement or removal")
    pieces = []
    position = 0
    for edit in edits:
        if not isinstance(edit, dict) or set(edit) != {"start", "end", "before", "after", "summary", "conditions", "exceptions", "consequences"}:
            raise ValueError("Explain each edit, its conditions, exceptions and consequences")
        start, end = edit["start"], edit["end"]
        if (type(start) is not int or type(end) is not int or not position <= start <= end <= len(old)
                or old[start:end] != edit["before"] or edit["before"] == edit["after"]):
            raise ValueError("Decision edits must match exact nonoverlapping old wording")
        for field in ("summary", "conditions", "exceptions", "consequences"):
            if not text(edit[field], field).strip():
                raise ValueError(f"Explain decision {field}")
        pieces.extend([old[position:start], text(edit["after"], "decision wording", MAX_NOTE)])
        position = end
    if "".join([*pieces, old[position:]]) != new:
        raise ValueError("Governing text contains changes outside the listed decision edits")


def materialize(request, head, texts):
    if not isinstance(request, dict) or set(request) != {"current_behavior", "reason", "effect", "changes"}:
        raise ValueError("Supply current behavior, reason, effect and proposed changes")
    for field in ("current_behavior", "reason", "effect"):
        if not text(request[field], field).strip():
            raise ValueError("Supply nonempty review context")
    changes = request["changes"]
    if not isinstance(changes, list) or not 1 <= len(changes) <= 32:
        raise ValueError("Review groups contain one to 32 changes")
    updated, pairs, seen = dict(texts), [], set()
    for item in changes:
        if (not isinstance(item, dict) or set(item) not in ({"path", "base", "text"}, {"path", "base", "text", "decisions"})
                or not isinstance(item["path"], str) or not NOTE.fullmatch(item["path"]) or item["path"] in seen):
            raise ValueError("Use unique notes/<name>.md destinations within the managed domain")
        seen.add(item["path"])
        name = item["path"].split("/")[1]
        old, new = texts.get(name), item["text"]
        if head["files"].get(name) != item["base"]:
            raise ValueError("The base record changed. Rebuild the proposal against the current revision")
        if old == new:
            raise ValueError("A proposed change must change the record")
        if new is None:
            updated.pop(name)
        else:
            updated[name] = text(new, "record", MAX_NOTE)
        if name in head.get("governing", []) and "decisions" not in item:
            raise ValueError("List each change to this governing record before saving")
        if "decisions" in item:
            governing(item["decisions"], old or "", new or "")
        pairs.append({**item, "before": old, "after_sha256": None if new is None else sha(new.encode())})
    return updated, pairs


def checked_paths(private):
    """Return validated managed file paths. Unknown files remain visible to the ordinary checker."""
    if not os.environ.get("ORYX_WORKSPACE") or not (private / ".oryx").is_dir():
        return set()
    ws = Workspace()
    if ws.root != private:
        raise ValueError("Cannot audit another Workspace")
    known = set()
    def remember(path):
        if path.is_symlink() or not path.is_file() or path.stat().st_nlink != 1:
            raise ValueError("Unexpected file type in local review state")
        known.add(path.relative_to(private).as_posix())
    if (ws.official / HEAD).exists():
        head, _ = ws.snapshot()
        for name in [HEAD, *head["files"]]:
            remember(ws.official / name)
    from . import handoff
    from oryx.workspace import layout
    handoff_head = private / layout.work_path("workspace/handoffs", private) / HEAD
    if handoff_head.exists():
        handoff.receipt_state(ws)
        remember(handoff_head)
    if ws.staging.exists():
        checked_directory(ws.staging)
        for path in ws.staging.iterdir():
            if path.suffix == ".json" and HEX.fullmatch(path.stem):
                request = ws.proposal(path.stem)
                if not isinstance(request, dict):
                    raise ValueError("Invalid staged review request")
                remember(path)
    if not ws.state.exists():
        return known
    checked_directory(ws.state, private=True)
    lock = ws.state / "writer.lock"
    if lock.exists():
        remember(lock)
    discarded = ws.state / "discarded"
    if discarded.exists():
        checked_directory(discarded, private=True)
        for path in discarded.iterdir():
            if HEX.fullmatch(path.name):
                remember(path)
                record = json.loads(path.read_bytes(), object_pairs_hook=unique)
                if record != {"id": path.name, "actor": "pm-local-review"} and record != {"id": path.name, "actor": "pm-local-editor"}:
                    raise ValueError("Invalid discard receipt")
    restored = ws.state / "restored.json"
    if restored.exists():
        from . import work
        work.restored_bindings(ws)
        remember(restored)
    transactions = ws.state / "transactions"
    if transactions.exists():
        from . import work
        checked_directory(transactions, private=True)
        for folder in transactions.iterdir():
            if HEX.fullmatch(folder.name):
                work.state(ws, folder.name, ws.proposal(folder.name))
                for name in ("content", "intent.json", "done.json"):
                    if (folder / name).exists():
                        remember(folder / name)
    generations = ws.state / "generations"
    if generations.exists():
        checked_directory(generations, private=True)
        for folder in generations.iterdir():
            if not re.fullmatch(r"[0-9a-f]{32}", folder.name):
                continue
            checked_directory(folder)
            names = set(os.listdir(folder))
            if HEAD in names:
                fd = os.open(folder, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                try:
                    head = json.loads(read_fd(fd, HEAD, MAX_METADATA), object_pairs_hook=unique)
                finally:
                    os.close(fd)
                if "files" in head:
                    data, _ = ws.snapshot(folder)
                    for name in [*data["files"], HEAD]:
                        remember(folder / name)
                    continue
                if set(head) != {"workspace", "receipts"} or head["workspace"] != ws.identity:
                    raise ValueError("Invalid handoff preimage metadata")
                remember(folder / HEAD)
            if "index.json" in names:
                remember(folder / "index.json")
                parsed = json.loads((folder / "index.json").read_bytes(), object_pairs_hook=unique)
                if not isinstance(parsed, dict) or set(parsed) != {"work", "grants"}:
                    raise ValueError("Invalid handoff preimage")
    return known
