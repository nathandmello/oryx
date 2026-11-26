"""Bind bounded, purpose-specific reads to their original source and revision."""

from hashlib import sha256
import json
import os
from pathlib import PurePosixPath
import re
from urllib.parse import urlsplit
from uuid import uuid4

import layout
import pm_profile
import storage

GRANTS = ".state/ingestion-grants.json"
LIMIT = 128 * 1024
MAX_GRANTS = 512
DIGEST = re.compile(r"[a-f0-9]{64}")
IDENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}")
OPTIONAL = {"source_id", "revision", "event_id", "coverage", "offset", "purposes", "text", "retention", "subject"}
PRIVATE_TURN = re.compile(r"\boff[ -]the[ -]record\b|\b(?:chat|summary)[ -]only\b|"
                          r"\b(?:do not|don['’]t|never)\s+(?:(?:use|save|retain|record)\b.{0,56}\bprofile|"
                          r"profile|(?:save|remember|retain|record)\s+this)\b", re.I)


def digest(value):
    return sha256(value).hexdigest()


def fingerprint(value):
    return digest(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())


def line(value, field):
    if not isinstance(value, str) or not value.strip() or value.splitlines() != [value] or len(value) > 1200:
        raise ValueError(f"Supply a bounded single-line {field}")
    return value.strip()


def source_target(reference):
    link = re.fullmatch(r"\[[^\]\n]+\]\((<[^>\n]+>|[^\s)]+)\)", reference)
    return link[1].strip("<>") if link else reference


def safe_url(value):
    parts = urlsplit(value)
    return (parts.scheme == "https" and bool(parts.hostname) and parts.username is None
            and not re.search(r"[\s\\]|%(?:2e|2f|5c|25)", value, re.I)
            and not {".", ".."}.intersection(parts.path.split("/")))


def within_scope(scope, reference):
    actual, allowed = source_target(reference), source_target(scope)
    if actual == allowed:
        return True
    if not safe_url(actual) or not safe_url(allowed):
        return False
    base, candidate = urlsplit(allowed), urlsplit(actual)
    return (not base.query and not base.fragment and base.path.endswith("/")
            and base.netloc == candidate.netloc and candidate.path.startswith(base.path))


def local_ref(ref):
    """Only named evidence documents inside Studio. Never follow links or read configuration."""
    path = PurePosixPath(ref)
    return (path.parts[:1] in (("context",), ("workspace",)) and path.as_posix() == ref
            and path.suffix.lower() in {".md", ".txt"} and not {"secrets", "customizations", "profiles"}.intersection(path.parts)
            and not any(part.startswith(".") or not re.fullmatch(r"[\w -]+(?:\.[\w-]+)*", part)
                        for part in path.parts))


def retainable(ref):
    if local_ref(ref) or re.fullmatch(r"(?:chat|meeting|article|document|message|transcript|email|minutes|wiki|thread|interview|note):[A-Za-z0-9._-]{1,96}", ref):
        return True
    return bool(safe_url(ref) and not urlsplit(ref).query and not urlsplit(ref).fragment)


def metadata(value):
    required = {"kind", "scope", "reference", "authorized"}
    if not isinstance(value, dict) or not required <= value.keys() <= required | OPTIONAL:
        raise ValueError("A source needs kind, reference, scope and current authorization")
    reference = source_target(line(value["reference"], "source reference"))
    scope = line(value["scope"], "approved source scope")
    if reference.startswith(("context/", "workspace/")) and not local_ref(reference):
        raise ValueError("Use an eligible private evidence document")
    if value["authorized"] is not True or not within_scope(scope, reference):
        raise ValueError("Source access is unavailable or outside the current grant")
    purposes = value.get("purposes", [])
    if (not isinstance(purposes, list) or len(purposes) > 8
            or not all(isinstance(p, str) and layout.SLUG.fullmatch(p) and len(p) <= 64 for p in purposes)):
        raise ValueError("List each permitted workflow purpose explicitly")
    coverage = value.get("coverage", "read")
    retention = value.get("retention", "chat-only")
    offset = value.get("offset", 0)
    if (coverage not in ("read", "partial", "unavailable") or retention not in ("review", "chat-only")
            or type(offset) is not int or offset < 0 or offset > 2**40 or coverage == "read" and offset != 0):
        raise ValueError("Check coverage, retention and UTF-8 byte offset")
    source_id = value.get("source_id", fingerprint(reference))
    event = value.get("event_id", source_id)
    revision = value.get("revision")
    for identifier in [source_id, event, *([revision] if revision is not None else [])]:
        if not isinstance(identifier, str) or not IDENT.fullmatch(identifier):
            raise ValueError("Use a stable source, event or revision identifier")
    subject = value.get("subject", "unknown")
    if not isinstance(subject, str) or not (subject == "unknown" or re.fullmatch(
            r"product/[a-z0-9]+(?:-[a-z0-9]+)*(?:/(?:area|initiative)/[a-z0-9]+(?:-[a-z0-9]+)*)?", subject)):
        raise ValueError("Use the product, area or initiative authorized for this passage")
    return {"kind": layout.slug(value["kind"]), "reference": reference, "source_id": source_id, "event_id": event,
            "revision": revision, "coverage": coverage, "offset": offset, "retention": retention,
            "purposes": sorted(set(purposes)), "subject": subject}


