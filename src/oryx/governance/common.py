"""Validated names, canonical commitments and bounded protocol records."""
import hashlib
import json
import re

LIMIT = 1024 * 1024
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
SHA = re.compile(r"[a-f0-9]{64}\Z")


def canonical(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def digest(value):
    return hashlib.sha256(value).hexdigest()


def identifier(value):
    if not isinstance(value, str) or not NAME.fullmatch(value) or ".." in value:
        raise ValueError("Invalid scope, actor or provider identifier")
    return value


def record_id(value):
    if not isinstance(value, str) or not value or len(value.encode()) > 256 or any(ord(ch) < 32 for ch in value):
        raise ValueError("Invalid record identity")
    return value


def shape(value, required, optional=()):
    if not isinstance(value, dict) or set(value) - set(required) - set(optional) or not set(required) <= set(value):
        raise ValueError("Request fields do not match this operation")
    return value


def decode(raw):
    if len(raw) > LIMIT:
        raise ValueError("Customer peer request exceeds its size limit")
    def pairs(items):
        out = {}
        for key, val in items:
            if key in out:
                raise ValueError("Duplicate JSON field")
            out[key] = val
        return out
    def invalid(_):
        raise ValueError("Nonfinite JSON input")
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)
