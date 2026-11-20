"""Move identified private records to the purpose-first layout without guessing at loose notes."""

from html import unescape
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
from urllib.parse import quote, unquote, urlsplit, urlunsplit

import conversion
import layout
import metric_registry
import records
import storage
import upgrades

RULE = "purpose-layout-1"
PROFILE = "context/pm/context.md"
OLD_PROFILE = "context/pm-remit.json"
JOURNAL = "pm-hub-layout-pending.json"
GROUPS = layout.WORK_FOLDERS
GUIDES = {"README.md": "README.md", "context/README.md": "context/README.md",
          "products/README.md": "workspace/README.md"}
# Digests of the unmodified, installed 0.1 and 0.2 guides, after link retargeting.
OLD_GUIDES = {
    "6c07fc381fbb3f9656790ba756733d00ae1766f1683d0caf5754c4d6a8f7fee5",
    "9ab9fbd2d56aa26fe37d7ccf512b6320eac186b36f57aad4a18758a95f573885",
    "9ea0b2f822de6b25352815387db7a3e3529466ef5b47e24fba44676e6b06a04e",
    "b0b8137c7964f26a985e2b9b96819c3fdcd96cf2f4a447631981a12cabb7eb69",
    "4753a2d9cc26681edfb3ed50587fec9945ea8bc34ad38b4214132cb723ab4354",
    "4b5e5e2598c2cd567462a6b5c75aeeb5f89f47b154370977a5ad09f4939caa02",
    "bee0aac82e93b3f1be907d0ce487f6a8320c02ba9dc0dcf8673705124e52f6b7",
}
SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
# Keep the label, surrounding syntax, title, query string and anchor intact.
LINK = re.compile(r'\]\(\s*(?P<link><[^>\r\n]+>|(?:[^\s()]|\([^()\s]*\))+)(?=\s+["\']|\s*\))'
                  r'|^ {0,3}\[(?!\^)[^\]\r\n]+\]:\s*(?P<definition><[^>\r\n]+>|[^\s]+)', re.M)
TEXT_EXTENSIONS = {".md", ".markdown", ".txt", ".json", ".yml", ".yaml", ".html", ".csv", ".toml"}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def safe_path(private, name):
    path = private / name
    if (not name or Path(name).is_absolute() or Path(name).as_posix() != name or
            path.resolve() != path or private not in path.parents or
            any(p.startswith(".") or p == "secrets" for p in Path(name).parts) and name != upgrades.LEDGER):
        raise ValueError(f"Unsafe layout migration path: {name}")
    return path


def journal_path(private):
    path = private / ".git" / JOURNAL
    if path.resolve() != path or not path.parent.is_dir():
        raise ValueError("The layout journal requires a regular private Git directory")
    return path


def pending(private):
    return journal_path(private).is_file()


def receipt(private, state):
    saved = state.get(RULE)
    if saved is None:
        return {}
    if (not isinstance(saved, dict) or not {"version"} <= saved.keys() <= {"version", "retained", "sources"}
            or type(saved["version"]) != int or saved["version"] != 1 or not isinstance(saved.get("retained", {}), dict)
            or not isinstance(saved.get("sources", []), list)):
        raise ValueError("Invalid purpose layout ledger")
    for name in saved.get("sources", []):
        if not isinstance(name, str) or name == upgrades.LEDGER:
            raise ValueError("Invalid original source path in the layout ledger")
        safe_path(private, name)
    for name, row in saved.get("retained", {}).items():
        safe_path(private, name)
        if (not isinstance(row, dict) or not {"note", "digest"} <= row.keys() <= {"note", "digest", "destination", "disposition"}
                or not isinstance(row["note"], str) or not row["note"].strip()
                or not re.fullmatch(r"[a-f0-9]{64}|absent", str(row["digest"]))):
            raise ValueError("Invalid retained file entry in the layout ledger")
        if "destination" in row:
            if not isinstance(row["destination"], str):
                raise ValueError("Invalid destination in the layout ledger")
            safe_path(private, row["destination"])
        review = row.get("disposition")
        if review is not None and (not isinstance(review, dict) or set(review) != {"status", "digest", "note"}
                or review["status"] not in ("source", "reviewed", "waiting") or not isinstance(review["note"], str)
                or not review["note"].strip() or not re.fullmatch(r"[a-f0-9]{64}|absent", str(review["digest"]))):
            raise ValueError("Invalid review disposition in the layout ledger")
    return saved