def material(private, info, supplied, *, length=None):
    """Read only the granted byte range. The full source remains with its owner."""
    if supplied is not None and (not isinstance(supplied, str) or len(supplied) > LIMIT):
        raise ValueError("Use a bounded inspected passage")
    raw = supplied.encode() if supplied is not None else None
    if info["coverage"] == "unavailable" or raw is not None and len(raw) > LIMIT:
        raise ValueError("The source passage is unavailable or too large")
    local_version = None
    ends_at_eof = False
    if local_ref(info["reference"]):
        if info["coverage"] == "partial" and length is None and raw is None:
            raise ValueError("A partial local read needs a bounded passage")
        path = pm_profile.safe_path(private, info["reference"])
        with path.open("rb") as stream:
            stream.seek(info["offset"])
            limit = length if length is not None else len(raw or b"")
            before = os.fstat(stream.fileno())
            original = stream.read(limit if info["coverage"] == "partial" else LIMIT + 1)
            after = os.fstat(stream.fileno())
            if (before.st_mtime_ns, before.st_size) != (after.st_mtime_ns, after.st_size):
                raise ValueError("The original changed during its authorized read")
            local_version = fingerprint([after.st_size, after.st_mtime_ns])
            ends_at_eof = info["offset"] + len(original) == after.st_size
        if len(original) > LIMIT or raw is not None and original != raw:
            raise ValueError("The supplied passage differs from the authorized original")
        raw = original
    if not raw:
        raise ValueError("Inspect the authorized original passage")
    checksum = digest(raw)
    if info["coverage"] == "partial" and info["revision"] is None and local_version is None:
        raise ValueError("Identify the remote source revision for this partial read")
    return {**info, "revision": info["revision"] or local_version or checksum, "checksum": checksum,
            "length": len(raw), "local_version": local_version, "ends_at_eof": ends_at_eof}, raw.decode()


def valid_grant(key, grant):
    expected = {"kind", "reference", "source_id", "event_id", "revision", "coverage", "offset", "retention",
                "purposes", "subject", "checksum", "length", "local_version", "ends_at_eof", "ticket"}
    if not isinstance(grant, dict) or grant.keys() != expected or not isinstance(key, str) or key != fingerprint(grant):
        return False
    if (not isinstance(grant["ticket"], str) or not re.fullmatch(r"[a-f0-9]{32}", grant["ticket"])
            or not isinstance(grant["reference"], str) or not retainable(grant["reference"])
            or grant["retention"] != "review" or grant["coverage"] not in ("read", "partial")
            or type(grant["length"]) is not int or not 0 < grant["length"] <= LIMIT
            or not isinstance(grant["checksum"], str) or not DIGEST.fullmatch(grant["checksum"])
            or grant["local_version"] is not None and not DIGEST.fullmatch(str(grant["local_version"]))
            or type(grant["ends_at_eof"]) is not bool):
        return False
    fields = {k: grant[k] for k in ("kind", "reference", "source_id", "event_id", "revision", "coverage",
                                     "offset", "retention", "purposes", "subject")}
    try:
        metadata({**fields, "scope": grant["reference"], "authorized": True})
        return len(grant["purposes"]) == 1
    except (ValueError, TypeError):
        return False


