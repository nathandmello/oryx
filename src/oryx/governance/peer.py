"""A local customer peer. The service owns all Git repositories and trusted ACLs."""
from contextlib import contextmanager
from datetime import date, datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import sqlite3
import stat
import subprocess
import tempfile

from .common import canonical, decode, digest, identifier, record_id, shape

RIGHTS = {"read", "propose", "review", "merge", "policy", "publish"}
PARENTS = {"company": {None}, "function": {"company"}, "team": {"company", "function"}, "user": {"team", "function", "company"}}
AREAS = {"record": "context/records", "metric": "context/metrics", "report": "context/reports", "policy": ".oryx/policies"}


def checked_roster(config):
    shape(config, ("organization", "principals", "scopes", "datasets"))
    identifier(config["organization"])
    if not all(isinstance(config[k], dict) for k in ("principals", "scopes", "datasets")):
        raise ValueError("Invalid customer enrollment")
    actors = set()
    for uid, user in config["principals"].items():
        if not uid.isdecimal() or str(int(uid)) != uid:
            raise ValueError("Use kernel UID mappings")
        shape(user, ("actor", "mode"))
        actors.add(identifier(user["actor"]))
        if user["mode"] not in {"agent", "human"}:
            raise ValueError("Unknown customer principal mode")
    scopes = config["scopes"]
    if sum(v.get("type") == "company" for v in scopes.values()) != 1:
        raise ValueError("A registered organization needs one authoritative company scope")
    for key, scope in scopes.items():
        identifier(key)
        shape(scope, ("type", "parent", "roles"))
        parent = scope["parent"]
        if parent is not None and parent not in scopes:
            raise ValueError("Unregistered parent scope")
        parent_type = scopes[parent]["type"] if parent is not None else None
        if scope["type"] not in PARENTS or parent_type not in PARENTS[scope["type"]]:
            raise ValueError("Invalid scope hierarchy")
        if not isinstance(scope["roles"], dict):
            raise ValueError("Expected per-actor scope grants")
        for actor, rights in scope["roles"].items():
            if actor not in actors or not isinstance(rights, list) or not set(rights) <= RIGHTS:
                raise ValueError("Unregistered scope grant")
    for key, data in config["datasets"].items():
        identifier(key)
        shape(data, ("readers",))
        if not isinstance(data["readers"], list) or not set(data["readers"]) <= actors:
            raise ValueError("Invalid source permissions")
    return config


def check_private(path, directory):
    info = path.lstat()
    expected = stat.S_ISDIR if directory else stat.S_ISREG
    if (path.resolve() != path or not expected(info.st_mode) or info.st_uid != os.geteuid()
            or info.st_mode & 0o077 or (not directory and info.st_nlink != 1)):
        raise ValueError("The customer service requires its own private, unredirected storage")
    return path