def complete(private):
    return bool(receipt(private, upgrades.read_state(private)[1]))


def mark_fresh(private):
    original, state = upgrades.read_state(private)
    if not receipt(private, state):
        state[RULE] = {"version": 1}
        storage.replace_text(private / upgrades.LEDGER, original, upgrades.encode(state))


def entity(name):
    parts = Path(name).parts
    if parts[0] == "context" and (len(parts) == 2 or parts[1] == "records"):
        return "context/company"
    if len(parts) < 3 or parts[0] != "products" or not SLUG.fullmatch(parts[1]):
        return None
    if parts[2] in {"areas", "initiatives"}:
        if len(parts) < 5 or not SLUG.fullmatch(parts[3]):
            return None
        if parts[2] == "initiatives":
            return f"context/initiatives/{parts[3]}"
        return f"context/products/{parts[1]}/areas/{parts[3]}"
    return f"context/products/{parts[1]}"


def classify(name, text):
    owner = entity(name)
    canonical = {"context/company": "company-context"}
    if owner:
        expected = canonical.get(owner, "product-context")
        if "/areas/" in owner:
            expected = "product-area-context"
        if owner.startswith("context/initiatives/"):
            expected = "initiative-context"
        marker = records.MARKER.match(text.replace("\r\n", "\n", 1))
        if marker:
            kind = marker[1]
            if kind == expected:
                return owner + "/overview.md"
            if kind in GROUPS:
                identifier = records.work_state(text)[0].get("ID", "")
                if SLUG.fullmatch(identifier) and len(identifier) <= 80:
                    parts = Path(name).parts
                    scope = "company" if parts[0] == "context" else "product-" + parts[1]
                    if parts[2:3] in (("areas",), ("initiatives",)):
                        scope += ("-area-" if parts[2] == "areas" else "-initiative-") + parts[3]
                    return f"workspace/{GROUPS[kind]}/{scope}-{identifier}.md"
    return None


def referenced(private, origin, raw):
    try:
        url = urlsplit(unescape(raw.strip("<>")))
    except ValueError:
        return None
    if url.scheme or url.netloc or not url.path or Path(unquote(url.path)).is_absolute():
        return None
    return Path(os.path.abspath((private / origin).parent / unquote(url.path)))


def markdown_chunks(text):
    """Keep examples and verbatim quotations byte-for-byte, including Markdown-looking text."""
    fence = None
    for line in text.splitlines(keepends=True):
        found = re.match(r"^ {0,3}(`{3,}|~{3,})([^\r\n]*)", line)
        if found:
            marker, rest = found.groups()
            if fence is None:
                fence = marker
            elif marker[0] == fence[0] and len(marker) >= len(fence) and not rest.strip():
                fence = None
            yield "literal", line
        elif fence:
            yield "literal", line
        elif line.lstrip().startswith(">"):
            yield "quote", line
        else:
            offset = 0
            for span in re.finditer(r"(`+)(?!`)(.+?)(?<!`)\1(?!`)", line):
                yield "active", line[offset:span.start()]
                yield "literal", span[0]
                offset = span.end()
            yield "active", line[offset:]


def transform_links(private, text, origin, destination, moves):
    def replace(match):
        raw = match["link"] or match["definition"]
        resolved = referenced(private, origin, raw)
        if resolved is None:
            return match[0]
        target = resolved
        if private in resolved.parents:
            old = resolved.relative_to(private).as_posix()
            target = private / moves.get(old, old)
        new_dir = (private / destination).parent
        if target == resolved and new_dir == (private / origin).parent:
            return match[0]
        url = urlsplit(unescape(raw.strip("<>")))
        path = quote(Path(os.path.relpath(target, new_dir)).as_posix(), safe="/-._~")
        rewritten = urlunsplit(("", "", path, url.query, url.fragment))
        if raw.startswith("<"):
            rewritten = "<" + rewritten + ">"
        return match[0][:-len(raw)] + rewritten
    return "".join(LINK.sub(replace, part) if kind == "active" else part for kind, part in markdown_chunks(text))


