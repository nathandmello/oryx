"""Track the one-time review of context created before evidence routing."""

import hashlib
import json
import os
import re
from pathlib import Path
from tempfile import NamedTemporaryFile

import records
import layout
import storage

LEDGER = ".hub-upgrades.json"
RULE = "record-filing-0.2"
TRANSACTIONS = "filing-transactions-0.2"


def scan_marker(private):
    path = private / ".git" / "pm-hub-inventory-record-filing-0.2"
    if path.resolve() != path:
        raise ValueError("Unsafe private inventory marker")
    return path


# Exact installed 0.1 paragraphs. Other private wording always stays under PM control.
STARTERS = {
    "README.md": (
        "Company context, product context, and strategy remain uncaptured. Start those activities in separate sessions, in that order.",
        "For first-time setup, start with company context, then product context and strategy. Reuse existing records when new evidence arrives."),
    "context/README.md": (
        "Company context remains uncaptured. Use [the company-context template](../../templates/company-context.md) and [the context rules](../../playbook/context.md).",
        "Start with `company.md`. Use [the context ingestion rules](../../playbook/context.md) to route supplied evidence and open questions."),
    "products/README.md": (
        "Product context and strategy remain uncaptured. Use [the product-context template](../../templates/product-context.md) and [the context rules](../../playbook/context.md).",
        "Use [the product template](../../templates/product-context.md) for standing product guidance. Link recurring initiative work to its product using [the initiative template](../../templates/initiative-context.md)."),
}


