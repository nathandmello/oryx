"""Bind bounded, purpose-specific reads to their original source and revision."""

from hashlib import sha256
import json
import posixpath
from pathlib import Path
import sys
import re
from urllib.parse import unquote, urlsplit
from uuid import uuid4

import layout
import pm_profile
import storage

# Legacy script callers load tools directly; resolve the package in this Core.
_src = str(Path(__file__).resolve().parents[3] / "src")
if _src not in sys.path:
    sys.path.insert(0, _src)
from oryx.capabilities.evidence import LIMIT, local_name, read as read_local, target as source_target

GRANTS = ".state/ingestion-grants.json"
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
    try:
        return local_name(ref) is not None
    except ValueError:
        return False


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
    local_name(reference)  # Reject ineligible local files before considering supplied text.
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
    name = local_name(info["reference"])
    if name is not None:
        raw, after, ends_at_eof = read_local(private, name, info["coverage"], info["offset"], supplied, length)
        local_version = fingerprint([after.st_size, after.st_mtime_ns])
    if not raw:
        raise ValueError("Inspect the authorized original passage")
    checksum = digest(raw)
    if info["coverage"] == "partial" and info["revision"] is None and local_version is None:
        raise ValueError("Identify the remote source revision for this partial read")
    return {**info, "revision": info["revision"] or local_version or checksum, "checksum": checksum,
            "length": len(raw), "local_version": local_version, "ends_at_eof": ends_at_eof}, raw.decode()


def capture_material(private, source, binding=None):
    """Verify a local citation for a primary workflow and retain only its bounded locator."""
    name = local_name(source["reference"])
    if name is None or source["coverage"] == "unavailable":
        if binding is not None:
            raise ValueError("The reviewed local citation changed")
        return source.get("text"), None
    options = source.get("ingestion", {})
    if not isinstance(options, dict):
        raise ValueError("Invalid evidence locator")
    reference = source_target(source["reference"])
    source_id = options.get("source_id", fingerprint(reference))
    offset = options.get("offset", 0)
    length = None
    if binding is not None:
        if (not isinstance(binding, dict) or set(binding) != {"reference", "source_id", "offset", "length", "digest", "version"}
                or binding["reference"] != reference):
            raise ValueError("Invalid reviewed local citation")
        source_id, offset, length = binding["source_id"], binding["offset"], binding["length"]
    if not isinstance(source_id, str) or not IDENT.fullmatch(source_id):
        raise ValueError("Use a stable source identifier")
    if revoked(state(private)[1], {"reference": reference, "source_id": source_id}):
        raise ValueError("The reviewed source grant was revoked")
    raw, stat, _ = read_local(private, name, source["coverage"], offset, source.get("text"), length)
    current = {"source_id": source_id, "reference": reference, "offset": offset, "length": len(raw),
               "digest": digest(raw), "version": fingerprint([stat.st_size, stat.st_mtime_ns])}
    if binding is not None and current != binding:
        raise ValueError("The original source revision changed. Review the passage again")
    return raw.decode(), current


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
    local = local_name(info["reference"])
    fingerprints = {fingerprint(info["reference"])}
    if local:
        fingerprints.add(fingerprint(local))
    return (info["source_id"] in doc["revoked"] or bool(fingerprints.intersection(doc["revoked"]))
            or any(fingerprints.intersection(refs) for refs in doc["revoked"].values()))


def denied_references(private):
    revoked_sources = state(private)[1]["revoked"]
    return frozenset(revoked_sources).union(*(refs for refs in revoked_sources.values()))


def withheld(denied, reference, record=None):
    if not denied:
        return False
    target = source_target(reference)
    values = {target}
    parsed = urlsplit(target)
    if not parsed.scheme and not parsed.netloc:
        path = unquote(parsed.path)
        values.add(path)
        if record:
            values.add(posixpath.normpath(posixpath.join(posixpath.dirname(record), path)))
    return any(fingerprint(value) in denied for value in values)


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


def revoke(private, source_id, *, restore=False, reference=None):
    if not IDENT.fullmatch(source_id):
        raise ValueError("Use the source ID from its review")
    canonical = local_name(reference) if reference is not None else None
    if reference is not None and canonical is None:
        raise ValueError("Supply a local document for an explicit revocation path")
    with storage.writer_lock(private):
        original, doc = state(private)
        if restore:
            doc["revoked"].pop(source_id, None)
        else:
            refs = []
            for grant in doc["grants"].values():
                if grant["source_id"] == source_id:
                    refs.append(fingerprint(grant["reference"]))
                    local = local_name(grant["reference"])
                    if local:
                        refs.append(fingerprint(local))
            if canonical:
                refs.append(fingerprint(canonical))
            doc["revoked"][source_id] = sorted(set(refs + doc["revoked"].get(source_id, [])))
            doc["grants"] = {k: v for k, v in doc["grants"].items() if v["source_id"] != source_id}
        write_state(private, original, doc)
    return {"source_id": source_id, "status": "restored" if restore else "revoked"}


def reread(private, grant, purpose, source=None):
    """Check the caller’s current remote read or reopen the original local passage."""
    grant = {k: v for k, v in grant.items() if k != "ticket"}
    if grant["purposes"] != [purpose] or grant["retention"] != "review":
        raise ValueError("Source use is outside this purpose")
    if source is None:
        if not local_ref(grant["reference"]):
            raise ValueError("Obtain a fresh authorized read of the original passage using an available reader")
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