def legacy_initiative_registers(private):
    """Recognize registers from the local format-1 opportunity branch, without trusting or modifying them."""
    home = private / "products"
    found = []
    if home.resolve() != home:
        return found
    for path in sorted(home.glob("*/initiatives.json")):
        if not SLUG.fullmatch(path.parent.name) or path.resolve() != path or not path.is_file():
            continue
        try:
            envelope = json.loads(path.read_bytes())
        except (UnicodeError, ValueError):
            continue
        if not isinstance(envelope, dict):
            continue
        record, signature = envelope.get("record"), envelope.get("signature")
        if (not isinstance(record, dict) or record.get("version") != 1 or record.get("product") != path.parent.name
                or not isinstance(signature, str) or not signature.startswith("-----BEGIN SSH SIGNATURE-----\n")):
            continue
        events = record.get("events")
        if not isinstance(events, list) or not events or not isinstance(events[0], dict):
            continue
        setup = events[0]
        refs = setup.get("references")
        if (setup.get("type") == "setup" and isinstance(refs, dict)
                and {"company_id", "product_id"} <= refs.keys()):
            found.append(path)
    return found


def require_supported_registers(private):
    paths = legacy_initiative_registers(private)
    if paths:
        names = ", ".join(str(path.relative_to(private)) for path in paths)
        raise ValueError(f"Format-1 opportunity register requires its original workflow checkout: {names}. "
                         "Keep its signed history and reviewed records together. "
                         "If this installation already moved them, restore the verified format-1 backup.")


def legacy_material(name):
    parts = Path(name).parts
    if name == metric_registry.PRIVATE:
        return False
    return parts[0] == "products" or (
        parts[0] == "context" and len(parts) > 1 and parts[1] not in {"company", "products", "initiatives", "pm", "sources"}
    )


def load_documents(private):
    docs, metadata = {}, {}
    for path in storage.inventory(private):
        rel = path.relative_to(private)
        if (not path.is_file() or not rel.parts or path.resolve() != path or
                any(p.startswith(".") or p == "secrets" for p in rel.parts)):
            continue
        if path.suffix.lower() not in TEXT_EXTENSIONS:
            if legacy_material(rel.as_posix()) and "sources" not in rel.parts:
                metadata[rel.as_posix()] = (upgrades.fingerprint(path), stat.S_IMODE(path.stat().st_mode))
            continue
        data = path.read_bytes()
        metadata[rel.as_posix()] = (digest(data), stat.S_IMODE(path.stat().st_mode))
        try:
            docs[rel.as_posix()] = data.decode("utf-8")
        except UnicodeError:
            continue
    return docs, metadata


def protected_sources(private, docs, ledger, saved):
    protected = set(saved.get("sources", []))
    protected.update(name for name, row in saved.get("retained", {}).items()
                     if row.get("disposition", {}).get("status") == "source")
    protected.update(name for name, entry in ledger.items() if entry.get("role") == "source")
    protected.update(name for name in docs if "sources" in Path(name).parts and not layout.is_customization(name))
    for name, text in docs.items():
        if not name.lower().endswith(".md") or name in protected or layout.is_customization(name):
            continue
        for match in LINK.finditer(records.section(text, "Sources") or ""):
            path = referenced(private, name, match["link"] or match["definition"])
            if path and private in path.parents:
                relative = path.relative_to(private)
                if (not layout.is_customization(relative) and path.resolve() == path
                        and not any(part.startswith(".") or part == "secrets" for part in relative.parts)):
                    protected.add(relative.as_posix())
    return {name for name in protected if not layout.is_customization(name)}


def ignored_names(private, names):
    names = list(names)
    if not names:
        return set()
    result = subprocess.run(["git", "-C", str(private), "check-ignore", "--no-index", "-z", "--stdin"],
                            input=b"\0".join(map(os.fsencode, names)) + b"\0", capture_output=True)
    if result.returncode not in {0, 1}:
        raise ValueError("Could not verify Git ignore rules for migration destinations")
    return {os.fsdecode(name) for name in result.stdout.split(b"\0") if name}


def ambiguous_component(private, name):
    directory = private
    for part in Path(name).parts:
        if not directory.exists():
            return False
        if not directory.is_dir() or directory.is_symlink():
            return True
        if any(child.name != part and child.name.casefold() == part.casefold() for child in directory.iterdir()):
            return True
        directory /= part
    return False