class GitRecords:
    def __init__(self, root, scope):
        self.path = root / "repositories" / (identifier(scope) + ".git")

    def git(self, *args, data=None, index=None, optional=False):
        env = {"PATH": os.defpath, "HOME": str(self.path.parent.parent), "GIT_CONFIG_NOSYSTEM": "1",
               "GIT_CONFIG_GLOBAL": os.devnull, "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C",
               "GIT_AUTHOR_NAME": "Oryx customer peer", "GIT_AUTHOR_EMAIL": "peer@localhost",
               "GIT_COMMITTER_NAME": "Oryx customer peer", "GIT_COMMITTER_EMAIL": "peer@localhost"}
        if index:
            env["GIT_INDEX_FILE"] = str(index)
        proc = subprocess.run(["git", "--no-pager", "--git-dir", str(self.path), "-c", "core.hooksPath=/dev/null", *args],
                              input=data, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, timeout=30)
        if proc.returncode:
            if optional and proc.returncode == 1:
                return None
            raise ValueError("Customer Git operation could not verify its expected state")
        return proc.stdout

    def initialize(self):
        if self.path.exists():
            raise ValueError("Customer repository already exists")
        self.git("init", "--bare", "--initial-branch=main")
        tree = self.git("mktree", data=b"").strip().decode()
        first = self.git("commit-tree", tree, data=b"Initialize customer scope\n").strip().decode()
        self.git("update-ref", "refs/heads/main", first, "0" * len(first))

    def ref(self, name="refs/heads/main"):
        value = self.git("rev-parse", "--verify", "--quiet", name, optional=True)
        return value.strip().decode() if value is not None else None

    def get(self, revision, path):
        row = self.git("ls-tree", "-z", revision, "--", path)
        if not row:
            return None
        head, actual = row.rstrip(b"\0").split(b"\t", 1)
        parts = head.split()
        if actual.decode() != path or len(parts) != 3 or parts[:2] != [b"100644", b"blob"]:
            raise ValueError("Unsupported customer record type")
        return decode(self.git("cat-file", "blob", parts[2].decode()))

    def stage(self, base, path, value, change):
        with tempfile.TemporaryDirectory(dir=self.path.parent.parent) as folder:
            index = Path(folder) / "index"
            self.git("read-tree", base, index=index)
            blob = self.git("hash-object", "-w", "--stdin", data=canonical(value)).strip().decode()
            self.git("update-index", "--add", "--cacheinfo", f"100644,{blob},{path}", index=index)
            tree = self.git("write-tree", index=index).strip().decode()
            return self.git("commit-tree", tree, "-p", base, data=("Reviewed proposal " + change + "\n").encode()).strip().decode()

    def paths(self, revision):
        return [p.decode() for p in self.git("ls-tree", "-r", "--name-only", "-z", revision).split(b"\0") if p]

    def contains(self, earlier, ref):
        return self.git("merge-base", "--is-ancestor", earlier, ref, optional=True) is not None


def storage_path(kind, name):
    if kind not in AREAS:
        raise ValueError("Unsupported governed record kind")
    return AREAS[kind] + "/" + digest(record_id(name).encode()) + ".json"


SCHEMA = """
CREATE TABLE approvals(digest TEXT, actor TEXT, scope TEXT, PRIMARY KEY(digest, actor));
CREATE TABLE proposals(id TEXT PRIMARY KEY, scope TEXT, actor TEXT, base TEXT, candidate TEXT, body TEXT, status TEXT,
                       reviewer TEXT, reviewed_revision TEXT);
CREATE TABLE owners(id TEXT PRIMARY KEY, scope TEXT, revision TEXT);
CREATE TABLE receipts(id TEXT PRIMARY KEY, effect TEXT, scope TEXT, revision TEXT, stamp TEXT);
CREATE TABLE pages(id TEXT PRIMARY KEY, scope TEXT, record TEXT, source_rev TEXT, page_rev INTEGER, body TEXT, updated TEXT, live INTEGER, actor TEXT, audience TEXT, delivered_rev INTEGER, source_updated TEXT);
CREATE TABLE deliveries(id TEXT PRIMARY KEY, scope TEXT, actor TEXT, source_rev TEXT, body TEXT, stamp TEXT, audience TEXT, source_updated TEXT);
CREATE TABLE replicas(scope TEXT PRIMARY KEY, revision TEXT, previous TEXT);
"""


def initialize(root, config):
    root = Path(root).absolute()
    checked_roster(config)
    if root.resolve()!=root or root.exists() or not root.parent.is_dir():
        raise ValueError("Select an unused, canonical customer store location")
    # Provision out of sight so failed or concurrent initialization cannot present a partial store.
    with tempfile.TemporaryDirectory(dir=root.parent,prefix=".oryx-setup-") as stage:
        prepared=Path(stage)/"peer"
        prepared.mkdir(mode=0o700)
        _initialize_files(prepared,config)
        os.rename(prepared,root)


