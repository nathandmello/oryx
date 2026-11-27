"""Disposable routing and embedding cache. Authoritative records stay in the workspace."""

from contextlib import contextmanager
from hashlib import sha256
import json
import os
from pathlib import Path
import stat
import tempfile

import storage

try:
    import sqlite3
except ImportError:  # Some Python distributions omit the optional SQLite extension.
    sqlite3 = None


def signature(path):
    info = path.stat()
    return f"{info.st_dev}/{info.st_ino}/{info.st_size}/{info.st_mtime_ns}/{info.st_ctime_ns}"


def cache_path(private):
    if os.name == "posix":
        root = Path(tempfile.gettempdir()).resolve() / f"pm-hub-context-{os.getuid()}"
        if root.is_relative_to(private) or root.is_relative_to(storage.core_for(private)):
            raise ValueError("Cache would be inside the installation")
        root.mkdir(mode=0o700, exist_ok=True)
        info = root.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError("Unavailable personal cache directory")
    else:
        local = os.environ.get("LOCALAPPDATA")
        if not local or Path.home().resolve() not in Path(local).resolve().parents:
            raise ValueError("Unavailable personal application directory")
        root = Path(local) / "PM Hub" / "Search"
        root.mkdir(parents=True, exist_ok=True)
        if root.resolve() != root:
            raise ValueError("Redirected cache directory")
    identity = private.stat()
    key = sha256(os.fsencode(private.resolve()) + f"/{identity.st_dev}/{identity.st_ino}".encode()).hexdigest()
    path = root / (key + "-v3.sqlite")
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ValueError("Redirected cache file")
    return path


def sealed(data, key):
    return sha256(key.encode() + data).digest() + data


def unpacked(data, key):
    if isinstance(data, bytes) and len(data) >= 32:
        value = data[32:]
        if sealed(value, key) == data:
            return value
    return None


class Index:
    def __init__(self, database=None):
        self.db = database
        self.present = set()
        self.partition = ""

    def restrict(self, scope, purpose):
        view = json.dumps([scope, purpose], sort_keys=True, separators=(",", ":"))
        self.partition = sha256(view.encode()).hexdigest() + ":"

    def execute(self, sql, args=()):
        if self.db is not None:
            try:
                return self.db.execute(sql, args).fetchall()
            except sqlite3.Error:
                pass
        return ()

    def metadata(self, name, stamp):
        self.present.add(name)
        for (data,) in self.execute("SELECT meta FROM files WHERE name=? AND stamp=?", (name, stamp)):
            try:
                value = json.loads(unpacked(data, name + stamp))
                if value is None or (isinstance(value, dict) and value.get("record") == name and
                                     {"kind", "title", "product", "area", "initiative", "parent", "company",
                                      "identifiers", "aliases", "providers", "areas", "id", "due", "leads", "reviewable", "journal"} <= value.keys()):
                    return True, value
            except (ValueError, TypeError):
                pass
        return False, None

    def store(self, name, stamp, meta):
        self.execute("INSERT OR REPLACE INTO files VALUES(?,?,?)", (name, stamp, sealed(json.dumps(meta).encode(), name + stamp)))

    def prune(self):
        for (name,) in list(self.execute("SELECT name FROM files")):
            if name not in self.present:
                self.execute("DELETE FROM files WHERE name=?", (name,))

    def projection(self, name, view):
        view = self.partition + view
        for (raw,) in self.execute("SELECT rows FROM notes WHERE name=? AND view=?", (name, view)):
            try:
                rows = json.loads(unpacked(raw, name + view))
                if isinstance(rows, list) and all(isinstance(row, list) and len(row) == 4 and
                                                  isinstance(row[0], str) and isinstance(row[1], str) and
                                                  isinstance(row[2], bool) and (row[3] is None or isinstance(row[3], str))
                                                  for row in rows):
                    return [{"record": name, "section": section, "text": text, "binding": binding,
                             **({"product_area": area} if area else {})} for section, text, binding, area in rows]
            except (ValueError, TypeError):
                pass
        return None

    def save_projection(self, name, view, rows):
        view = self.partition + view
        data = [[row["section"], row["text"], row["binding"], row.get("product_area")] for row in rows]
        self.execute("INSERT OR REPLACE INTO notes VALUES(?,?,?)", (name, view, sealed(json.dumps(data).encode(), name + view)))

    def vector(self, name, key):
        key = self.partition + key
        row = next(iter(self.execute("SELECT value FROM vectors WHERE name=? AND key=?", (name, key))), (None,))
        return unpacked(row[0], key)

    def save_vector(self, name, key, blob):
        key = self.partition + key
        self.execute("INSERT OR REPLACE INTO vectors VALUES(?,?,?)", (name, key, sealed(blob, key)))


@contextmanager
def opened(private, *, access_epoch=""):
    if sqlite3 is None:
        yield Index()
        return
    db = None
    path = None
    try:
        path = cache_path(private)
        db = sqlite3.connect(path, timeout=0)
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA secure_delete=ON")
        db.execute("CREATE TABLE IF NOT EXISTS access_epoch(value TEXT NOT NULL)")
        epoch = db.execute("SELECT value FROM access_epoch").fetchone()
        db.execute("CREATE TABLE IF NOT EXISTS files(name TEXT PRIMARY KEY, stamp TEXT, meta BLOB)")
        db.execute("CREATE TABLE IF NOT EXISTS notes(name TEXT PRIMARY KEY REFERENCES files ON DELETE CASCADE, "
                   "view TEXT, rows BLOB)")
        db.execute("CREATE TABLE IF NOT EXISTS vectors(name TEXT REFERENCES files ON DELETE CASCADE, "
                   "key TEXT, value BLOB, PRIMARY KEY(name,key))")
        if epoch != (access_epoch,):
            # Removing the parent also removes projections and embeddings. A locked
            # cache takes the no-cache path rather than serving an obsolete policy.
            db.execute("DELETE FROM files")
            db.execute("DELETE FROM access_epoch")
            db.execute("INSERT INTO access_epoch VALUES(?)", (access_epoch,))
    except (OSError, ValueError, sqlite3.Error) as error:
        if db is not None:
            db.close()
        db = None
        corrupt = (getattr(error, "sqlite_errorname", "") in {"SQLITE_NOTADB", "SQLITE_CORRUPT"}
                   or str(error) in {"file is not a database", "database disk image is malformed"})
        if corrupt and path is not None:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
    try:
        yield Index(db)
        if db is not None:
            try:
                db.commit()
            except sqlite3.Error:
                pass
    finally:
        if db is not None:
            db.close()