def reserved_paths(private):
    """Keep index entries, worktree files, and destinations the PM has staged for deletion."""
    paths = {path.relative_to(private) for path in storage.inventory(private)}
    deleted = subprocess.run(["git", "-C", str(private), "diff", "--cached", "--no-renames", "--name-only",
                              "--diff-filter=D", "-z", "--"], capture_output=True, check=True)
    paths.update(Path(os.fsdecode(name)) for name in deleted.stdout.split(b"\0") if name)
    return paths


def check_destinations(private, moves, notes):
    destinations = {}
    # A tracked but locally deleted destination is still the PM's pending change.
    occupied = {path.as_posix().casefold() for path in reserved_paths(private)}
    for old, new in moves.items():
        destinations.setdefault(new.casefold(), []).append(old)
    ignored = ignored_names(private, moves.values())
    for old, new in list(moves.items()):
        path = private / new
        if new in ignored:
            notes[old] = f"Private Git ignores the proposed destination {new}; keep the original visible."
            del moves[old]
            continue
        collisions = destinations[new.casefold()]
        if (len(collisions) > 1 or new.casefold() in occupied or path.exists() or path.is_symlink()
                or path.resolve() != path or ambiguous_component(private, new)):
            notes[old] = f"Resolve the occupied or ambiguous destination {new}; retain every original."
            del moves[old]
            continue


def note_moves(private, docs, moves, protected):
    for name, text in docs.items():
        if name in protected or name in moves or not text.startswith("<!-- pm: context-note -->"):
            continue
        owner = entity(name)
        if not owner or "records" not in Path(name).parts or not SLUG.fullmatch(Path(name).stem):
            continue
        rows, errors = records.table(text, "Filing", ("Field", "Value"))
        data = dict(rows)
        if errors or data.get("Basis") not in {"event-history", "maintained-reference"}:
            continue
        parent = re.fullmatch(r"\[Parent\]\(([^)]+)\)", data.get("Owning record", ""))
        path = referenced(private, name, parent[1]) if parent else None
        if path and private in path.parents:
            parent_name = path.relative_to(private).as_posix()
            if moves.get(parent_name, parent_name) == owner + "/overview.md" and path.is_file():
                moves[name] = owner + "/" + Path(name).name


def blocking_references(private, docs, moves, protected, guides):
    """Preserve opaque references and source bytes; never guess at rewriting them."""
    blocked = {}
    for name, text in docs.items():
        if name in {OLD_PROFILE, "settings.json"} or name in guides:
            continue
        markdown = Path(name).suffix.lower() in {".md", ".markdown"}
        if name in protected or layout.is_customization(name):
            for match in LINK.finditer(text):
                target = referenced(private, name, match["link"] or match["definition"])
                if target and private in target.parents:
                    subject = target.relative_to(private).as_posix()
                    if subject in moves:
                        owner = "Customization" if layout.is_customization(name) else "Original source"
                        blocked[subject] = f"{owner} {name} links here. Preserve that link before moving the record."
        residual = "".join(LINK.sub("", part) if kind in {"active", "literal"} else part for kind, part in markdown_chunks(text)) if markdown else text
        # Detect common opaque href, wiki, and path-valued configuration spellings. Keep
        # the old file reachable until someone can update the consumer in its own syntax.
        for match in re.finditer(r"""["']([^"'\r\n]+\.(?:md|pdf|csv|json)(?:[#?][^"'\r\n]*)?)["']|(?:href|src)\s*=\s*["']([^"']+)["']|(?:^|[\s"'`(])((?:[./\w%+-]+/)*[\w%+.-]+\.(?:md|pdf|csv|json))(?:[#?][^\s"'`)]*)?""",
                                 residual, re.I | re.M):
            token = next(group for group in match.groups() if group is not None)
            path = referenced(private, name, token)
            if path and private in path.parents:
                key = path.relative_to(private).as_posix()
                if key in moves:
                    blocked[key] = f"Review the nonstandard reference in {name} before moving this record."
                if name in moves and path.exists() and (private / name).parent != (private / moves[name]).parent:
                    blocked[name] = "Preserve this file's relative reference before moving it."
        for old in moves:
            if old in residual or re.search(r"\[\[" + re.escape(Path(old).stem) + r"(?:\||#|\]\])", residual):
                blocked[old] = f"Review the nonstandard reference in {name} before moving this record."
    return blocked