def _initialize_files(root,config):
    check_private(root, True)
    roster = root / "authority.json"
    with roster.open("xb") as stream:
        os.fchmod(stream.fileno(), 0o600)
        stream.write(canonical(config))
    for directory in ("repositories", "datasets"):
        (root / directory).mkdir(mode=0o700)
    with sqlite3.connect(root / "peer.sqlite") as db:
        db.executescript(SCHEMA)
    for scope in config["scopes"]:
        GitRecords(root, scope).initialize()


class Peer:
    def __init__(self, root):
        self.root = check_private(Path(root).absolute(), True)

    @contextmanager
    def operation(self, uid, organization):
        with (self.root / "operation.lock").open("a+b") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            config = checked_roster(decode(check_private(self.root / "authority.json", False).read_bytes()))
            user = config["principals"].get(str(uid))
            if not user or config["organization"] != organization or uid == os.geteuid():
                raise PermissionError("Customer peer cannot verify this separate acting principal")
            db = sqlite3.connect(self.root / "peer.sqlite", isolation_level=None)
            try:
                db.row_factory = sqlite3.Row
                ctx = Context(self.root, config, user, db)
                from oryx.sharing.effects import reconcile_merge
                for entry in db.execute("SELECT * FROM proposals WHERE status='merging'").fetchall():
                    reconcile_merge(ctx, entry)
                yield ctx
            finally:
                db.close()