def state(private):
    path = pm_profile.safe_path(private, GRANTS)
    original = path.read_bytes() if path.exists() else None
    doc = storage.json_input(original) if original is not None else {"grants": {}, "revoked": {}}
    if (not isinstance(doc, dict) or doc.keys() != {"grants", "revoked"} or not isinstance(doc["grants"], dict)
            or not isinstance(doc["revoked"], dict) or len(doc["grants"]) > MAX_GRANTS
            or not all(valid_grant(k, v) for k, v in doc["grants"].items())
            or not all(isinstance(i, str) and IDENT.fullmatch(i) and isinstance(refs, list) and
                       all(isinstance(r, str) and DIGEST.fullmatch(r) for r in refs)
                       for i, refs in doc["revoked"].items())):
        raise ValueError("Invalid optional source review grants")
    return original, doc


def write_state(private, original, doc):
    storage.replace_text(pm_profile.safe_path(private, GRANTS), original, json.dumps(doc, ensure_ascii=False) + "\n")


def revoked(doc, info):
    return (info["source_id"] in doc["revoked"]
            or any(fingerprint(info["reference"]) in refs for refs in doc["revoked"].values()))


def superseded(other, info):
    same = other["source_id"] == info["source_id"] and other["reference"] == info["reference"]
    changed = other["revision"] != info["revision"] or other["local_version"] != info["local_version"]
    same_range = (other["coverage"], other["offset"], other["length"]) == (info["coverage"], info["offset"], info["length"])
    return same and (changed or same_range and other["checksum"] != info["checksum"])


def invalidate_changed(private, info):
    # New content can remove the only relevant claim. Invalidate older grants even on an empty pass.
    _, doc = state(private)
    if not any(superseded(other, info) for other in doc["grants"].values()):
        return
    with storage.writer_lock(private):
        original, doc = state(private)
        doc["grants"] = {k: other for k, other in doc["grants"].items() if not superseded(other, info)}
        write_state(private, original, doc)


def remember(private, info, purpose):
    if purpose not in info["purposes"] or not retainable(info["reference"]) or info["retention"] != "review":
        return None
    grant = {**info, "purposes": [purpose]}
    with storage.writer_lock(private):
        original, doc = state(private)
        if revoked(doc, info):
            return None
        rows = doc["grants"]
        for key, other in list(rows.items()):
            if other.keys() == grant.keys() | {"ticket"} and all(other[k] == v for k, v in grant.items()):
                return key
            if superseded(other, grant):
                del rows[key]
        if len(rows) >= MAX_GRANTS:
            del rows[next(iter(rows))]
        # A fresh permission after revocation cannot reactivate an obsolete review.
        grant["ticket"] = uuid4().hex
        key = fingerprint(grant)
        rows[key] = grant
        write_state(private, original, doc)
    return key


def revoke(private, source_id, *, restore=False):
    if not IDENT.fullmatch(source_id):
        raise ValueError("Use the source ID from its review")
    with storage.writer_lock(private):
        original, doc = state(private)
        if restore:
            doc["revoked"].pop(source_id, None)
        else:
            refs = [fingerprint(v["reference"]) for v in doc["grants"].values() if v["source_id"] == source_id]
            doc["revoked"][source_id] = sorted(set(refs + doc["revoked"].get(source_id, [])))
            doc["grants"] = {k: v for k, v in doc["grants"].items() if v["source_id"] != source_id}
        write_state(private, original, doc)
    return {"source_id": source_id, "status": "restored" if restore else "revoked"}


def reread(private, grant, purpose, source=None):
    """Connector reads arrive through the caller. The stored grant cannot supply remote text."""
    grant = {k: v for k, v in grant.items() if k != "ticket"}
    if grant["purposes"] != [purpose] or grant["retention"] != "review":
        raise ValueError("Source use is outside this purpose")
    if source is None:
        if not local_ref(grant["reference"]):
            raise ValueError("Obtain a fresh authorized read from the original conversation or connector")
        info = {k: v for k, v in grant.items() if k not in ("checksum", "length", "local_version", "ends_at_eof")}
        actual, text = material(private, info, None, length=grant["length"])
    else:
        info = metadata(source)
        if purpose not in info["purposes"] or info["retention"] != "review" or info["coverage"] != grant["coverage"]:
            raise ValueError("The current source grant no longer permits this review")
        info["purposes"] = [purpose]
        if any(info[k] != grant[k] for k in ("source_id", "event_id", "reference", "offset", "subject", "kind")):
            raise ValueError("The source identity or approved range changed")
        actual, text = material(private, info, source.get("text"), length=grant["length"])
    if actual != grant:
        raise ValueError("The source or its revision changed. Review the current passage again")
    return text