def dependent_moves(private, docs, moves):
    """A child with an unresolved parent keeps its old home until both can file correctly."""
    blocked = {}
    for name, dest in moves.items():
        if not dest.startswith("context/") or name in {OLD_PROFILE, *GUIDES}:
            continue
        owner = entity(name)
        if not owner:
            continue
        parents = []
        text = docs[name]
        for section, field in (("Context controls", "Parent context"), ("Filing", "Owning record")):
            body = records.section(text, section) or ""
            line = next((line for line in body.splitlines() if line.startswith(f"| {field} |")), "")
            match = LINK.search(line)
            if match:
                target = referenced(private, name, match["link"] or match["definition"])
                if target and private in target.parents:
                    parents.append(target.relative_to(private).as_posix())
        if any(legacy_material(parent) and parent not in moves for parent in parents):
            blocked[name] = "Keep this record with its existing parent until the parent's destination is resolved."
    return blocked


def known_seed(private, destination):
    path = private.parent / "tools/workspace-seed" / destination
    if path.is_file():
        return upgrades.installed_seed(private, destination)
    return None


def plan(private):
    require_supported_registers(private)
    original, state = upgrades.read_state(private)
    if conversion.pointer(private).exists():
        raise ValueError("Resume the previous filing transaction before migrating the layout")
    docs, metadata = load_documents(private)
    ledger = state.setdefault(upgrades.RULE, {})
    saved = receipt(private, state)
    protected = protected_sources(private, docs, ledger, saved)
    notes, moves, guides = {}, {}, {}
    for name in metadata.keys() - docs.keys() - protected:
        if legacy_material(name):
            notes[name] = "Preserve this file in place and identify its source, purpose and owner."
    for name, text in docs.items():
        if name in protected:
            continue
        if name in GUIDES:
            target = GUIDES[name]
            if digest(text.replace("\r\n", "\n").encode()) in OLD_GUIDES and known_seed(private, target) is not None:
                guides[name] = known_seed(private, target)
                if target != name:
                    moves[name] = target
            elif name == "products/README.md":
                notes[name] = "Preserve this customised product guide and decide which guidance belongs in reference or work."
            continue
        if name == OLD_PROFILE:
            moves[name] = PROFILE
            continue
        if not legacy_material(name):
            continue
        if Path(name).suffix.lower() == ".md":
            destination = classify(name, text)
            if destination:
                moves[name] = destination
            else:
                notes[name] = "Inspect the contents and owner before filing this existing record."
        else:
            notes[name] = "Keep this file in place until its purpose or original-source status is established."
    note_moves(private, docs, moves, protected)
    intended = moves.copy()
    check_destinations(private, moves, notes)
    # A mixed brief keeps its known entity identity while its working material awaits review.
    for old, target in list(moves.items()):
        if target.endswith("/overview.md") and (
                re.search(r"^#{1,6} (?:backlog|tasks|action items|project plan|execution plan|milestones)\s*$",
                          docs[old], re.I | re.M) or re.search(r"^[-*] \[[ xX]\] ", docs[old], re.M)):
            notes[old] = "Separate the active plan from the standing reference before filing this entity overview."
            del moves[old]
    blocked = blocking_references(private, docs, moves, protected, guides)
    notes.update(blocked)
    for old in blocked:
        del moves[old]
    while True:
        blocked = dependent_moves(private, docs, moves)
        if not blocked:
            break
        notes.update(blocked)
        for old in blocked:
            del moves[old]
    candidate_profile = None
    if OLD_PROFILE in moves:
        import pm_profile
        try:
            candidate_profile = pm_profile.from_legacy(private, docs[OLD_PROFILE].encode(), moves).decode()
        except (TypeError, ValueError, OSError) as exc:
            notes[OLD_PROFILE] = f"Preserve the legacy PM remit for repair: {exc}"
            del moves[OLD_PROFILE]
    # A retained JSON remit may contain workspace-relative goal paths.
    if OLD_PROFILE in metadata and OLD_PROFILE not in moves:
        for old in list(moves):
            # An opaque profile could refer to any legacy goal path.
            profile_text = unquote(docs.get(OLD_PROFILE, ""))
            if old in profile_text or (not profile_text and Path(moves[old]).parts[:2] == ("workspace", "goals")):
                notes[old] = "Repair the retained legacy PM profile's goal link before moving this record."
                del moves[old]
    for old in moves:
        notes.pop(old, None)

    writes = {}
    retired = {old: metadata[old][0] for old in moves}
    for name, before in docs.items():
        destination = moves.get(name, name)
        if name in protected or layout.is_customization(name):
            continue
        if name == OLD_PROFILE:
            if not candidate_profile:
                continue
            after = candidate_profile
        elif name in guides and (name not in notes):
            after = guides[name]
        elif Path(name).suffix.lower() in {".md", ".markdown"}:
            after = transform_links(private, before, name, destination, moves)
        else:
            continue
        if name != destination or after != before:
            writes[destination] = {"before": "absent" if name != destination else metadata[name][0],
                                   "text": after, "mode": metadata[name][1]}

    # Keep local annotations. Seed replacement is limited to positively identified stock copies.
    for guide in GUIDES.values():
        if guide not in docs and guide not in writes and not (private / guide).exists():
            if ignored_names(private, [guide]) or ambiguous_component(private, guide):
                notes[guide] = "The required guide destination is ignored or ambiguous. Resolve its path before adding the guide."
                metadata[guide] = ("absent", 0o600)
                continue
            data = known_seed(private, guide)
            if data is not None:
                writes[guide] = {"before": "absent", "text": data, "mode": 0o600}

    # Preserve the semantic audit and its review status, including immutable source identities.
    for old, new in moves.items():
        if old in ledger:
            row = ledger.pop(old)
            if row.pop("layout_review", False) and row.get("status") == "waiting":
                continue
            row["digest"] = digest(writes[new]["text"].encode())
            ledger[new] = row
        migrated = writes[new]["text"]
        kind = records.MARKER.match(migrated)
        if kind and kind[1] in records.CONTEXT_KINDS:
            template = private.parent / "templates" / f"{kind[1]}.md"
            if template.is_file() and records.structure_errors(
                kind[1], migrated, records.heading_order(kind[1], template.read_text(encoding="utf-8"))
            ):
                ledger[new] = {"status": "waiting", "note": "Review legacy headings and keep their source evidence.",
                               "digest": digest(migrated.encode())}
    for name in notes:
        if name in writes:
            metadata[name] = (digest(writes[name]["text"].encode()), writes[name]["mode"])
    for name, reason in notes.items():
        if name.endswith(".md") and metadata[name][0] != "absent":
            row = ledger.get(name)
            if row is None or row.get("layout_review"):
                ledger[name] = {"status": "waiting", "note": reason, "digest": metadata[name][0], "layout_review": True}
    for name in protected:
        if name in metadata and name.endswith(".md"):
            row = ledger.setdefault(name, {"status": "reviewed", "note": "Preserved the registered original source.",
                                           "digest": metadata[name][0]})
            row["role"] = "source"
            if row.pop("layout_review", False):
                row.update(status="reviewed", note="Preserved the registered original source.")
    prior = saved.get("retained", {})
    retained, outstanding = {}, []
    for name, reason in sorted(notes.items()):
        row = {"digest": metadata[name][0], "note": reason}
        if name in intended:
            row["destination"] = intended[name]
        reviewed = prior.get(name, {}).get("disposition", {})
        if reviewed.get("digest") == row["digest"]:
            row["disposition"] = reviewed
        retained[name] = row
        status = row.get("disposition", {}).get("status")
        if status == "reviewed" and name not in intended:
            continue
        outstanding.append({"path": name, "status": "waiting", "note": reviewed.get("note", reason) if status else reason,
                            "digest": row["digest"]})
    state[RULE] = {"version": 1}
    if retained:
        state[RULE]["retained"] = retained
    if protected:
        state[RULE]["sources"] = sorted(protected)
    after_state = upgrades.encode(state)
    if after_state != original:
        writes[upgrades.LEDGER] = {"before": upgrades.fingerprint(private / upgrades.LEDGER),
                                   "text": after_state, "mode": 0o600}
    return {"moves": moves, "outstanding": outstanding, "writes": writes, "retired": retired}