class Context:
    def __init__(self, root, config, user, db):
        self.root, self.config, self.user, self.db = root, config, user, db
        self.actor = user["actor"]

    def rights(self, scope, actor=None):
        return set(self.config["scopes"].get(scope, {}).get("roles", {}).get(actor or self.actor, []))

    def require(self, scope, *rights, actor=None):
        identifier(scope)
        if not set(rights) <= self.rights(scope, actor):
            raise PermissionError("Current customer scope does not grant this operation")

    def human(self):
        if self.user["mode"] != "human":
            raise PermissionError("A separate PM-controlled identity must perform this operation")

    def audience(self, scope):
        return sorted(a for a, r in self.config["scopes"][scope]["roles"].items() if "read" in r)

    def lineage(self, scope):
        path = []
        while scope is not None:
            path.append(scope)
            scope = self.config["scopes"][scope]["parent"]
        return list(reversed(path))

    def git(self, scope):
        return GitRecords(self.root, scope)

    def scope(self, scope):
        self.require(scope, "read")
        return {"organization": self.config["organization"], "scope": scope, "type": self.config["scopes"][scope]["type"],
                "parent": self.config["scopes"][scope]["parent"], "revision": self.git(scope).ref(),
                "actor": self.actor, "rights": sorted(self.rights(scope)), "audience": self.audience(scope)}

    def deliverable(self, scope, value, trail=()):
        if self.actor not in value["reviewed_audience"]:
            raise PermissionError("The current reader is outside the approved record audience")
        key = (scope, value["kind"], value["id"])
        if key in trail or len(trail) >= 16:
            raise ValueError("Circular or unbounded governed references")
        for ref in value["references"]:
            self.require(ref["scope"], "read")
            source = self.git(ref["scope"])
            target = source.get(source.ref(), storage_path(ref["kind"], ref["id"]))
            if target is None or digest(canonical(target)) != ref["revision"]:
                raise ValueError("Referenced source changed or is unavailable; hold dependent delivery")
            self.deliverable(ref["scope"], target, (*trail, key))

    def record(self, scope, kind, name, revision=None):
        self.require(scope, "read")
        git = self.git(scope)
        head = git.ref()
        if revision is not None:
            if not isinstance(revision, str) or len(revision) not in (40, 64) or any(c not in "0123456789abcdef" for c in revision):
                raise ValueError("Invalid record commit")
            if not git.contains(revision, head):
                raise ValueError("Revision is outside the verified official history")
        value = git.get(revision or head, storage_path(kind, name))
        if value is None:
            raise ValueError("No official record with this identity in this scope")
        self.deliverable(scope,value)
        return {"scope": scope, "commit": revision or head, "revision": digest(canonical(value)), "record": value}

    def sync(self, scope):
        info = self.scope(scope)
        git = self.git(scope)
        head = info["revision"]
        paths = git.paths(head)
        records = []
        for path in paths:
            result = git.get(head, path)
            if storage_path(result["kind"], result["id"]) != path:
                raise ValueError("Unverified official customer repository entry")
            self.deliverable(scope,result)
            records.append(result)
        if len(canonical(records)) > 900_000:
            raise ValueError("Maintain a smaller scoped replica before syncing")
        # The server owns the replica ref and switches only after validating the complete tree.
        old = git.ref("refs/oryx/replica")
        if old != head:
            git.git("update-ref", "refs/oryx/replica", head, old or "0" * len(head))
        self.db.execute("INSERT INTO replicas VALUES(?,?,?) ON CONFLICT(scope) DO UPDATE SET previous=CASE WHEN revision != excluded.revision THEN revision ELSE previous END, revision=excluded.revision",
                        (scope, head, old))
        self.receipt(digest(canonical([self.actor,scope,head,"sync"])), "sync", scope, head)
        from oryx.sharing.effects import refresh_pages
        publications = refresh_pages(self, scope)
        return {"scope": scope, "revision": head, "records": records, "publications": publications}

    def metric(self, scope, name):
        self.require(scope, "read")
        chosen = binding = None
        deps = []
        for level in self.lineage(scope):
            self.require(level, "read")
            git = self.git(level)
            head = git.ref()
            definition = git.get(head, storage_path("metric", name))
            policy = git.get(head, storage_path("policy", name))
            if definition:
                self.deliverable(level,definition)
                if binding:
                    raise ValueError("A lower-scope definition conflicts with a binding rule; refer to its owner")
                chosen = {"owner": level, "window_days": definition["content"]["window_days"]}
                deps.append([level, "metric", digest(canonical(definition))])
            if policy:
                self.deliverable(level,policy)
                if binding or not chosen or chosen["owner"] != level:
                    raise ValueError("Conflicting or unverified binding rule; refer to its owner")
                binding = level
                deps.append([level, "policy", digest(canonical(policy))])
                for child in self.lineage(scope):
                    if child in policy["content"]["exceptions"]:
                        chosen["window_days"] = policy["content"]["exceptions"][child]
        if chosen is None:
            raise ValueError("The metric owner and definition are unavailable")
        return {**chosen, "metric": name, "scope": scope, "rule_owner": binding,
                "revision": digest(canonical([scope, name, deps])), "dependencies": deps}

    def report(self, owner, name, as_of):
        report = self.record(owner, "report", name)
        recipe = report["record"]["content"]
        if recipe.get("operation") != "count-events":
            raise ValueError("Opaque calculation needs definition-owner review")
        metric = self.metric(recipe["scope"], recipe["metric"])
        if metric["revision"] != recipe["dependency_revision"] or metric["window_days"] != recipe["window_days"]:
            raise ValueError(f"Stale report; refer its correction to report owner {owner}")
        data = self.config["datasets"].get(recipe["dataset"], {})
        if self.actor not in data.get("readers", []):
            raise PermissionError("Acting user lacks source access")
        end = date.fromisoformat(as_of)
        # Source access occurs only after policy, recipe and effective source authorization.
        path = check_private(self.root / "datasets" / (identifier(recipe["dataset"]) + ".json"), False)
        events = decode(path.read_bytes())
        if not isinstance(events, list):
            raise ValueError("Unreadable structured source")
        days = [(end - date.fromisoformat(d)).days for d in events]
        return {"value": sum(0 <= d < metric["window_days"] for d in days), "unit": "events", "as_of": as_of,
                "report_owner": owner, "report_revision": report["revision"], "metric": metric}

    def receipt(self, key, effect, scope, revision):
        stamp = datetime.now(timezone.utc).isoformat()
        self.db.execute("INSERT OR IGNORE INTO receipts VALUES(?,?,?,?,?)", (key, effect, scope, revision, stamp))