def encode(state):
    return json.dumps(state, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def fresh(private):
    storage.replace_text(private / LEDGER, None, encode({RULE: {}}))
    storage.replace_text(scan_marker(private), None, RULE)


def review_path(private, name, *, markdown=True):
    if not isinstance(name, str):
        raise ValueError("Expected a private Markdown path")
    path = private / name
    if (not name or Path(name).is_absolute() or
            Path(name).as_posix() != name or (markdown and path.suffix.lower() != ".md") or
            any(p.startswith(".") or p == "secrets" for p in Path(name).parts) or
            path.resolve() != path or (path.exists() and not path.is_file())):
        raise ValueError("Review paths must identify regular Markdown files inside the private workspace")
    return path


def installed_seed(private, name):
    seed = private.parent / "tools" / "workspace-seed"
    source = seed / name
    if not source.is_file():
        # This starter was retired when working artifacts moved under workspace/.
        return ""
    copies = {path: private / path.relative_to(seed) for path in seed.rglob("*") if path.is_file()}
    return records.retarget_links(source.read_text(encoding="utf-8"), source, private / name, private.parent, copies)


def candidates(private, inventory, *, restored_layout=False):
    found = {}
    for path in inventory(private):
        name = path.relative_to(private).as_posix()
        parts = Path(name).parts
        if (path.suffix.lower() != ".md" or path.resolve() != path or
                any(p.startswith(".") or p == "secrets" for p in parts) or not path.is_file()):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if (name in STARTERS or name == "workspace/README.md") and text and text == installed_seed(private, name):
            continue
        marker = records.MARKER.match(text)
        if restored_layout and (name == layout.PROFILE or "sources" in parts or layout.valid_work(name)
                                or (parts[0] == "context" and marker and
                                    not records.context_location(marker[1], name))):
            continue
        if name in STARTERS:
            reason = "Inspect the installed guide and preserve local additions"
        elif marker and marker[1] in records.KINDS:
            reason = f"Inspect the existing {marker[1]} record and its evidence"
        else:
            reason = "Identify this document's purpose, owner, sources, and incoming references"
        hint = "Unconfirmed"
        if parts[0] == "products" and len(parts) >= 3:
            hint = "/".join(parts[:4] if len(parts) >= 5 and parts[2] in {"initiatives", "areas"} else parts[:2])
        elif parts[0] == "context":
            hint = "Possible company scope; confirm from contents"
        found[name] = {"status": "pending", "note": reason, "owner_hint": hint, "digest": fingerprint(path)}
    return found


def fingerprint(path):
    if not path.exists():
        return "absent"
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_state(private):
    path = private / LEDGER
    if path.resolve() != path:
        raise ValueError("The private upgrade ledger must be a regular file")
    original = path.read_text(encoding="utf-8") if path.exists() else None
    state = json.loads(original) if original is not None else {}
    if not isinstance(state, dict) or not isinstance(state.get(RULE, {}), dict):
        raise ValueError("Invalid private upgrade ledger")
    transactions = state.get(TRANSACTIONS, {})
    if not isinstance(transactions, dict) or not all(
            re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", key) and isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value)
            for key, value in transactions.items()):
        raise ValueError("Invalid filing transaction ledger")
    for name, item in state.get(RULE, {}).items():
        review_path(private, name)
        if (not isinstance(item, dict) or item.get("status") not in ("pending", "waiting", "reviewed")
                or not isinstance(item.get("note"), str) or not item["note"].strip()):
            raise ValueError("Invalid context review entry")
    return original, state


def source_paths(private):
    import layout_upgrade
    state = read_state(private)[1]
    return ({name for name, item in state.get(RULE, {}).items() if item.get("role") == "source"}
            | set(layout_upgrade.receipt(private, state).get("sources", [])))


def run(private, inventory, *, prepare=False, record=None, outcome=None, digest=None, note=None):
    """Caller holds the private writer lock for updates. Preview never writes."""
    original, state = read_state(private)
    needs_setup = RULE not in state
    marker = scan_marker(private)
    items = state.setdefault(RULE, {})
    if needs_setup or not marker.exists():
        for name, candidate in candidates(private, inventory, restored_layout="purpose-layout-1" in state).items():
            items.setdefault(name, candidate)
    repaired = []
    if prepare and needs_setup:
        for name, (old, new) in STARTERS.items():
            if name not in items:
                continue
            target = review_path(private, name)
            original_text = target.read_bytes().decode("utf-8")
            lines = original_text.splitlines(keepends=True)
            matches = [i for i, line in enumerate(lines) if line.rstrip("\r\n") == old]
            if len(matches) == 1:
                backup(private, [name])
                i = matches[0]
                lines[i] = lines[i].replace(old, new, 1)
                storage.replace_text(target, original_text, "".join(lines))
                repaired.append(name)
                items[name]["digest"] = fingerprint(target)
                if "".join(lines).strip() in (new, installed_seed(private, name).strip()):
                    items[name] = {"status": "reviewed", "note": "Updated the exact 0.1 starter paragraph",
                                   "digest": fingerprint(target)}
    if any(value is not None for value in (record, outcome, digest, note)):
        layout_state = state.get("purpose-layout-1", {})
        retained = layout_state.get("retained", {})
        if ((record not in items and record not in retained) or outcome not in ("reviewed", "waiting", "source")
                or not isinstance(note, str) or not records.specific(note.strip()) or len(note.splitlines()) != 1):
            raise ValueError("Select a review item, outcome, current digest, and specific one-line evidence or blocker")
        if fingerprint(review_path(private, record, markdown=record not in retained)) != digest:
            raise ValueError("Record changed since review; inspect its current contents and digest")
        if record in items:
            items[record] = {"status": "reviewed" if outcome == "source" else outcome, "note": note, "digest": digest}
            if outcome == "source":
                items[record]["role"] = "source"
        if record in retained:
            retained[record]["disposition"] = {"status": outcome, "digest": digest, "note": note}
            if outcome == "source":
                layout_state["sources"] = sorted(set(layout_state.get("sources", [])) | {record})
    if prepare and encode(state) != original:
        storage.replace_text(private / LEDGER, original, encode(state))
    if prepare and not marker.exists():
        storage.replace_text(marker, None, RULE)
    outstanding = []
    for name, item in items.items():
        if item["status"] != "reviewed":
            outstanding.append(dict(item, path=name, digest=fingerprint(review_path(private, name))))
    return {"rule": RULE, "updated_guides": repaired, "needs_setup": needs_setup and not prepare, "outstanding": outstanding}


def backup(private, names):
    """Keep immutable original bytes in private Git metadata, including untracked files."""
    home = private / ".git" / "pm-hub-recovery" / RULE
    if home.resolve() != home:
        raise ValueError("Invalid private recovery directory")
    copies = {}
    for name in names:
        path = review_path(private, name)
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        target = home / digest / name
        if target.resolve() != target:
            raise ValueError("Invalid private recovery destination")
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            with NamedTemporaryFile(dir=target.parent, delete=False) as stream:
                staging = Path(stream.name)
                try:
                    stream.write(data)
                    stream.close()
                    os.link(staging, target)
                finally:
                    staging.unlink(missing_ok=True)
        if target.read_bytes() != data:
            raise ValueError("Private recovery copy does not match the original file")
        copies[name] = target.relative_to(private).as_posix()
    return copies