def blocked(private, canonical):
    """An unresolved existing brief prevents silently opening a second home."""
    if not private.is_dir() or not (private / ".git").is_dir():
        return []
    saved = receipt(private, upgrades.read_state(private)[1])
    if not saved:
        candidate = plan(private)
        change = candidate["writes"].get(upgrades.LEDGER)
        saved = json.loads(change["text"]).get(RULE, {}) if change else {}
    return sorted(name for name, row in saved.get("retained", {}).items()
                  if row.get("destination") == canonical and (private / name).is_file())


def recoveries(private, identifier, document):
    for name, before in document["retired"].items():
        original = private / name
        saved = private / ".git/pm-hub-recovery/filing" / identifier / name
        if original.exists() or original.is_symlink() or saved.resolve() != saved or upgrades.fingerprint(saved) != before:
            raise ValueError(f"Concurrent change to {name}; preserve the displaced file and resolve the layout journal")


def apply_plan(private, document):
    identifier = "layout-" + digest(upgrades.encode(document).encode())[:24]
    writes, retired = document["writes"], document["retired"]
    for name in (*writes, *retired):
        safe_path(private, name)
    invisible = ignored_names(private, (name for name, row in writes.items() if row["before"] == "absent"))
    if invisible:
        raise ValueError("A migration destination is now ignored. Keep the original and resolve: " + ", ".join(sorted(invisible)))
    for name, row in writes.items():
        if name != upgrades.LEDGER:
            conversion.recoverable_swap(private, identifier, name, row["before"], row["text"].encode())
            os.chmod(private / name, row["mode"])
    if ignored_names(private, document["moves"].values()):
        raise ValueError("Private ignore rules changed; retain originals before completing migration")
    for name, before in retired.items():
        conversion.recoverable_swap(private, identifier, name, before, None)
    # Recheck displaced inodes because an editor can continue writing after a rename.
    recoveries(private, identifier, document)
    for name, row in writes.items():
        if name != upgrades.LEDGER and upgrades.fingerprint(private / name) != digest(row["text"].encode()):
            raise ValueError(f"File changed during migration: {name}")
    if upgrades.LEDGER in writes:
        row = writes[upgrades.LEDGER]
        conversion.recoverable_swap(private, identifier, upgrades.LEDGER, row["before"], row["text"].encode())
    recoveries(private, identifier, document)
    journal_path(private).unlink()


def read_journal(private):
    envelope = json.loads(journal_path(private).read_text(encoding="utf-8"))
    if (not isinstance(envelope, dict) or set(envelope) != {"format", "sha256", "plan"}
            or envelope["format"] != 1 or digest(upgrades.encode(envelope["plan"]).encode()) != envelope["sha256"]):
        raise ValueError("Invalid layout journal; restore the verified copy before resuming")
    doc = envelope["plan"]
    if (not isinstance(doc, dict) or set(doc) != {"moves", "outstanding", "writes", "retired"}
            or not all(isinstance(doc[key], dict) for key in ["moves", "writes", "retired"])
            or not isinstance(doc["outstanding"], list) or set(doc["moves"]) != set(doc["retired"])
            or len(set(doc["moves"].values())) != len(doc["moves"]) or doc["retired"].keys() & doc["writes"].keys()):
        raise ValueError("Invalid layout plan structure")
    for name, row in doc["writes"].items():
        safe_path(private, name)
        if (not isinstance(row, dict) or set(row) != {"before", "mode", "text"} or not isinstance(row["text"], str)
                or not re.fullmatch(r"absent|[a-f0-9]{64}", str(row["before"]))
                or type(row["mode"]) != int or not 0 <= row["mode"] <= 0o7777):
            raise ValueError("Invalid layout journal file")
    for name, checksum in doc["retired"].items():
        safe_path(private, name)
        dest = doc["moves"][name]
        if not re.fullmatch(r"[a-f0-9]{64}", str(checksum)) or doc["writes"].get(dest, {}).get("before") != "absent":
            raise ValueError("Invalid layout journal move")
    return doc


def run(private, *, apply=False):
    """Preview without writes, or apply under the caller's lock and full installation backup."""
    private = private.resolve()
    journal = journal_path(private)
    if journal.is_file():
        require_supported_registers(private)
        document = read_journal(private)
    else:
        document = plan(private)
    changed = bool(document["writes"] or document["retired"])
    if apply and changed:
        if not journal.exists():
            envelope = {"format": 1, "sha256": digest(upgrades.encode(document).encode()), "plan": document}
            storage.replace_text(journal, None, upgrades.encode(envelope))
        apply_plan(private, document)
    return {"moves": document["moves"], "outstanding": document["outstanding"], "changed": changed}
